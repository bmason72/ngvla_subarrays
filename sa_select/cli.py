"""
Command-line interface to sa_select.

Thin argparse wrapper around ``ObservingRequest`` / ``select_subarrays``; all
the actual logic (feasibility, curve lookup, sensitivity) lives in the
package.  Run as ``python -m sa_select --resolution ... --frequency ...``.

Configuration revisions: ``--rev`` / ``--sim-mode`` select any campaign
registered in data/config_registry.csv (default: revF, track).  Release
scope note (WRAPUP.md, 17 Aug 2026): the released curves are revF/track
(point-source AND imaging), revD/track (point-source only), revC/track
(point-source only) -- an imaging query against a point-source-only
release prints a warning but still runs (the imaging samples exist in the
tables; they are simply not release-validated).

Batch mode: ``--batch cases.csv`` evaluates one request per CSV row --
the way to reproduce an envelope-observing-program (EOP) case list.
Recognized columns (all optional except resolution and frequency; empty
cells fall back to the command-line flags): ``case, resolution, frequency,
sensitivity, sensitivity_unit, las, imaging, beam_margin, skirt_threshold,
optimize, delta_v``.  ``imaging`` accepts true/false/1/0/imaging/point-source.
Output is one CSV row per case per ranked feasible candidate (``--top N``
per case, default 1), with infeasible cases reported on a single row.

Exit status: 0 if at least one subarray is feasible for the request (all
requests, in batch mode), 2 otherwise (tables are printed either way, with
exclusion reasons).
"""

import argparse
import csv
import sys

from .schema import ObservingRequest
from .selector import select_subarrays
from .curves import CurveLibrary
from .heuristics import HEURISTICS

#: (rev, sim_mode) combinations whose IMAGING curves are outside the release
#: scope (WRAPUP.md): queries still run, with a warning.
PTSRC_ONLY_RELEASE = {("revD", "track"), ("revC", "track")}

_TRUE = {"1", "true", "yes", "imaging"}
_FALSE = {"0", "false", "no", "point-source", "ptsrc", "pointsource"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sa_select",
        description="Rank NGVLA subarrays (+ tclean weighting) for a "
                    "requested beam, frequency, sensitivity, and LAS.",
    )
    p.add_argument("--resolution", type=float, default=None,
                   help="target beam FWHM, arcsec (required unless --batch)")
    p.add_argument("--frequency", type=float, default=None,
                   help="observing frequency, GHz (required unless --batch)")
    p.add_argument("--sensitivity", type=float, default=None,
                   help="target point-source sensitivity goal, in --unit "
                        "(omit for a beam-only query, no integration time)")
    p.add_argument("--unit", dest="sensitivity_unit", choices=["Jy/beam", "K"],
                   default="Jy/beam",
                   help="unit of --sensitivity (default: Jy/beam)")
    p.add_argument("--las", type=float, default=None,
                   help="largest angular scale needed, arcsec")

    imaging = p.add_mutually_exclusive_group()
    imaging.add_argument("--imaging", dest="imaging", action="store_true",
                         default=True,
                         help="imaging project: apply the PSF-skirt "
                              "constraint (default)")
    imaging.add_argument("--point-source", dest="imaging", action="store_false",
                         help="point-source detection: ignore PSF quality")

    p.add_argument("--beam-margin", type=float, default=0.05,
                   help="fractional tolerance on the achieved beam "
                        "(default: 0.05)")
    p.add_argument("--skirt-threshold", type=float, default=0.10,
                   help="max PSF level at r = 1 FWHM, imaging only "
                        "(default: 0.10)")
    p.add_argument("--optimize", choices=sorted(HEURISTICS), default="antenna_hours",
                   help="ranking heuristic (default: antenna_hours)")
    p.add_argument("--delta-v", dest="delta_v", type=float, default=None,
                   help="channel width, m/s, for a spectral-line goal "
                        "(default: continuum)")

    p.add_argument("--rev", default="revF",
                   help="configuration revision (config_registry.csv; "
                        "default: revF)")
    p.add_argument("--sim-mode", default="track",
                   help="simulation mode the curves were measured in "
                        "(default: track)")
    p.add_argument("--stroh", metavar="SUBARRAY_DATA_JSON", default=None,
                   help="query M. Stroh's curve delivery instead of a "
                        "registered campaign: path to his subarray_data.json "
                        "(point-source curves only; overrides --rev/--sim-mode;"
                        " see sa_select/stroh.py for the conventions applied)")

    p.add_argument("--batch", metavar="CASES_CSV", default=None,
                   help="evaluate one request per CSV row (see module "
                        "docstring for the columns); prints a combined CSV")
    p.add_argument("--top", type=int, default=1,
                   help="batch mode: ranked candidates to print per case "
                        "(default: 1)")
    p.add_argument("--rows", action="store_true",
                   help="print to_rows() as CSV instead of the summary table")
    return p


def _parse_imaging(text, default):
    v = text.strip().lower()
    if not v:
        return default
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise ValueError("unrecognized imaging value %r" % text)


def _request_from_row(row, args):
    """Build an ObservingRequest from one batch-CSV row; empty/missing cells
    fall back to the command-line flags."""
    def get(col, cast, fallback):
        v = (row.get(col) or "").strip()
        return cast(v) if v else fallback

    return ObservingRequest(
        resolution=get("resolution", float, args.resolution),
        frequency=get("frequency", float, args.frequency),
        sensitivity=get("sensitivity", float, args.sensitivity),
        sensitivity_unit=get("sensitivity_unit", str, args.sensitivity_unit),
        las=get("las", float, args.las),
        imaging=_parse_imaging(row.get("imaging") or "", args.imaging),
        beam_margin=get("beam_margin", float, args.beam_margin),
        skirt_threshold=get("skirt_threshold", float, args.skirt_threshold),
        optimize=get("optimize", str, args.optimize),
        delta_v=get("delta_v", float, args.delta_v),
    )


def _warn_release_scope(rev, sim_mode, imaging):
    if imaging and (rev, sim_mode) in PTSRC_ONLY_RELEASE:
        print("warning: imaging curves for %s/%s are outside the released "
              "scope (point-source only); results are not release-validated"
              % (rev, sim_mode), file=sys.stderr)


def _run_batch(args, library) -> int:
    with open(args.batch, newline="") as f:
        cases = list(csv.DictReader(f))
    if not cases:
        print("error: %s has no data rows" % args.batch, file=sys.stderr)
        return 2

    fields = ["case", "rank"]
    all_feasible = True
    rows_out = []
    warned_imaging = False
    for i, row in enumerate(cases):
        case_id = (row.get("case") or "").strip() or str(i + 1)
        try:
            request = _request_from_row(row, args)
        except (TypeError, ValueError) as e:
            print("error: case %s: %s" % (case_id, e), file=sys.stderr)
            return 2
        if request.imaging:
            warned_imaging = True
        result = select_subarrays(request, library=library)
        feasible = result.feasible
        if not feasible:
            all_feasible = False
        picks = feasible[:max(args.top, 1)] if feasible else []
        for rank, c in enumerate(picks, start=1):
            r = result.to_rows()[result.candidates.index(c)]
            r.update(case=case_id, rank=rank)
            rows_out.append(r)
        if not picks:
            reasons = "; ".join("%s: %s" % (c.subarray.name, "; ".join(c.reasons))
                                for c in result.infeasible)
            rows_out.append(dict(case=case_id, rank="", feasible=False,
                                 reasons=reasons))
    if warned_imaging:
        _warn_release_scope(args.rev, args.sim_mode, True)

    # union of keys, stable order: case/rank first, then to_rows() order
    for r in rows_out:
        for k in r:
            if k not in fields:
                fields.append(k)
    out = csv.DictWriter(sys.stdout, fieldnames=fields)
    out.writeheader()
    out.writerows(rows_out)
    return 0 if all_feasible else 2


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.stroh is not None:
        from . import stroh
        try:
            library = stroh.curve_library(args.stroh)
        except (ValueError, OSError, KeyError) as e:
            print("error: cannot load Stroh curves from %s: %s"
                  % (args.stroh, e), file=sys.stderr)
            return 2
        args.rev, args.sim_mode = "stroh", "n/a"    # for the header line
    else:
        try:
            library = CurveLibrary.for_config(args.rev, args.sim_mode)
        except (ValueError, OSError) as e:
            print("error: cannot load curves for %s/%s: %s"
                  % (args.rev, args.sim_mode, e), file=sys.stderr)
            return 2

    if args.batch is not None:
        return _run_batch(args, library)

    if args.resolution is None or args.frequency is None:
        print("error: --resolution and --frequency are required "
              "(unless --batch)", file=sys.stderr)
        return 2

    try:
        request = ObservingRequest(
            resolution=args.resolution,
            frequency=args.frequency,
            sensitivity=args.sensitivity,
            sensitivity_unit=args.sensitivity_unit,
            las=args.las,
            imaging=args.imaging,
            beam_margin=args.beam_margin,
            skirt_threshold=args.skirt_threshold,
            optimize=args.optimize,
            delta_v=args.delta_v,
        )
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2

    _warn_release_scope(args.rev, args.sim_mode, request.imaging)
    result = select_subarrays(request, library=library)

    print("# %s/%s  resolution=%.4g\" frequency=%.4g GHz  %s  optimize=%s"
          % (args.rev, args.sim_mode, request.resolution, request.frequency,
             "imaging" if request.imaging else "point-source",
             request.optimize))

    if args.rows:
        rows = result.to_rows()
        writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    else:
        print(result.table())

    return 0 if result.feasible else 2


if __name__ == "__main__":
    sys.exit(main())

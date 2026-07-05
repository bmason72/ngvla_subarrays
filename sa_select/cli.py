"""
Command-line interface to sa_select.

Thin argparse wrapper around ``ObservingRequest`` / ``select_subarrays``; all
the actual logic (feasibility, curve lookup, sensitivity) lives in the
package.  Run as ``python -m sa_select --resolution ... --frequency ...``.

Exit status: 0 if at least one subarray is feasible for the request, 2 if
none is (the table/CSV is still printed either way, with exclusion reasons).
"""

import argparse
import csv
import sys

from .schema import ObservingRequest
from .selector import select_subarrays
from .heuristics import HEURISTICS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sa_select",
        description="Rank NGVLA Rev F subarrays (+ tclean weighting) for a "
                    "requested beam, frequency, sensitivity, and LAS.",
    )
    p.add_argument("--resolution", type=float, required=True,
                   help="target beam FWHM, arcsec")
    p.add_argument("--frequency", type=float, required=True,
                   help="observing frequency, GHz")
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
    p.add_argument("--rows", action="store_true",
                   help="print to_rows() as CSV instead of the summary table")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

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

    result = select_subarrays(request)

    print("# resolution=%.4g\" frequency=%.4g GHz  %s  optimize=%s"
          % (request.resolution, request.frequency,
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

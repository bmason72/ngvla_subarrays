"""
PSF-inspector P2: anchor backfill.

Every point the report draws as a CURVE ANCHOR (an interpolation endpoint of a
displayed curve) should have a PSF profile line WITH major/minor-axis cuts, so
the report's PSF inspector can show the beam shape (incl. the snapshot
elongation the azimuthal average hides).  Sweeps captured before the cut
feature (feature v11 profiles are azimuthal-only; revF/track predates even
those) left many anchors without cuts.  This is a resumable job that finds the
anchors lacking a cut-bearing profile and RE-IMAGES only those, appending a
profile+cuts JSONL line via exactly the sweep's capture path.

It NEVER touches curve data.  The results CSVs are byte-identical after a run:
the only writes are appended lines to results<suffix>/profiles/<stem>.jsonl.
(The Sweep it drives is a ReadOnlyResultsSweep whose results-write path raises.)

Anchor set (per subarray), built EXACTLY as refine.py builds curves:
  refine.samples_from(Sweep) -> make_report.build_curve
    * the s0=0.10 imaging curve   (skirt_max = refine.SKIRT_MAX)
    * the point-source curve       (skirt_max = None)
  both clipped at the subarray's beam cap (refine.curve_max_res_mas), UNION of
  their anchor env_keys, PLUS the natural reference point.  Keys are spelled
  through make_report.env_key + sweep.point_key + export_psf_data.normalize_key
  so they match the results CSV rows AND the profiles JSONL keys (the last
  handles the negative-zero "-0.00"/"0.00" spelling gotcha).

Re-imaging uses the EXACT recorded convention from the anchor's results-CSV
row (weighting/robust/taper/imsize and the row's cell_arcsec -- NOT recomputed)
via the same sweep.run_tclean/tclean_kwargs helper run_point uses, so the PSF
is byte-consistent with the original measurement.

Combo routing is entirely via config.py (NGVLA_REV / NGVLA_SIM_MODE and the
$WORK/$SCRATCH bases); the DEFAULT combo (revF, track, plain results/) needs no
environment at all.

Run (CASA's python via the casapy wrapper on TACC):
  casapy backfill_psf.py                 # all offered subarrays, active combo
  casapy backfill_psf.py core spiral     # just these
  casapy backfill_psf.py --dry-run       # count anchors/needed, image nothing
  casapy backfill_psf.py --limit 20      # image at most 20 anchors this run
"""

import argparse
import json
import os
import shutil
import sys
import traceback

from config import (RESULTS_DIR, PROFILE_DIR, MIN_UVRANGE_M, REV, SIM_MODE)
from sweep import Sweep, point_key, tclean_kwargs, run_tclean, TCLEAN_EXTS
from measure import beam_arcsec
from make_report import build_curve, env_key, offered_order, registry_paths
from refine import samples_from, curve_max_res_mas, SKIRT_MAX
from export_psf_data import normalize_key


# ------------------------------------------------------------------------- #
# the no-curve-data-write guarantee
# ------------------------------------------------------------------------- #
class ReadOnlyResultsSweep(Sweep):
    """A Sweep that physically cannot write curve data.

    Backfill re-images measured anchor points ONLY to capture their PSF
    profile + axis cuts; it must never alter a results CSV ("must never touch
    curve data").  `record` is the sole results writer every Sweep results
    write flows through (run_point / skip_point both call it), so overriding it
    to raise turns any accidental results write -- now or in future edits --
    into a loud failure instead of silent curve corruption.  `capture_profile`
    writes only to PROFILE_DIR and is deliberately left untouched.
    """

    def record(self, row):
        raise RuntimeError(
            "backfill must never write curve data (ReadOnlyResultsSweep.record)")


# ------------------------------------------------------------------------- #
# key spelling: consistent across CSV rows, JSONL keys and curve anchors
# ------------------------------------------------------------------------- #
def _canonical_key(weighting, robust, taper):
    """point_key spelling used consistently for results rows, profile JSONL
    keys, and curve anchors -- with export_psf_data's negative-zero
    normalization applied, so a "-0.00" robust and a "0.00" robust never
    mismatch (make_report/JS fold -0.0 -> 0.0; a re-run refine point can still
    spell it "-0.00" in the CSV/JSONL)."""
    return normalize_key(point_key(weighting, robust, taper))


NATURAL_KEY = _canonical_key("natural", 2.0, 0.0)   # the eta=1 reference point


# ------------------------------------------------------------------------- #
# anchor set + needs-backfill filtering (all CASA-free)
# ------------------------------------------------------------------------- #
def anchor_keys_from_samples(samples, max_res=None):
    """Canonical keys of the anchor points the two displayed curves interpolate
    between, plus the natural reference.

    Built EXACTLY as refine.py builds its curves (make_report.build_curve): the
    s0=0.10 imaging curve and the point-source curve, both clipped at the beam
    cap (max_res).  Each curve point carries env_keys = its measured
    (weighting, robust, taper) anchors; env_key canonicalizes them (natural's
    robust None -> 2.0, -0.0 -> 0.0) and _canonical_key spells them to match
    the CSV rows and JSONL keys.
    """
    keys = set()
    # Scope = the s0=0.10 imaging curve + the point-source curve + natural, the
    # bmason-approved P2 spec.  make_report strips env_keys for the non-default
    # skirt setpoints (0.05/0.15/0.20), so the report cannot reference their
    # anchors -- no backfill is owed for them.  If a future report ever ships
    # env_keys for other setpoints, widen this (add their skirt_max here).
    for skirt_max in (SKIRT_MAX, None):        # imaging (s0=0.10), point-source
        for c in build_curve(samples, skirt_max, max_res=max_res):
            for raw in c["env_keys"]:
                k = env_key(raw)
                if k is not None:
                    keys.add(_canonical_key(*k))
    keys.add(NATURAL_KEY)
    return keys


def anchor_keys(sweep, subarray):
    """Anchor keys for a subarray from its recorded sweep results.  Empty when
    the subarray has no natural (eta=1) reference yet -- then it has no
    displayed curve and nothing to backfill."""
    if sweep.measured("natural", 2.0, 0.0) is None:
        return set()
    return anchor_keys_from_samples(samples_from(sweep),
                                    curve_max_res_mas(subarray))


def cut_bearing_keys(profile_lines):
    """{canonical_key} of profile JSONL lines that ALREADY carry axis cuts.

    Loader convention (sweep.capture_profile): the JSONL is append-only and the
    LAST line per key wins -- so a later azimuthal-only re-measure correctly
    supersedes an earlier cut-bearing line (that key then needs backfill
    again).  A line "has cuts" iff it carries "cut_maj".  Keys are
    normalize_key-canonicalized to match the anchor keys.
    """
    has_cut = {}                               # canonical_key -> bool (last wins)
    for line in profile_lines:
        try:
            rec = json.loads(line)
            key = rec["key"]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue                           # malformed line -> skip, like the exporter
        if not isinstance(key, str):
            continue
        has_cut[normalize_key(key)] = ("cut_maj" in rec)
    return {k for k, has in has_cut.items() if has}


def load_profile_lines(subarray):
    """The subarray's profile JSONL lines (empty list if none yet)."""
    stem = subarray.replace("+", "_").replace("-", "_")
    path = os.path.join(PROFILE_DIR, stem + ".jsonl")
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        return f.read().splitlines()


def row_index(sweep):
    """{canonical_key: results row} for every recorded point, so an anchor key
    resolves to the row whose exact convention it must be re-imaged with."""
    return {normalize_key(k): row for k, row in sweep.rows.items()}


def plan(sweep, subarray):
    """(anchors, already_cut_bearing, to_image) canonical-key sets."""
    anchors = anchor_keys(sweep, subarray)
    already = anchors & cut_bearing_keys(load_profile_lines(subarray))
    return anchors, already, anchors - already


# ------------------------------------------------------------------------- #
# re-imaging (the only CASA part)
# ------------------------------------------------------------------------- #
def _remove_products(name):
    """Delete every tclean product for image base `name` (never the MS)."""
    for ext in TCLEAN_EXTS:
        shutil.rmtree(name + ext, ignore_errors=True)


def backfill_one(sweep, subarray, key, row):
    """Re-image ONE anchor with the EXACT recorded convention and append its
    profile+cuts JSONL line.  Writes nothing but the profile line; cleans up
    the tclean products (never the MS).

    Returns True iff a cut-bearing line was written; False if the capture
    degraded to an azimuthal-only line (capture_profile swallows axis-cut
    failures), so the caller does NOT count an azimuthal-only fallback as a
    resolved anchor."""
    sweep.ensure_ready()                       # MS reused (make_ms skips existing)
    weighting = row["weighting"]
    robust = float(row["robust"])
    taper_mas = float(row["taper_mas"])
    imsize = int(row["imsize"])
    cell_arcsec = float(row["cell_arcsec"])    # from the row, NOT recomputed
    min_uvrange_m = MIN_UVRANGE_M.get(subarray)
    # JSONL key: run_point's exact spelling for this point (matches earlier
    # azimuthal-only lines; the exporter normalizes both anyway)
    jsonl_key = point_key(weighting, robust, taper_mas)
    name = os.path.join(sweep.workdir, "backfill_" + key)
    # the workdir path is STABLE across runs, so a walltime SIGKILL can leave
    # partial products from a prior attempt under this exact imagename; clear
    # them first so tclean never reuses a half-written image (the finally-block
    # cleanup below handles the normal path)
    _remove_products(name)
    try:
        run_tclean(**tclean_kwargs(sweep.vis, name, weighting, robust,
                                   taper_mas, imsize, cell_arcsec,
                                   min_uvrange_m))
        bmaj, bmin, bpa = beam_arcsec(name + ".image")
        res_geo = float((bmaj * bmin) ** 0.5)
        # same capture path P1 built (azimuthal profile + major/minor cuts)
        return bool(sweep.capture_profile(jsonl_key, name + ".psf", res_geo,
                                          beam=(bmaj, bmin, bpa)))
    finally:
        _remove_products(name)


def backfill_subarray(subarray, dry_run=False, limit=None):
    """Backfill one subarray's anchors.

    Returns dict(imaged, unresolved, deferred, ran):
      * imaged      -- anchors that gained a cut-bearing line;
      * unresolved  -- anchors ATTEMPTED but not resolved: a missing/unusable
                       results row, an imaging exception, or an azimuthal-only
                       fallback (axis-cut capture failed).  These must surface
                       as a nonzero exit so a resubmit retries them;
      * deferred    -- anchors not attempted because --limit was hit (a rerun
                       covers them; NOT a failure);
      * ran         -- tclean calls made (charged against a global --limit).

    A dry run images nothing and makes no CASA imaging calls."""
    sweep = ReadOnlyResultsSweep(subarray)
    anchors, already, todo = plan(sweep, subarray)
    todo = sorted(todo)
    print("%s: %d anchors, %d already cut-bearing, %d to image"
          % (subarray, len(anchors), len(already), len(todo)))
    if dry_run or not todo:
        return dict(imaged=0, unresolved=0, deferred=0, ran=0)

    idx = row_index(sweep)
    n_imaged = n_unresolved = n_ran = 0
    processed = 0
    for key in todo:
        if limit is not None and n_ran >= limit:
            break                              # remaining are --limit deferred
        processed += 1
        row = idx.get(key)
        if (row is None or row.get("status") not in ("ok", "capped")
                or not (row.get("cell_arcsec") and row.get("imsize"))):
            print("  UNRESOLVED %s: no re-imageable results row" % key,
                  file=sys.stderr)
            n_unresolved += 1
            continue                           # no imaging; does not charge --limit
        print("  imaging %s ..." % key, flush=True)
        n_ran += 1
        try:
            cuts_ok = backfill_one(sweep, subarray, key, row)
        except Exception as e:
            traceback.print_exc()
            print("  UNRESOLVED %s: backfill raised: %s" % (key, e),
                  file=sys.stderr)
            n_unresolved += 1
            continue
        if cuts_ok:
            n_imaged += 1
        else:
            print("  UNRESOLVED %s: only an azimuthal-only line was written "
                  "(axis-cut capture failed)" % key, file=sys.stderr)
            n_unresolved += 1
    deferred = len(todo) - processed
    tail = "" if deferred == 0 else " (%d deferred by --limit)" % deferred
    print("%s done: imaged %d, unresolved %d%s"
          % (subarray, n_imaged, n_unresolved, tail))
    return dict(imaged=n_imaged, unresolved=n_unresolved, deferred=deferred,
                ran=n_ran)


# ------------------------------------------------------------------------- #
# CLI
# ------------------------------------------------------------------------- #
def main():
    offered = offered_order(registry_paths(REV, SIM_MODE)[0])
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subarrays", nargs="*",
                    help="subarrays to backfill (default: all offered for the "
                         "active %s/%s combo: %s)"
                         % (REV, SIM_MODE, ", ".join(offered)))
    ap.add_argument("--dry-run", action="store_true",
                    help="list per subarray: n anchors / n already cut-bearing "
                         "/ n to image, and image nothing (no CASA imaging)")
    ap.add_argument("--limit", type=int, default=None,
                    help="image at most N anchors this run (resumability "
                         "covers the rest)")
    args = ap.parse_args()

    targets = args.subarrays or offered
    unknown = [s for s in targets if s not in offered]
    if unknown:
        ap.error("not offered for %s/%s: %s\noffered: %s"
                 % (REV, SIM_MODE, ", ".join(unknown), ", ".join(offered)))

    print("backfill combo: %s/%s\n  results  = %s\n  profiles = %s"
          % (REV, SIM_MODE, RESULTS_DIR, PROFILE_DIR))
    remaining = args.limit
    totals = dict(imaged=0, unresolved=0, deferred=0, ran=0)
    for sa in targets:
        res = backfill_subarray(sa, dry_run=args.dry_run, limit=remaining)
        for k in totals:
            totals[k] += res[k]
        if remaining is not None and not args.dry_run:
            remaining -= res["ran"]            # only imaging charges the budget
            if remaining <= 0:
                print("global --limit reached; rerun to continue the rest")
                break
    if not args.dry_run:
        print("backfill complete: imaged %d, unresolved %d, deferred %d"
              % (totals["imaged"], totals["unresolved"], totals["deferred"]))
        # a nonzero exit makes the sbatch task fail so a resubmit retries the
        # unresolved anchors (a resolved anchor is skipped as already
        # cut-bearing, so a retry only redoes what still needs it)
        if totals["unresolved"] > 0:
            print("EXIT NONZERO: %d anchor(s) unresolved (see the UNRESOLVED "
                  "lines above); resubmit to retry" % totals["unresolved"],
                  file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()

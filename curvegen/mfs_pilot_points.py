#!/usr/bin/env python
"""
Generate the MFS imaging pilot's non-seed lattice points for one subarray
(MFS-3 imaging half, docs/plans/mfs-imaging-pilot-spec.md).

The nchan-convergence pilot compares the SAME lattice points across two (or
more) nchan variants, so the point list has to be computed ONCE, from the
REFERENCE variant's results (the first nchan in the campaign's --nchan-list,
e.g. nchan027), and then reused verbatim for every other variant.  That is
what this script's caller (mfs_imaging_pilot.sbatch) does: run this script
once under the reference variant's environment, then feed the same points.json
to `sweep.py <sa> --points-file` for every variant.

Point construction (10 points, both seeds excluded since sweep.py's seeds-only
pass already measures them):
  * natural x {mid, coarse}                                        (2 points)
  * briggs r in {-2.0, -0.4, 1.2} x taper in {0, mid, coarse}       (9 combos,
    minus (r=-2.0, taper=0) which IS the briggs seed)               (8 points)
`mid`/`coarse` are tapers[6] and tapers[8] of the subarray's own canonical
14-level taper grid (config.taper_list_mas), anchored to its measured seed
resolutions (res_fine from the briggs r=-2 seed, res_nat from the natural
seed) -- exactly the grid `sweep.py`'s full lattice uses, so every pilot point
is guaranteed to be a member of that lattice (`run_points` requires this).

Run (under the pilot env of the REFERENCE nchan variant, e.g. nchan027):
    /work2/10240/bmason72/stampede3/casaenv/bin/casapy mfs_pilot_points.py \\
        core --out points_core.json
"""

import argparse
import csv
import json
import os
import sys

from adaptive_support import point_key

# the three briggs robusts probed at each of the three tapers (0, mid, coarse)
PILOT_ROBUSTS = (-2.0, -0.4, 1.2)
SEED_NATURAL = ("natural", 2.0, 0.0)
SEED_FINE = ("briggs", -2.0, 0.0)
# indices into config.taper_list_mas()'s 14-level grid
MID_TAPER_INDEX = 6
COARSE_TAPER_INDEX = 8


def _csv_path(results_dir, subarray):
    return os.path.join(
        results_dir, subarray.replace("+", "_").replace("-", "_") + ".csv")


def read_seed_rows(results_dir, subarray):
    """{point_key: row} for every row recorded for `subarray`.

    Returns {} (not an error) if the results CSV does not exist yet -- the
    caller (build_points) is what raises loudly when a seed is missing.
    """
    path = _csv_path(results_dir, subarray)
    rows = {}
    if os.path.isfile(path):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                rows[point_key(row["weighting"], row["robust"],
                               row["taper_mas"])] = row
    return rows


def _canon(weighting, robust, taper):
    """Round to point_key precision (match adaptive.canon_rt)."""
    r = round(float(robust), 2)
    t = round(float(taper), 3)
    if r == 0.0:
        r = 0.0
    if t == 0.0:
        t = 0.0
    return [weighting, r, t]


def build_points(rows, subarray, taper_list_mas):
    """Return the 10 non-seed [weighting, robust, taper_mas] pilot points.

    `rows` is a {point_key: row} dict (e.g. from read_seed_rows).
    `taper_list_mas` is config.taper_list_mas, injected so this function has
    no config/CASA dependency and is trivially unit-testable.

    Raises RuntimeError if either seed is missing or not status=ok.
    """
    nat_key = point_key(*SEED_NATURAL)
    fine_key = point_key(*SEED_FINE)
    nat = rows.get(nat_key)
    fine = rows.get(fine_key)
    if not (nat and nat.get("status") == "ok"):
        raise RuntimeError(
            "%s: natural seed missing or not ok (%s) -- run "
            "'sweep.py %s --seeds-only' first" % (subarray, nat_key, subarray))
    if not (fine and fine.get("status") == "ok"):
        raise RuntimeError(
            "%s: briggs r=-2 seed missing or not ok (%s) -- run "
            "'sweep.py %s --seeds-only' first" % (subarray, fine_key, subarray))

    res_nat_mas = float(nat["res_geo_arcsec"]) * 1e3
    res_fine_mas = float(fine["res_geo_arcsec"]) * 1e3
    tapers = taper_list_mas(res_fine_mas, res_nat_mas)
    mid = tapers[MID_TAPER_INDEX]
    coarse = tapers[COARSE_TAPER_INDEX]

    combos = [("natural", 2.0, mid), ("natural", 2.0, coarse)]
    for robust in PILOT_ROBUSTS:
        for taper in (0.0, mid, coarse):
            if robust == -2.0 and taper == 0.0:
                continue     # already the briggs seed; don't re-request it
            combos.append(("briggs", robust, taper))

    return [_canon(w, r, t) for w, r, t in combos]


def generate_points(subarray, results_dir, taper_list_mas):
    """read_seed_rows + build_points, the pair main() drives."""
    rows = read_seed_rows(results_dir, subarray)
    return build_points(rows, subarray, taper_list_mas)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subarray")
    ap.add_argument("--out", required=True,
                    help="output JSON path (a [weighting, robust, taper_mas] "
                         "list, ready for sweep.py --points-file)")
    args = ap.parse_args(argv)

    from config import RESULTS_DIR, SUBARRAYS, taper_list_mas
    if args.subarray not in SUBARRAYS:
        print("error: unknown subarray %r for the active (rev, sim_mode, "
              "band); known: %s" % (args.subarray, sorted(SUBARRAYS)),
              file=sys.stderr)
        return 2

    try:
        points = generate_points(args.subarray, RESULTS_DIR, taper_list_mas)
    except RuntimeError as e:
        print("error:", e, file=sys.stderr)
        return 1

    outdir = os.path.dirname(args.out)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(points, f, indent=2)
    print("%s: wrote %d pilot points to %s" % (args.subarray, len(points), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

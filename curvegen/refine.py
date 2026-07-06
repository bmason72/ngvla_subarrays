"""
Targeted refinement of the imaging curve: wherever the min-eta sculpted
curve jumps by more than --max-step in eta between adjacent resolutions,
measure a handful of new (robust, taper) points bracketing the two winners,
and repeat for a few rounds.

Rationale: the sweep lattice quantizes robust (0.4 steps) and taper (log
steps), but the true optimum rides the skirt = 10% contour between nodes;
at boundary crossings the discrete curve jumps.  Refining only where jumps
occur keeps the extra imaging cost tiny (tens of points, not a lattice
doubling).  Runs on top of sweep.py's resumable results, so refined points
are permanent and re-runs are free.

Run (from curvegen/, CASA's python3):
  .../python3 refine.py core                     # default 3 rounds, step 0.25
  .../python3 refine.py spiral+mid --rounds 2
"""

import argparse

from config import SUBARRAYS
from sweep import Sweep, point_key
from make_report import build_curve, ETA_CAP

SKIRT_MAX = 0.10
GAP_RATIO = 1.35          # res jumps beyond this are infeasibility gaps


def samples_from(sweep):
    """ok rows -> sample dicts with eta relative to the natural reference."""
    nat = sweep.measured("natural", 2.0, 0.0)
    sigma_nat = float(nat["sigma_dirty"])
    out = []
    for row in sweep.rows.values():
        if row["status"] != "ok":
            continue
        out.append(dict(
            res=float(row["res_geo_arcsec"]) * 1e3,
            eta=float(row["sigma_dirty"]) / sigma_nat,
            skirt=float(row["skirt"]),
            weighting=row["weighting"],
            robust=float(row["robust"]),
            taper=float(row["taper_mas"]),
        ))
    return out


def candidates_between(a, b):
    """New (weighting, robust, taper) points bracketing two adjacent curve
    winners.  Natural-weighting winners are treated as robust +2 briggs
    (numerically equivalent) so robust interpolation stays meaningful."""
    def rob(s):
        return 2.0 if s["weighting"] == "natural" else s["robust"]

    cands = set()
    r_mid = round((rob(a) + rob(b)) / 2, 2)
    tapers = sorted({a["taper"], b["taper"]})
    t_mid = round((tapers[0] * tapers[1]) ** 0.5, 3) if tapers[0] > 0 \
        else round(tapers[1] / 2, 3)
    cands.add(("briggs", r_mid, t_mid))
    for s in (a, b):
        r, t = rob(s), s["taper"]
        for dr in (-0.2, 0.2):
            if -2.0 <= r + dr <= 2.0:
                cands.add(("briggs", round(r + dr, 2), round(t, 3)))
        if t > 0:
            cands.add(("briggs", round(r, 2), round(t * 1.22, 3)))
            cands.add(("briggs", round(r, 2), round(t / 1.22, 3)))
    return cands


def refine(subarray, rounds=3, max_step=0.25, budget=60):
    sweep = Sweep(subarray)
    n_new_total = 0
    for rnd in range(1, rounds + 1):
        curve = build_curve(samples_from(sweep), SKIRT_MAX)
        jumps = [(a, b) for a, b in zip(curve, curve[1:])
                 if abs(b["eta"] - a["eta"]) > max_step
                 and b["res"] / a["res"] <= GAP_RATIO]
        if not jumps:
            print("round %d: no eta jumps > %.2g left -- done" % (rnd, max_step))
            break
        todo = set()
        for a, b in jumps:
            todo |= candidates_between(a, b)
        todo = [p for p in todo if point_key(*p) not in sweep.rows]
        todo = sorted(todo)[:budget - n_new_total]
        print("round %d: %d jumps, %d new points" % (rnd, len(jumps), len(todo)))
        if not todo:
            break
        for w, r, t in todo:
            sweep.run_point(w, r, t)
        n_new_total += len(todo)
        if n_new_total >= budget:
            print("refinement budget (%d points) reached" % budget)
            break
    curve = build_curve(samples_from(sweep), SKIRT_MAX)
    worst = max((abs(b["eta"] - a["eta"]) for a, b in zip(curve, curve[1:])
                 if b["res"] / a["res"] <= GAP_RATIO), default=0)
    print("%s refined: +%d points, curve %d pts, worst in-band step %.2f"
          % (subarray, n_new_total, len(curve), worst))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("subarray", choices=sorted(SUBARRAYS))
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--max-step", type=float, default=0.25)
    ap.add_argument("--budget", type=int, default=60)
    args = ap.parse_args()
    refine(args.subarray, rounds=args.rounds, max_step=args.max_step,
           budget=args.budget)

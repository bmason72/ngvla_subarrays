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

from config import SUBARRAYS, BEAM_CAP_ARCSEC
from sweep import Sweep, point_key
from make_report import build_curve
from sa_select.envelope import ETA_CAP

SKIRT_MAX = 0.10
GAP_RATIO = 1.35          # res jumps beyond this are infeasibility gaps
# For homogeneous subarrays, res jumps > GAP_RATIO are treated as genuine
# sculpt-infeasibility gaps (e.g. spiral+mid) and NOT refined.  For the
# heterogeneous ones (in BEAM_CAP_ARCSEC) the beam(taper) mapping crosses a
# sharp spike-to-plateau transition that can leave real resolution holes
# even where eta is smooth, so there res jumps ARE refinement targets
# (bounded by the same rounds/budget).


def samples_from(sweep):
    """ok + capped rows -> sample dicts with eta relative to the natural
    reference.  Capped rows are interpolation anchors (the offered curve is
    clipped at the beam cap via build_curve's max_res, matching collect.py /
    the report), so refine sees the same curve the report will show.

    The eta > ETA_CAP display trim matches make_report.main() EXACTLY: the
    report never draws that far-coarse fringe, so jumps there must not eat
    the refinement budget.  (15 Jul 2026: the first campaign round burned
    entire 60-point budgets smoothing invisible eta~5+ fringe jumps -- e.g.
    snapshot spiral "worst step 0.92" while its rendered curve was already
    smooth at 0.10.)"""
    nat = sweep.measured("natural", 2.0, 0.0)
    sigma_nat = float(nat["sigma_dirty"])
    out = []
    for row in sweep.rows.values():
        if row["status"] not in ("ok", "capped"):
            continue
        eta = float(row["sigma_dirty"]) / sigma_nat
        if eta > ETA_CAP:
            continue
        out.append(dict(
            res=float(row["res_geo_arcsec"]) * 1e3,
            eta=eta,
            skirt=float(row["skirt"]),
            weighting=row["weighting"],
            robust=float(row["robust"]),
            taper=float(row["taper_mas"]),
        ))
    return out


def curve_max_res_mas(subarray):
    """The beam cap in mas (build_curve max_res), or None if uncapped."""
    cap = BEAM_CAP_ARCSEC.get(subarray)
    return None if cap is None else cap * 1e3


def candidates_between(a, b):
    """New (weighting, robust, taper) points bracketing two adjacent curve
    winners.  Natural-weighting winners are treated as robust +2 briggs
    (numerically equivalent) so robust interpolation stays meaningful."""
    def rob(s):
        return 2.0 if s["weighting"] == "natural" else s["robust"]

    cands = set()
    r_mid = round((rob(a) + rob(b)) / 2, 2)
    tapers = sorted({a["taper"], b["taper"]})
    if len(tapers) == 1:
        # same taper (a robust-direction jump): bracket in robust only
        t_mid = tapers[0]
    elif tapers[0] > 0:
        t_mid = round((tapers[0] * tapers[1]) ** 0.5, 3)   # geometric mean
    else:
        t_mid = round(tapers[1] / 2, 3)                    # 0 -> first taper
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


# the two published curves; BOTH are refinement targets (15 Jul 2026 -- the
# first campaign round chased only the imaging curve, so point-source steps
# like RevF-snapshot main/main+long survived refinement untouched)
CURVE_SPECS = (("imaging", SKIRT_MAX), ("ptsrc", None))


def curve_jumps(curve, max_step, chase_res_jumps):
    return [(a, b) for a, b in zip(curve, curve[1:])
            if (abs(b["eta"] - a["eta"]) > max_step
                and b["res"] / a["res"] <= GAP_RATIO)
            or (chase_res_jumps and b["res"] / a["res"] > GAP_RATIO)]


def jump_severity(pair):
    """Ranking key: eta jumps by their size; coverage gaps by (ratio - 1),
    so a x2 resolution hole ranks with a 1.0-eta jump."""
    a, b = pair
    ratio = b["res"] / a["res"]
    if ratio > GAP_RATIO:
        return ratio - 1.0
    return abs(b["eta"] - a["eta"])


def pick_candidates(jumps, sweep, room):
    """Severity-ranked round-robin selection of new measurement points.

    A flat sorted-set truncation let one pathological jump's (alphabetically
    early) candidates crowd out every other jump when the per-round list
    exceeded the budget (codex review, 15 Jul 2026).  Instead: candidates are
    grouped per jump (deduped toward the most severe one that generated
    them), then taken one-per-jump in severity order until `room` is used."""
    jumps = sorted(jumps, key=jump_severity, reverse=True)
    assigned, cand_lists = set(), []
    for a, b in jumps:
        cands = []
        for p in sorted(candidates_between(a, b)):
            if p in assigned or point_key(*p) in sweep.rows:
                continue
            assigned.add(p)
            cands.append(p)
        if cands:
            cand_lists.append(cands)
    todo, depth = [], 0
    while len(todo) < room:
        added = False
        for cands in cand_lists:
            if depth < len(cands):
                todo.append(cands[depth])
                added = True
                if len(todo) >= room:
                    break
        if not added:
            break
        depth += 1
    return todo


def refine(subarray, rounds=3, max_step=0.25, budget=60):
    sweep = Sweep(subarray)
    chase_res_jumps = subarray in BEAM_CAP_ARCSEC
    n_new_total = 0
    max_res = curve_max_res_mas(subarray)
    for rnd in range(1, rounds + 1):
        samples = samples_from(sweep)
        jumps = []
        for _label, s_max in CURVE_SPECS:
            curve = build_curve(samples, s_max, max_res=max_res)
            jumps += curve_jumps(curve, max_step, chase_res_jumps)
        if not jumps:
            print("round %d: no eta jumps > %.2g left -- done" % (rnd, max_step))
            break
        todo = pick_candidates(jumps, sweep, budget - n_new_total)
        print("round %d: %d jumps, %d new points" % (rnd, len(jumps), len(todo)))
        if not todo:
            break
        for w, r, t in todo:
            sweep.run_point(w, r, t)
        n_new_total += len(todo)
        if n_new_total >= budget:
            print("refinement budget (%d points) reached" % budget)
            break
    samples = samples_from(sweep)
    for label, s_max in CURVE_SPECS:
        curve = build_curve(samples, s_max, max_res=max_res)
        worst = max((abs(b["eta"] - a["eta"]) for a, b in zip(curve, curve[1:])
                     if b["res"] / a["res"] <= GAP_RATIO), default=0)
        print("%s refined (%s): +%d points, curve %d pts, "
              "worst in-band step %.2f"
              % (subarray, label, n_new_total, len(curve), worst))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("subarray", choices=sorted(SUBARRAYS))
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--max-step", type=float, default=0.25)
    ap.add_argument("--budget", type=int, default=60)
    args = ap.parse_args()
    refine(args.subarray, rounds=args.rounds, max_step=args.max_step,
           budget=args.budget)

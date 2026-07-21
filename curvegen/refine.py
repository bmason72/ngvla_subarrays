"""
Targeted refinement of the two displayed curves (imaging: min eta vs
resolution subject to PSF skirt <= 0.10; point-source: min eta), by measuring
a handful of new (robust, taper) points wherever the discrete lattice makes
the curve jump, leave a resolution hole, or bump above its neighbours.

Why the lattice needs refining
------------------------------
The sweep quantizes robust (0.4 steps) and taper (log steps).  The true
optimum rides the skirt = 10% contour BETWEEN nodes, so at family crossings
the discrete curve jumps.  Refining only where a defect shows keeps the extra
imaging cost tiny (tens of points, not a lattice doubling), and it runs on top
of sweep.py's resumable results so refined points are permanent and re-runs are
free.

The escalation ladder (21 Jul 2026 upgrade)
-------------------------------------------
The original fixed candidate menu (`candidates_between`) smooths ordinary
node-to-node jumps, but a family of defects it cannot touch kept showing up as
"round N: X jumps, 0 new points" -- the menu was exhausted yet the jump
survived.  Those defects are now escalated:

  E1  secant resolution targeting -- one measured probe aimed at the
      log-midpoint resolution of a persisting jump, along the 1-D lattice slice
      (robust column or taper row) that actually connects the two winners.  The
      probe is placed at an EXISTING lattice coordinate on the fixed axis so it
      forms a row/column segment and is therefore visible in the curve (see the
      E0 note below).

  E2  staged dense taper scan -- the workhorse.  Between the fine and coarse
      rims of a defect it scans new taper levels in progressive log-midpoint
      order, measuring the SAME taper vector at BOTH endpoint robusts (so
      complete cells/columns form), then classifies the interval from the
      measured probes: a genuine resolution discontinuity, a locally supported
      high-penalty ridge, or honest under-sampling that keeps refining.

  E3  homogeneous gap chasing -- resolution holes (res ratio > GAP_RATIO) are
      now chased for every subarray; homogeneous subarrays get E2-only
      treatment (no fixed menu, no E1).

  E4  bumps -- a winner sitting above the chord joining its lower neighbours
      (branch alternation) gets one E1 attempt plus one staged E2 scan, capped
      at a quarter of the campaign budget.

E0 (verified 21 Jul 2026): the displayed curve is built at margin=0
(make_report.build_curve -> Envelope.curve), so a measured point is only
"seen" by the curve when it anchors a SEGMENT (two lattice-adjacent points in
a row or column) or a CELL (four corners).  An isolated singleton probe forms
no segment and never lands on the 0.01-dex grid, so it is invisible.  That is
why E1 fixes the non-varying axis to an existing lattice value and E2 measures
one taper vector at both robusts -- both guarantee the probes complete the
segments/cells the engine interpolates over.

Run (from curvegen/, CASA's python3):
  .../python3 refine.py core                     # default 3 rounds, step 0.25
  .../python3 refine.py spiral+mid --rounds 2
  .../python3 refine.py long --scan-points 12 --budget 120
"""

import argparse
import math
from collections import deque

from config import SUBARRAYS, BEAM_CAP_ARCSEC
from sweep import Sweep, point_key
from make_report import build_curve, sample_from_row
from sa_select.envelope import ETA_CAP

SKIRT_MAX = 0.10
GAP_RATIO = 1.35          # res jumps beyond this are resolution holes ("gaps")

# escalation tuning ---------------------------------------------------------- #
DEFAULT_MAX_STEP = 0.25       # eta jump size a refined curve should stay under
DEFAULT_SCAN_POINTS = 8       # K: taper levels an E2 scan may add per interval
DEFAULT_BUMP_MIN = 0.05       # floor of the eta-scaled bump trigger
RIM_DEX = 0.01                # a probe within this of a rim res is "on the rim"
MAX_PAIRS_PER_DEFECT = 4      # E2 taper pairs one defect may get per round
MAX_BUMPS_PER_CURVE = 2       # bump regions chased per curve per run
BUMP_BUDGET_FRACTION = 0.25   # bumps get at most this share of the budget

# the two published curves; BOTH are refinement targets (15 Jul 2026 -- the
# first campaign round chased only the imaging curve, so point-source steps
# survived refinement untouched)
CURVE_SPECS = (("imaging", SKIRT_MAX), ("ptsrc", None))


# --------------------------------------------------------------------------- #
# samples: the shared display-trim contract (see make_report.sample_from_row)

def samples_from(sweep):
    """ok + capped rows -> sample dicts with eta relative to the natural
    reference.  Capped rows are interpolation anchors (the offered curve is
    clipped at the beam cap via build_curve's max_res, matching collect.py /
    the report), so refine sees the same curve the report will show.

    The eta > ETA_CAP display trim and the capped-as-anchor rule are applied by
    make_report.sample_from_row -- the SAME implementation the report uses --
    so the refiner can never chase a jump the report has already trimmed away.
    (15 Jul 2026 incident: the two filters had drifted and a 60-point budget
    was burned smoothing an invisible eta ~5 fringe; they now share code.)"""
    nat = sweep.measured("natural", 2.0, 0.0)
    sigma_nat = float(nat["sigma_dirty"])
    out = []
    for row in sweep.rows.values():
        if row["status"] not in ("ok", "capped"):
            continue
        try:
            eta = float(row["sigma_dirty"]) / sigma_nat
        except (TypeError, ValueError):
            continue
        s = sample_from_row(
            res_mas=float(row["res_geo_arcsec"]) * 1e3,
            eta=eta,
            skirt=float(row["skirt"]),
            weighting=row["weighting"],
            robust=float(row["robust"]),
            taper_mas=float(row["taper_mas"]),
            capped=(row["status"] == "capped"))
        if s is not None:
            # refine feeds these to build_curve as envelope anchors; it does not
            # split display vs anchor (build_curve's max_res clips the offered
            # curve), so drop the display-only flag and keep the historical shape
            s.pop("capped", None)
            out.append(s)
    return out


def curve_max_res_mas(subarray):
    """The beam cap in mas (build_curve max_res), or None if uncapped."""
    cap = BEAM_CAP_ARCSEC.get(subarray)
    return None if cap is None else cap * 1e3


# --------------------------------------------------------------------------- #
# fixed candidate menu (heterogeneous in-band jumps and gaps).  Kept verbatim:
# tests/test_envelope.py::TestRefineCandidates imports candidates_between.

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


def pick_candidates(jumps, sweep, room):
    """Severity-ranked round-robin selection of fixed-menu points.

    Candidates are grouped per jump (deduped toward the most severe one that
    generated them), then taken one-per-jump in severity order until `room` is
    used -- so one pathological jump's candidates can never crowd out the rest
    (codex review, 15 Jul 2026)."""
    jumps = sorted(jumps, key=lambda ab: _pair_severity(ab), reverse=True)
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


def _pair_severity(pair):
    """Legacy ranking key for the fixed menu: eta jumps by size, gaps by
    (ratio - 1) so a x2 hole ranks with a 1.0-eta jump."""
    a, b = pair
    ratio = b["res"] / a["res"]
    if ratio > GAP_RATIO:
        return ratio - 1.0
    return abs(b["eta"] - a["eta"])


# --------------------------------------------------------------------------- #
# defect detection: jumps, gaps, ridges and bumps

def _untapered(taper):
    return taper is None or taper < 1e-6


def _chord_eta(left, right, res):
    """Eta of the straight line (in log10 res, eta) joining two curve points,
    evaluated at `res`."""
    x0, x1 = math.log10(left["res"]), math.log10(right["res"])
    if x1 == x0:
        return max(left["eta"], right["eta"])
    u = (math.log10(res) - x0) / (x1 - x0)
    return left["eta"] + u * (right["eta"] - left["eta"])


def _within_dex(res, ref, dex):
    return abs(math.log10(res / ref)) <= dex


def find_jumps_and_gaps(curve, label, max_step):
    """Adjacent-point defects on one curve: an in-band eta jump (|d_eta| >
    max_step, res ratio <= GAP_RATIO) or a resolution gap (res ratio >
    GAP_RATIO).  Up+down jump pairs bounding a single ridge are merged into one
    defect (they share one budget)."""
    raw = []
    for a, b in zip(curve, curve[1:]):
        ratio = b["res"] / a["res"]
        if ratio > GAP_RATIO:
            raw.append(dict(kind="gap", label=label, a=a, b=b))
        elif abs(b["eta"] - a["eta"]) > max_step:
            raw.append(dict(kind="jump", label=label, a=a, b=b))
    # merge an up-jump immediately followed by a down-jump (they share the
    # ridge point object) into one defect spanning both lower neighbours
    merged, i = [], 0
    while i < len(raw):
        d = raw[i]
        nxt = raw[i + 1] if i + 1 < len(raw) else None
        if (nxt is not None and d["kind"] == "jump" and nxt["kind"] == "jump"
                and d["b"] is nxt["a"]
                and d["b"]["eta"] > d["a"]["eta"]
                and nxt["b"]["eta"] < nxt["a"]["eta"]):
            merged.append(dict(kind="jump", label=label, a=d["a"],
                               b=nxt["b"], ridge=d["b"]))
            i += 2
        else:
            merged.append(d)
            i += 1
    return merged


def find_bumps(curve, label, bump_min_floor):
    """Bump regions: a run of curve points sitting above the straight line (in
    log10 res, eta) joining the nearest LOWER neighbours on each side (branch
    alternation), with peak excess above the eta-scaled trigger bump_min =
    max(bump_min_floor, 0.015 * eta_local).

    A branch-alternation bump is smooth at the 0.01-dex grid scale, so the
    region is found from a local eta MAXIMUM expanded down to its bounding local
    minima -- not from immediate grid neighbours, which barely differ."""
    bumps = []
    n = len(curve)
    i = 1
    while i < n - 1:
        peak = curve[i]
        if not (peak["eta"] > curve[i - 1]["eta"]
                and peak["eta"] >= curve[i + 1]["eta"]):
            i += 1
            continue
        # expand to the bounding local minima (walk downhill on each side)
        left = i
        while left > 0 and curve[left - 1]["eta"] <= curve[left]["eta"]:
            left -= 1
        right = i
        while right < n - 1 and curve[right + 1]["eta"] <= curve[right]["eta"]:
            right += 1
        lo_pt, hi_pt = curve[left], curve[right]
        excess = max(curve[j]["eta"] - _chord_eta(lo_pt, hi_pt, curve[j]["res"])
                     for j in range(left, right + 1))
        bmin = max(bump_min_floor, 0.015 * peak["eta"])
        if right > left and excess > bmin:
            bumps.append(dict(kind="bump", label=label, a=lo_pt, b=hi_pt,
                              peak=peak, excess=excess, bump_min=bmin))
        i = right + 1
    return bumps


def merge_bumps_across_curves(bumps):
    """Merge equivalent bump regions across the imaging/ptsrc curves: when two
    bumps' res intervals overlap (same feature seen on both curves), keep the
    more severe one so they share a single budget."""
    bumps = sorted(bumps, key=lambda d: d["excess"] / d["bump_min"],
                   reverse=True)
    kept = []
    for d in bumps:
        lo, hi = d["a"]["res"], d["b"]["res"]
        if any(not (hi < k["a"]["res"] or lo > k["b"]["res"]) for k in kept):
            continue                       # res interval overlaps a kept bump
        kept.append(d)
    return kept


def defect_severity(d, max_step):
    """Normalized severity for the global queue: jump |d_eta|/max_step, gap
    log(ratio)/log(GAP_RATIO), bump excess/bump_min.  Gaps and jumps are kept
    ahead of bumps at equal score by scheduling core defects first."""
    if d["kind"] == "gap":
        ratio = max(d["a"]["res"], d["b"]["res"]) / min(d["a"]["res"],
                                                        d["b"]["res"])
        return math.log(ratio) / math.log(GAP_RATIO)
    if d["kind"] == "bump":
        return d["excess"] / d["bump_min"]
    return abs(d["b"]["eta"] - d["a"]["eta"]) / max_step


# --------------------------------------------------------------------------- #
# E1: secant resolution targeting

def _slice_evidence(axis, fixed, samples):
    """Measured (param, res) evidence along one lattice slice: a robust column
    (fixed taper, vary robust) or a taper row (fixed robust, vary taper)."""
    out = []
    for s in samples:
        if s["weighting"] != "briggs" or s["robust"] is None:
            continue
        if axis == "robust" and round(s["taper"], 3) == fixed:
            out.append((round(s["robust"], 2), s["res"]))
        elif axis == "taper" and round(s["robust"], 2) == fixed and s["taper"] > 0:
            out.append((round(s["taper"], 3), s["res"]))
    return out


def secant_on_slice(axis, evidence, res_t, param_bracket):
    """Secant-interpolate the fixed-slice measured evidence to the parameter
    value that reaches resolution `res_t`.

    Interpolation matches the engine: robust is linear in log(res), taper is
    log-linear in log(res).  Rejects (returns None) when the evidence has
    duplicate resolutions, is non-monotone in param->res, does not bracket
    res_t, or when the proposed value falls outside the endpoint parameter
    bracket.  The returned value is rounded to point_key precision."""
    ev = sorted(evidence, key=lambda pr: pr[0])
    if len(ev) < 2:
        return None
    params = [p for p, _ in ev]
    ress = [r for _, r in ev]
    if len({round(r, 6) for r in ress}) != len(ress):
        return None                                  # duplicate resolutions
    diffs = [ress[k + 1] - ress[k] for k in range(len(ress) - 1)]
    if not (all(d > 0 for d in diffs) or all(d < 0 for d in diffs)):
        return None                                  # non-monotone param->res
    lo_p, hi_p = min(param_bracket), max(param_bracket)
    xt = math.log(res_t)
    for k in range(len(ev) - 1):
        r0, r1 = ress[k], ress[k + 1]
        if r0 == r1 or (r0 - res_t) * (r1 - res_t) > 0:
            continue                                 # res_t not in this pair
        u = (xt - math.log(r0)) / (math.log(r1) - math.log(r0))
        if axis == "robust":
            val = round(params[k] + u * (params[k + 1] - params[k]), 2)
        else:
            val = round(math.exp(math.log(params[k])
                                 + u * (math.log(params[k + 1])
                                        - math.log(params[k]))), 3)
        if not (lo_p <= val <= hi_p):
            return None                              # outside endpoint bracket
        return val
    return None


def secant_target(a, b, samples):
    """A single (weighting, robust, taper) probe aimed at the log-midpoint
    resolution of the jump (a, b), or None if the secant cannot be trusted (go
    to E2).  Skips cliffs (one endpoint tapered, the other not) and categorical
    weighting changes (natural vs briggs) -- "natural = robust 2.0" is a
    proposal convention, not valid interpolation."""
    if _untapered(a["taper"]) != _untapered(b["taper"]):
        return None                                  # taper-onset cliff
    if a["weighting"] != b["weighting"] or a["weighting"] == "natural":
        return None
    res_t = math.sqrt(a["res"] * b["res"])           # log10 midpoint
    rob_a, rob_b = round(a["robust"], 2), round(b["robust"], 2)
    tap_a, tap_b = round(a["taper"], 3), round(b["taper"], 3)
    attempts = []
    if tap_a == tap_b and rob_a != rob_b:            # a robust-direction jump
        attempts.append(("robust", tap_a, (rob_a, rob_b)))
    if rob_a == rob_b and tap_a != tap_b:            # a taper-direction jump
        attempts.append(("taper", rob_a, (tap_a, tap_b)))
    if not attempts and rob_a != rob_b and tap_a != tap_b:
        # both axes differ: try each fixed slice, keep the first that brackets
        attempts = [("robust", tap_a, (rob_a, rob_b)),
                    ("robust", tap_b, (rob_a, rob_b)),
                    ("taper", rob_a, (tap_a, tap_b)),
                    ("taper", rob_b, (tap_a, tap_b))]
    for axis, fixed, bracket in attempts:
        val = secant_on_slice(axis, _slice_evidence(axis, fixed, samples),
                              res_t, bracket)
        if val is None:
            continue
        return ("briggs", val, fixed) if axis == "robust" \
            else ("briggs", fixed, val)
    return None


# --------------------------------------------------------------------------- #
# E2: staged dense taper scan

def progressive_log_midpoints(lo, hi, k, exclude=()):
    """Up to `k` unique taper levels strictly inside (lo, hi), in progressive
    log-midpoint (breadth-first bisection) order: the bracket midpoint first,
    then the midpoints of the two sub-brackets, and so on.  Each is rounded to
    point_key precision (3 dp) FIRST, then deduped against `exclude` and within
    the list, so re-runs are deterministic and already-measured levels are
    skipped."""
    if not (lo > 0 and hi > lo):
        return []
    xlo, xhi = math.log10(lo), math.log10(hi)
    seen = {round(float(t), 3) for t in exclude}
    out, queue, guard = [], deque([(xlo, xhi)]), 0
    while queue and len(out) < k and guard < 4000:
        guard += 1
        alo, ahi = queue.popleft()
        mid = 0.5 * (alo + ahi)
        t = round(10 ** mid, 3)
        if t not in seen and lo < t < hi:
            seen.add(t)
            out.append(t)
        if ahi - alo > 1e-6:                          # keep subdividing
            queue.append((alo, mid))
            queue.append((mid, ahi))
    return out


def _trace_of(point):
    """The lattice trace (weighting, robust) a curve winner rides."""
    if point["weighting"] == "natural":
        return ("natural", 2.0)
    return ("briggs", round(point["robust"], 2))


def _scan_bracket(defect):
    """(t_lo, t_hi, traces, fine, coarse) for an E2 scan, or None if no taper
    bracket exists.  t_hi = t_bite (the smallest taper that reaches the coarse
    rim); t_lo = the fine rim's taper, or t_bite/32 when the fine endpoint is
    untapered (no fine-rim taper evidence)."""
    a, b = defect["a"], defect["b"]
    fine, coarse = (a, b) if a["res"] <= b["res"] else (b, a)
    t_bite = coarse["taper"] or 0.0
    if t_bite <= 0:
        return None                                  # coarse rim untapered
    t_nobite = fine["taper"] if fine["taper"] and fine["taper"] > 0 \
        else t_bite / 32.0
    lo, hi = min(t_nobite, t_bite), max(t_nobite, t_bite)
    if not (hi > lo):
        return None
    traces = []
    for pt in (fine, coarse):
        tr = _trace_of(pt)
        if tr not in traces:
            traces.append(tr)
    return lo, hi, traces, fine, coarse


def _measured_row(sweep, trace, taper):
    row = sweep.rows.get(point_key(trace[0], trace[1], taper))
    if row and row["status"] in ("ok", "capped"):
        return row
    return None


def _skirt_max_for(label):
    """The imaging skirt setpoint for a defect on the imaging curve, else None
    (the point-source curve draws every skirt)."""
    return SKIRT_MAX if label == "imaging" else None


def _classify_scan(sweep, traces, levels, fine, coarse, skirt_max):
    """Classify a completed E2 stage from the measured probes (recomputed from
    rows, never stored):

      'confirmed'    -- no display-eligible interior resolution exists at this
                        scan density: a sampled resolution discontinuity;
      'high_penalty' -- eligible probes land interior but none dips below the
                        chord joining the rims (a locally supported high-penalty
                        ridge);
      'undersampled' -- an interior probe dips below the chord: keep refining.

    A probe counts as EVIDENCE only if the report would draw it: each row is put
    through the shared display-trim contract (make_report.sample_from_row, which
    drops eta > ETA_CAP and NaN eta) and, on the IMAGING curve, must also meet
    skirt <= skirt_max.  Stage completion is measured separately (from row
    existence), so an ineligible measurement still advances the scan but never
    terminally classifies the interval on evidence the curve does not contain."""
    sigma_nat = float(sweep.measured("natural", 2.0, 0.0)["sigma_dirty"])
    res_fine, res_coarse = fine["res"], coarse["res"]
    interior = []
    for tr in traces:
        for t in levels:
            row = _measured_row(sweep, tr, t)
            if row is None:
                continue
            try:
                eta = float(row["sigma_dirty"]) / sigma_nat
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            skirt = (float(row["skirt"]) if row.get("skirt") not in ("", None)
                     else None)
            s = sample_from_row(
                res_mas=float(row["res_geo_arcsec"]) * 1e3, eta=eta, skirt=skirt,
                weighting=tr[0], robust=(None if tr[0] == "natural" else tr[1]),
                taper_mas=t, capped=(row["status"] == "capped"))
            if s is None:
                continue                             # eta > ETA_CAP or NaN: not drawn
            if skirt_max is not None and (s["skirt"] is None
                                          or s["skirt"] > skirt_max):
                continue                             # imaging curve wouldn't draw it
            res = s["res"]
            if _within_dex(res, res_fine, RIM_DEX) \
                    or _within_dex(res, res_coarse, RIM_DEX):
                continue                             # on a rim
            if res_fine < res < res_coarse:
                interior.append((res, s["eta"]))
    if not interior:
        return "confirmed"                           # no eligible interior probe
    if any(eta < _chord_eta(fine, coarse, res) - 1e-9 for res, eta in interior):
        return "undersampled"
    return "high_penalty"


def e2_pairs_for_defect(defect, sweep, K, stage_size, ctx):
    """The E2 taper PAIRS (one taper level x both traces) to measure for one
    defect this round, or [] if the interval is classified/exhausted.

    Stateless across rounds and restarts: the stage is derived from how many of
    the deterministic progressive levels are already measured, and the
    interval is classified straight from the measured rows -- no state file."""
    bracket = _scan_bracket(defect)
    if bracket is None:
        return []
    t_lo, t_hi, traces, fine, coarse = bracket
    skirt_max = _skirt_max_for(defect["label"])
    # STABLE deterministic level set (not excluding earlier refinement points):
    # staging counts how many of these fixed K levels are already measured, so
    # round 1 fills stage 1 (first stage_size) and round 2 fills stage 2.
    levels = progressive_log_midpoints(t_lo, t_hi, K)
    if not levels:
        # no interior taper exists at this density -> a sampled discontinuity
        _record_classification(defect, "confirmed", fine, coarse, ctx)
        return []

    def fully_measured(t):
        # a level is "sampled" (stage completion) once every trace has a
        # measured row, regardless of whether the report would draw it
        return all(_measured_row(sweep, tr, t) is not None for tr in traces)

    done = [t for t in levels if fully_measured(t)]
    pending = [t for t in levels if not fully_measured(t)]
    # classify after each COMPLETED stage (stage 1 done, or all K measured)
    if len(done) >= stage_size or not pending:
        cls = _classify_scan(sweep, traces, done, fine, coarse, skirt_max)
        if cls in ("confirmed", "high_penalty"):
            _record_classification(defect, cls, fine, coarse, ctx)
            return []
    if not pending:
        return []                    # both stages measured, under-sampled: cap

    todo = pending[:stage_size]
    pairs = []
    for t in todo:
        pts = [(tr[0], tr[1], t) for tr in traces
               if _measured_row(sweep, tr, t) is None]
        if pts:
            pairs.append(pts)
    if pairs:
        print("  E2 plan %s [%s] res %.4g->%.4g mas  traces %s  tapers %s"
              % (ctx["subarray"], defect["label"], fine["res"], coarse["res"],
                 [t[1] for t in traces], [p[0][2] for p in pairs]), flush=True)
    return pairs


def _record_classification(defect, kind, fine, coarse, ctx):
    """Log a terminal classification once per interval per run and tally it."""
    sig = (defect["label"], round(fine["res"], 4), round(coarse["res"], 4), kind)
    if sig in ctx["logged"]:
        return
    ctx["logged"].add(sig)
    if kind == "confirmed":
        ctx["counts"]["confirmed"] += 1
        print("  E2 %s [%s]: sampled resolution discontinuity: no "
              "display-eligible interior resolution at this scan density "
              "(res %.4g -> %.4g mas)"
              % (ctx["subarray"], defect["label"], fine["res"], coarse["res"]),
              flush=True)
    elif kind == "high_penalty":
        ctx["counts"]["high_penalty"] += 1
        print("  E2 %s [%s]: locally supported high-penalty interval "
              "(res %.4g -> %.4g mas)"
              % (ctx["subarray"], defect["label"], fine["res"], coarse["res"]),
              flush=True)


# --------------------------------------------------------------------------- #
# per-round planning

class _Plan:
    __slots__ = ("points", "n_defects", "bump_points")

    def __init__(self, points, n_defects, bump_points):
        self.points = points
        self.n_defects = n_defects
        self.bump_points = bump_points


def plan_round(sweep, samples, curves, homogeneous, max_step, scan_points,
               bump_min_floor, room, bump_room, ctx):
    """Decide the new points to measure this round.

    Order of work: fixed menu (heterogeneous jumps/gaps whose menu is not
    exhausted), then E1 secant probes, then breadth-first E2 taper pairs, then
    E4 bumps -- so gaps and jumps are always served before bumps."""
    K = scan_points
    stage_size = max(1, K // 2)

    core, bumps = [], []
    for label, curve in curves.items():
        core += find_jumps_and_gaps(curve, label, max_step)
        bumps += find_bumps(curve, label, bump_min_floor)
    bumps = merge_bumps_across_curves(bumps)
    # keep at most the 2 most severe bump regions per curve
    per_curve, capped_bumps = {}, []
    for d in sorted(bumps, key=lambda d: defect_severity(d, max_step),
                    reverse=True):
        n = per_curve.get(d["label"], 0)
        if n < MAX_BUMPS_PER_CURVE:
            per_curve[d["label"]] = n + 1
            capped_bumps.append(d)
    bumps = capped_bumps
    core.sort(key=lambda d: defect_severity(d, max_step), reverse=True)

    points, used = [], set()

    def take(pt):
        k = point_key(*pt)
        if k in used or k in sweep.rows or len(points) >= room:
            return False
        used.add(k)
        points.append(pt)
        return True

    def take_group(group, allowance=None):
        """Admit a whole taper PAIR atomically or not at all -- never one trace
        without its mate, which would leave a half-cell the envelope cannot see
        (E0 rule).  A one-member group (its mate already measured) is valid.
        `allowance` further caps the group against the remaining bump budget."""
        members = [pt for pt in group if point_key(*pt) not in used
                   and point_key(*pt) not in sweep.rows]
        if not members or len(points) + len(members) > room:
            return 0
        if allowance is not None and len(members) > allowance:
            return 0
        for pt in members:
            used.add(point_key(*pt))
            points.append(pt)
        return len(members)

    # 1. split core defects into fixed-menu vs escalation.  Homogeneous
    # subarrays go straight to E2 taper scans (their gaps/jumps live at taper
    # transitions and the fixed menu just burns budget) -- EXCEPT an untapered
    # robust-direction defect, where E2 has no taper bracket and E1 does not
    # apply, so the fixed menu (midpoint robust etc.) is the only lever left.
    fixed_defects, escal_defects = [], []
    for d in core:
        if homogeneous and _scan_bracket(d) is not None:
            escal_defects.append(d)
            continue
        fixed = [p for p in candidates_between(d["a"], d["b"])
                 if point_key(*p) not in sweep.rows]
        (fixed_defects if fixed else escal_defects).append(d)

    # 2. fixed-menu points (existing round-robin)
    if fixed_defects and len(points) < room:
        for pt in pick_candidates([(d["a"], d["b"]) for d in fixed_defects],
                                  sweep, room - len(points)):
            take(pt)

    # 3. escalation: one E1 probe per interval (heterogeneous only), else E2
    e2_lists = []
    for d in escal_defects:
        if len(points) >= room:
            break
        if not homogeneous:
            key = secant_target(d["a"], d["b"], samples)
            if key is not None and point_key(*key) not in sweep.rows:
                if take(key):
                    ctx["counts"]["e1"] += 1
                    continue                          # E1 uses this defect's turn
        pairs = e2_pairs_for_defect(d, sweep, K, stage_size, ctx)
        if pairs:
            e2_lists.append(pairs)

    # 4. breadth-first E2: one pair per defect before any second, up to 4 pairs.
    # A pair is admitted atomically (both traces or neither) so a single
    # remaining budget slot never buys half a cell.
    for depth in range(MAX_PAIRS_PER_DEFECT):
        progressed = False
        for pairs in e2_lists:
            if depth < len(pairs) and len(points) < room:
                added = take_group(pairs[depth])
                if added:
                    ctx["counts"]["e2_pts"] += added
                    progressed = True
        if not progressed:
            break
    if e2_lists:
        ctx["counts"]["e2_scans"] += len(e2_lists)

    # 5. E4 bumps: one E1 attempt + one staged E2 scan each, within bump_room
    bump_used = 0
    for d in bumps:
        if len(points) >= room or bump_used >= bump_room:
            break
        before = len(points)
        key = secant_target(d["a"], d["b"], samples)
        if key is not None and point_key(*key) not in sweep.rows and take(key):
            bump_used += len(points) - before
            ctx["counts"]["bumps"] += 1
            continue
        pairs = e2_pairs_for_defect(d, sweep, K, stage_size, ctx)
        added = 0
        for pair in pairs[:MAX_PAIRS_PER_DEFECT]:
            if len(points) >= room or bump_used >= bump_room:
                break
            # atomic pair, also bounded by the remaining bump allowance
            got = take_group(pair, allowance=bump_room - bump_used)
            added += got
            bump_used += got
        if added:                        # bump worked via an E2 taper scan
            ctx["counts"]["e2_scans"] += 1
            ctx["counts"]["e2_pts"] += added
        if len(points) - before:
            ctx["counts"]["bumps"] += 1

    return _Plan(points, len(core) + len(bumps), bump_used)


# --------------------------------------------------------------------------- #
# the driver

def refine(subarray, rounds=3, max_step=DEFAULT_MAX_STEP, budget=60,
           scan_points=DEFAULT_SCAN_POINTS, bump_min=DEFAULT_BUMP_MIN,
           sweep=None):
    """Refine both published curves for one subarray by escalating whichever
    defects survive the fixed menu.  `sweep` may be injected (tests use an
    analytic FakeSweep); by default a real resumable Sweep is opened."""
    if sweep is None:
        sweep = Sweep(subarray)
    homogeneous = subarray not in BEAM_CAP_ARCSEC
    max_res = curve_max_res_mas(subarray)
    bump_room = int(round(BUMP_BUDGET_FRACTION * budget))
    counts = dict(e1=0, e2_scans=0, e2_pts=0, bumps=0,
                  confirmed=0, high_penalty=0)
    ctx = dict(subarray=subarray, counts=counts, logged=set())
    n_new, bumps_used = 0, 0

    for rnd in range(1, rounds + 1):
        room = budget - n_new
        if room <= 0:
            break
        samples = samples_from(sweep)
        curves = {label: build_curve(samples, s_max, max_res=max_res)
                  for label, s_max in CURVE_SPECS}
        plan = plan_round(sweep, samples, curves, homogeneous, max_step,
                          scan_points, bump_min, room,
                          max(0, bump_room - bumps_used), ctx)
        print("round %d: %d defects, %d new points"
              % (rnd, plan.n_defects, len(plan.points)), flush=True)
        if not plan.points:
            break
        for w, r, t in plan.points:
            sweep.run_point(w, r, t)
        n_new += len(plan.points)
        bumps_used += plan.bump_points
        if n_new >= budget:
            print("refinement budget (%d points) reached" % budget, flush=True)
            break

    samples = samples_from(sweep)
    for label, s_max in CURVE_SPECS:
        curve = build_curve(samples, s_max, max_res=max_res)
        worst = max((abs(b["eta"] - a["eta"]) for a, b in zip(curve, curve[1:])
                     if b["res"] / a["res"] <= GAP_RATIO), default=0)
        print("%s refined (%s): +%d points, curve %d pts, "
              "worst in-band step %.2f"
              % (subarray, label, n_new, len(curve), worst))
    print("%s escalation: E1 %d, E2-scans %d (%d pts), bumps %d, "
          "confirmed-discontinuities %d, high-penalty %d"
          % (subarray, counts["e1"], counts["e2_scans"], counts["e2_pts"],
             counts["bumps"], counts["confirmed"], counts["high_penalty"]))
    return counts


def _positive_int(text):
    v = int(text)
    if v <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return v


def _scan_points(text):
    """--scan-points: a positive K, capped at 64.  0 would make every E2 scan
    classify 'confirmed' without measuring anything, so it is rejected here."""
    v = _positive_int(text)
    if v > 64:
        raise argparse.ArgumentTypeError("must be <= 64")
    return v


def _positive_float(text):
    v = float(text)
    if not v > 0:                     # also rejects NaN
        raise argparse.ArgumentTypeError("must be > 0")
    return v


def _nonneg_float(text):
    v = float(text)
    if not v >= 0:                    # also rejects NaN
        raise argparse.ArgumentTypeError("must be >= 0")
    return v


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("subarray", choices=sorted(SUBARRAYS))
    ap.add_argument("--rounds", type=_positive_int, default=3)
    ap.add_argument("--max-step", type=_positive_float, default=DEFAULT_MAX_STEP,
                    help="eta jump the refined curve should stay under (> 0; "
                         "severity divides by it)")
    ap.add_argument("--budget", type=_positive_int, default=60)
    ap.add_argument("--scan-points", type=_scan_points,
                    default=DEFAULT_SCAN_POINTS,
                    help="K: taper levels an E2 scan may add per interval "
                         "(1..64)")
    ap.add_argument("--bump-min", type=_nonneg_float, default=DEFAULT_BUMP_MIN,
                    help="floor of the eta-scaled bump trigger (>= 0)")
    args = ap.parse_args()
    refine(args.subarray, rounds=args.rounds, max_step=args.max_step,
           budget=args.budget, scan_points=args.scan_points,
           bump_min=args.bump_min)

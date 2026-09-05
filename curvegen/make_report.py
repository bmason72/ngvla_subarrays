"""
Build the HTML curve-inspection report from the current sweep results.

Reads the (rev, sim_mode) combination's curve + subarray CSVs (routed through
sa_select/data/config_registry.csv) and injects the data as JSON into
report_template.html.  The output is a self-contained page (no external
resources) suitable for opening directly in a browser.

The DEFAULT invocation is (revF, track) and is byte-for-byte identical to the
original: it reads revf_curves.csv + subarrays.csv and RESULTS_DIR = results/.
A campaign for another combination sets NGVLA_REV / NGVLA_SIM_MODE in the
environment (so config.RESULTS_DIR points at that combo's results dir) and,
optionally, passes matching --rev / --sim-mode:

  Run:  .../python3 make_report.py [output.html]
        NGVLA_REV=revD NGVLA_SIM_MODE=track .../python3 make_report.py \\
            --rev revD --sim-mode track            # -> revd-track-curves.html
"""

import argparse
import base64
import csv
import gzip
import json
import math
import os
import re
import sys

import numpy as np

from config import (REPO, RESULTS_DIR, ROBUST_LIST, BEAM_CAP_ARCSEC, grid_rows,
                    REV, SIM_MODE, BAND, MFS, REF_FREQ_GHZ, FREQ_LO_GHZ,
                    FREQ_HI_GHZ, CURVE_TYPES, PROFILE_DIR)

sys.path.insert(0, REPO)                    # for the shared curve engine
from sa_select.envelope import Envelope, ETA_CAP   # noqa: E402

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "report_template.html")

# fixed series order & display names (color slots assigned in the template)
ORDER = ["core", "spiral", "mid", "core+spiral", "spiral+mid",
         "main", "core-inner",
         # memo-121 long-baseline + outer-core campaign (added 7 Jul 2026)
         "long", "mid+long", "spiral+mid+long", "main+long",
         "spiral+core-outer", "mid+spiral+core-outer",
         "long+mid+spiral+core-outer"]   # core+mid measured but dropped


GRID_DEX = 0.01      # target-resolution grid spacing of the plotted curves
MARK_EVERY = 8       # cadence of tooltip markers along smooth curve runs
SKIRT_SETPOINTS = [0.05, 0.10, 0.15, 0.20]
SKIRT_DEFAULT = 0.10
SKIRT_DEFAULT_KEY = "%.2f" % SKIRT_DEFAULT

DATA_DIR = os.path.join(REPO, "sa_select", "data")

# Release build (--combined --release; RELEASE_PLAN.md T3, WRAPUP.md items
# 2+3): the public page carries ONLY these campaigns, and the ones released
# point-source only advertise it via imaging_omitted=True in their combo
# metadata (the page then blanks the imaging-curves card and pins the
# calculator to point-source for that campaign).
RELEASE_COMBOS = ["revF_track", "revD_track", "revC_track"]
RELEASE_PTSRC_ONLY = {"revD_track", "revC_track"}

# Data routing.  These module globals default to (revF, track) so the plain
# `make_report.py out.html` call is byte-identical to the original; __main__
# re-points them for a different registered (rev, sim_mode).  ACTIVE_ORDER is
# ORDER filtered to the combo's offered subarrays (identical to ORDER for the
# default, since subarrays.csv holds exactly those 14).
CURVES_CSV = os.path.join(DATA_DIR, "revf_curves.csv")
SUBARRAYS_CSV = os.path.join(DATA_DIR, "subarrays.csv")
ACTIVE_ORDER = ORDER


def registry_paths(rev, sim_mode, band=""):
    """(subarrays_csv, samples_csv) absolute paths for (rev, mode, band) from
    config_registry.csv; SystemExit with guidance if the combo is absent."""
    reg = os.path.join(DATA_DIR, "config_registry.csv")
    with open(reg, newline="") as f:
        for r in csv.DictReader(f):
            if (r["rev"].strip() == rev and r["sim_mode"].strip() == sim_mode
                    and (r.get("band") or "").strip().lower() == band):
                return (os.path.join(DATA_DIR, r["subarrays_csv"].strip()),
                        os.path.join(DATA_DIR, r["samples_csv"].strip()))
    raise SystemExit("make_report.py: no config_registry.csv row for "
                     "(rev=%r, sim_mode=%r, band=%r)"
                     % (rev, sim_mode, band))


def offered_order(subarrays_csv):
    """ORDER restricted to the subarrays this combo actually offers, in ORDER's
    display order (so color slots and layout are reused)."""
    with open(subarrays_csv, newline="") as f:
        offered = {r["name"].strip() for r in csv.DictReader(f)}
    return [n for n in ORDER if n in offered]


def build_curve(samples, skirt_max=None, max_res=None, leaves=None):
    """The curve as the shared engine computes it: at each target resolution
    on a fine log grid, the cheapest interpolated-family operating point at
    EXACTLY that resolution (see sa_select/envelope.py; this replaced the
    sliding-window sample min after the 6 Jul 2026 anomaly post-mortem).

    Angular resolution is the primary requirement: where nothing under the
    skirt threshold exists at some resolution, the criterion is RELAXED to
    the best achievable skirt there (memo 121's 'partial' cases) and the
    point is flagged relaxed=True.  Real coverage gaps stay gaps.

    Each point carries: the interpolated (weighting, robust, taper), its
    measured anchor keys (env_keys, for the lattice heatmaps), and a marker
    flag (tooltip markers at family changes and every MARK_EVERY points).
    """
    curve = []
    prev_key, run = None, 0
    for c in Envelope(samples, leaves=leaves).curve(
            skirt_max=skirt_max, grid_dex=GRID_DEX, max_res=max_res):
        # family level only: on the robust branch c.robust (and the anchor
        # set, near refined minima) drifts continuously, which would reset
        # the run — and mark a tooltip point — at every grid point
        key = (c.weighting, c.relaxed, c.traded)
        run = run + 1 if key == prev_key else 0
        curve.append(dict(
            res=c.res, eta=c.eta, skirt=c.skirt, weighting=c.weighting,
            robust=c.robust, taper=c.taper, relaxed=c.relaxed,
            traded=c.traded,
            marker=(run % MARK_EVERY == 0),
            env_keys=[(a.weighting, a.robust, a.taper) for a in c.anchors],
        ))
        prev_key = key
    return curve


def sample_from_row(res_mas, eta, skirt, weighting, robust, taper_mas, capped):
    """The shared display-trim + interpolation-anchor contract, applied to one
    already-parsed lattice measurement.  Returns a sample dict (with a `capped`
    flag) or None when the display trim rejects the row.

    ONE implementation for BOTH the report (build_payload) and the refiner
    (curvegen/refine.samples_from): a 15 Jul 2026 incident traced a wasted
    refinement budget to those two filters drifting apart, so they now share
    this code.  The trim: the eta > ETA_CAP regime (>~25x natural observing
    time) is never plotted, and a NaN eta (a degenerate measurement) is
    dropped.  capped rows are interpolation ANCHORS -- they feed the envelope
    (extending row coverage up to the beam cap) but are never DISPLAYED as
    dots, so callers building a display set check the returned `capped` flag.
    """
    if eta is None or not (eta <= ETA_CAP):        # trims eta > cap AND NaN eta
        return None
    return dict(res=res_mas, eta=eta, skirt=skirt, weighting=weighting,
                robust=robust, taper=taper_mas, capped=bool(capped))


# ---------------------------------------------------------------------------
# Display-only curve smoothing (astronomer request, 21 Jul 2026).
#
# The report draws each curve through a DENSE 0.01-dex grid straight from the
# envelope engine (build_curve above), and the connecting line shows small
# (0.01-0.09 in eta) non-monotonic wiggle -- grid-scale numerical noise in the
# underlying PSF measurements, not real structure.  Real defects (bigger
# steps, genuine coverage gaps) are being fixed in the DATA by a separate
# refinement upgrade; this section must never do that job instead -- it only
# produces a parallel "smooth" eta array, aligned 1:1 with a curve's raw
# points, that report_template.html draws for the CONNECTING LINE only.
# Markers/tooltips/dots and the gap-break rule keep reading the raw points
# untouched (see curveChart in the template).
#
# The smoother is bounded so it can polish sub-threshold wiggle but can never
# mask real structure: it never bridges a genuine gap or step, it always
# keeps material local extrema, and it is iteratively tightened (inserting
# more knots) until it tracks the raw curve within SMOOTH_MAX_ABS everywhere,
# and within the tighter SMOOTH_MAX_OPTIMISTIC wherever it would UNDERSTATE
# the true cost (eta) -- reporting a rosier sensitivity than reality is the
# worse failure mode for an observing-time estimate, so that direction gets
# the tighter leash.  No scipy (project constraint): a small pure-numpy
# monotone (Fritsch-Carlson / PCHIP) cubic does the fitting.
# ---------------------------------------------------------------------------

SMOOTH_GAP_RATIO = 1.055            # matches report_template.html's drawn-gap rule
SMOOTH_STEP_ETA = 0.20              # a real step/cliff -- never bridged by a spline
SMOOTH_RDP_EPS = 0.03                # initial knot-selection vertical-error tolerance
SMOOTH_EXTREMUM_PROMINENCE = 0.05    # local extrema this material are always kept
SMOOTH_MAX_ABS = 0.03                # final bound: max|smooth - raw|, either direction
SMOOTH_MAX_OPTIMISTIC = 0.02         # tighter bound where smooth UNDERSTATES raw (eta too low)
SMOOTH_WARN_ABS = 0.06               # build-time warning threshold (should be unreachable)
SMOOTH_MIN_SEGMENT = 4               # shorter segments are passed through raw, untouched


def _segment_breaks(res, eta):
    """Index boundaries splitting one curve into segments the smoother may
    fit independently: a break at (a) a resolution gap the template already
    draws as a break (ratio > SMOOTH_GAP_RATIO) or (b) a genuine step
    (|adjacent eta jump| > SMOOTH_STEP_ETA) -- a real cliff must stay a sharp
    corner, never a soft curve, even where the template still draws a
    connecting line across it (that only breaks on rule (a)).  Returns a list
    of (start, end) inclusive index pairs covering the whole curve."""
    n = len(res)
    segments, start = [], 0
    for i in range(1, n):
        gap = res[i] > res[i - 1] * SMOOTH_GAP_RATIO
        step = abs(eta[i] - eta[i - 1]) > SMOOTH_STEP_ETA
        if gap or step:
            segments.append((start, i - 1))
            start = i
    segments.append((start, n - 1))
    return segments


def _pchip_slopes(x, y):
    """Fritsch-Carlson derivative estimate at each knot (x strictly
    increasing) -- the classic shape-preserving PCHIP recipe (MATLAB's
    `pchip`, scipy's PchipInterpolator): zero derivative at a knot that is a
    local extremum of the DATA (so the cubic cannot overshoot it), else a
    weighted harmonic mean of the two neighboring secant slopes, with a
    shape-corrected one-sided estimate at each end.  Guarantees a monotone
    interpolant on monotone data and no overshoot between any two knots."""
    m = len(x)
    if m == 2:
        return np.full(2, (y[1] - y[0]) / (x[1] - x[0]))
    h = np.diff(x)
    with np.errstate(divide="ignore", invalid="ignore"):
        delta = np.diff(y) / h                    # secant slopes, length m-1
    d = np.zeros(m)
    sign_change = (delta[:-1] * delta[1:]) <= 0
    w1 = 2 * h[1:] + h[:-1]
    w2 = h[1:] + 2 * h[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        harmonic = (w1 + w2) / (w1 / delta[:-1] + w2 / delta[1:])
    d[1:-1] = np.where(sign_change, 0.0, harmonic)

    def edge(h0, h1, d0, d1):
        slope = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
        if slope * d0 < 0:
            slope = 0.0
        elif (d0 * d1 < 0) and (abs(slope) > 3 * abs(d0)):
            slope = 3 * d0
        return slope

    d[0] = edge(h[0], h[1], delta[0], delta[1])
    d[-1] = edge(h[-1], h[-2], delta[-1], delta[-2])
    return d


def _pchip_eval(xk, yk, dk, x):
    """Evaluate the cubic Hermite spline through knots (xk, yk, dk) at every
    point in x (each must lie in [xk[0], xk[-1]]); vectorized over x via
    np.searchsorted to bucket each point into its knot interval.  Exact at
    the knots themselves (t=0 or 1 reduces the Hermite basis to yk)."""
    idx = np.clip(np.searchsorted(xk, x, side="right") - 1, 0, len(xk) - 2)
    x0, x1 = xk[idx], xk[idx + 1]
    y0, y1 = yk[idx], yk[idx + 1]
    d0, d1 = dk[idx], dk[idx + 1]
    h = x1 - x0
    t = (x - x0) / h
    t2, t3 = t * t, t * t * t
    h00, h10 = 2 * t3 - 3 * t2 + 1, t3 - 2 * t2 + t
    h01, h11 = -2 * t3 + 3 * t2, t3 - t2
    return h00 * y0 + h10 * h * d0 + h01 * y1 + h11 * h * d1


def _initial_knots(x, y):
    """Boolean keep-mask over one segment's points: RDP simplification with a
    VERTICAL error metric (the natural one for a single-valued curve y(x),
    rather than RDP's usual perpendicular distance) down to SMOOTH_RDP_EPS,
    plus -- regardless of what that simplification kept -- any local
    extremum whose prominence against the segment's own chord exceeds
    SMOOTH_EXTREMUM_PROMINENCE.  That second rule is not just a looser
    version of the first: a real bump can sit close to a *coarse* fit by
    curvature accident without being anchored to its measured (x, y) at all,
    which would blur or shift it; forcing it in as a knot keeps it exact and
    exactly where it was measured (real structure is refine's job to remove
    from the data, never the display smoother's)."""
    n = len(x)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True

    def rdp(lo, hi):
        if hi <= lo + 1:
            return
        chord = y[lo] + (y[hi] - y[lo]) * (x[lo:hi + 1] - x[lo]) / (x[hi] - x[lo])
        dist = np.abs(y[lo:hi + 1] - chord)
        dist[0] = dist[-1] = -1.0            # endpoints already kept
        j_local = int(np.argmax(dist))
        if dist[j_local] > SMOOTH_RDP_EPS:
            j = lo + j_local
            keep[j] = True
            rdp(lo, j)
            rdp(j, hi)

    rdp(0, n - 1)

    if x[-1] > x[0]:
        chord_full = y[0] + (y[-1] - y[0]) * (x - x[0]) / (x[-1] - x[0])
        is_extremum = np.zeros(n, dtype=bool)
        is_extremum[1:-1] = ((y[1:-1] - y[:-2]) * (y[2:] - y[1:-1])) <= 0
        prominent = is_extremum & (np.abs(y - chord_full) >
                                    SMOOTH_EXTREMUM_PROMINENCE)
        keep |= prominent
    return keep


def _fit_segment(x, y):
    """PCHIP-fit one segment (x=log10(res), y=eta already sliced to the
    segment), inserting knots at the worst-offending raw point until
    max|smooth-raw| <= SMOOTH_MAX_ABS and the OPTIMISTIC deviation (smooth
    reporting a lower eta than truth) <= SMOOTH_MAX_OPTIMISTIC.  Returns
    (smooth, ok).  ok=False means the bound could not be met -- the caller
    then falls back to the raw polyline for this segment; in practice this is
    unreachable, since inserting every raw point as a knot makes the fit
    exact (PCHIP passes through every knot), so the loop always converges."""
    n = len(x)
    knots = set(np.flatnonzero(_initial_knots(x, y)).tolist())
    for _ in range(n + 1):          # generous cap; exact once all points are knots
        idx = np.array(sorted(knots))
        d = _pchip_slopes(x[idx], y[idx])
        smooth = _pchip_eval(x[idx], y[idx], d, x)
        diff = smooth - y                              # + = smooth ABOVE raw
        worst_abs = int(np.argmax(np.abs(diff)))
        optimistic = np.maximum(0.0, -diff)             # smooth BELOW raw
        worst_opt = int(np.argmax(optimistic))
        over = abs(diff[worst_abs]) - SMOOTH_MAX_ABS
        opt_over = optimistic[worst_opt] - SMOOTH_MAX_OPTIMISTIC
        if over <= 0 and opt_over <= 0:
            return smooth, True
        insert = worst_abs if over >= opt_over else worst_opt
        if insert in knots:
            return y.copy(), False        # can't improve further -- degenerate
        knots.add(insert)
    return y.copy(), False


def smooth_curve(points, label=""):
    """The display-smoothed eta array for one already-built curve (a list of
    point dicts from build_curve, in resolution order): returns
    (smooth_etas, stats), where smooth_etas is a plain list of floats aligned
    1:1 with `points` (meant to be drawn INSTEAD of the raw eta for the
    connecting line -- see report_template.html) and stats holds the
    build-time deviation report {"max_abs", "max_optimistic"} for the whole
    curve.  Never touches `points` itself.

    Guaranteed: the returned smooth_etas either satisfies BOTH
    max|smooth-raw| <= SMOOTH_MAX_ABS and max_optimistic <= SMOOTH_MAX_OPTIMISTIC
    (up to float tolerance) with every value finite, or -- if that hard
    contract is somehow violated (it shouldn't be; _fit_segment enforces it
    segment-by-segment) -- is the untouched raw eta.  A curve is never shipped
    half-fixed."""
    n = len(points)
    if n == 0:
        return [], dict(max_abs=0.0, max_optimistic=0.0)
    res = np.array([p["res"] for p in points], dtype=float)
    eta = np.array([p["eta"] for p in points], dtype=float)
    x = np.log10(res)
    smooth = eta.copy()
    for lo, hi in _segment_breaks(res, eta):
        if hi - lo + 1 < SMOOTH_MIN_SEGMENT:
            continue                        # short segment: raw passthrough
        seg_smooth, ok = _fit_segment(x[lo:hi + 1], eta[lo:hi + 1])
        if ok:
            smooth[lo:hi + 1] = seg_smooth
        # else: leave the raw passthrough already sitting in `smooth`

    diff = smooth - eta
    finite = bool(np.all(np.isfinite(smooth)))
    max_abs = float(np.max(np.abs(diff))) if finite else float("inf")
    max_optimistic = (float(np.max(np.maximum(0.0, -diff))) if finite
                      else float("inf"))

    # The HARD gate (the per-segment fitter already enforces these bounds
    # segment-by-segment via _fit_segment, so this should be unreachable on
    # real curves): any non-finite value, or a deviation past the advertised
    # SMOOTH_MAX_ABS/SMOOTH_MAX_OPTIMISTIC contract (a tight float tolerance
    # aside), and the WHOLE curve falls back to raw -- no exceptions.  This is
    # the enforcement line; SMOOTH_WARN_ABS below is only a louder forensic
    # signal layered on top of it, not a separate/looser gate.
    tol = 1e-9
    within_bounds = (finite and max_abs <= SMOOTH_MAX_ABS + tol
                     and max_optimistic <= SMOOTH_MAX_OPTIMISTIC + tol)
    if not within_bounds:
        if not finite or max_abs > SMOOTH_WARN_ABS:
            print("make_report: WARNING smoothing violated its bound on %r "
                  "(max|smooth-raw|=%s%s) -- using raw for this curve"
                  % (label, ("%.3f" % max_abs) if finite else "non-finite",
                     "" if finite else ", non-finite values present"),
                  file=sys.stderr)
        return [float(v) for v in eta], dict(max_abs=0.0, max_optimistic=0.0)
    return [float(v) for v in smooth], dict(max_abs=max_abs,
                                             max_optimistic=max_optimistic)


def _print_smooth_report(entries):
    """One grep-able line per curve ('smooth: ...'): build-time visibility
    into how far the display smoother moved the connecting line off the raw
    grid (see smooth_curve).  entries is [((kind, s0_or_None, name), stats), ...]."""
    for (kind, s0, name), stats in entries:
        where = ("imaging[%s]" % s0) if kind == "imaging" else kind
        print("smooth: %s %s: max|smooth-raw|=%.3f max_optimistic=%.3f"
              % (where, name, stats["max_abs"], stats["max_optimistic"]))


STATUS_PRIORITY = {"skipped": 0, "failed": 1, "capped": 2, "ok": 3}


def result_key(row):
    """Canonical heatmap key for one raw sweep-result row."""
    try:
        weighting = row["weighting"]
        robust = 2.0 if weighting == "natural" else round(float(row["robust"]), 2)
        taper = round(float(row["taper_mas"]), 3)
    except (KeyError, TypeError, ValueError):
        return None
    return weighting, robust, taper


def best_result_rows(rows):
    """Deduplicate append-style result CSV rows by lattice key.

    Repair/fill jobs can leave stale rows behind.  Prefer valid simulation
    results over diagnostics, and for identical statuses keep the later
    row because the result files are append-ordered.
    """
    out = {}
    for i, row in enumerate(rows):
        key = result_key(row)
        if key is None:
            continue
        rank = STATUS_PRIORITY.get(row.get("status"), -1)
        prev = out.get(key)
        if prev is None or (rank, i) > prev[:2]:
            out[key] = (rank, i, row)
    return {key: row for key, (_rank, _i, row) in out.items()}


def env_key(key):
    """Canonical heatmap key for one curve anchor tuple."""
    try:
        weighting, robust, taper = key
        robust = 2.0 if weighting == "natural" else round(float(robust), 2)
        taper = round(float(taper or 0.0), 3)
    except (TypeError, ValueError):
        return None
    return weighting, robust, taper


def build_heatmap(subarray, results_rows, sigma_nat, imaging_curve):
    """The canonical sweep lattice as a rectangular cell table."""
    cells_by_key = best_result_rows(results_rows)
    nat = cells_by_key.get(("natural", 2.0, 0.0))
    fine = cells_by_key.get(("briggs", -2.0, 0.0))
    if (not nat or not fine or nat.get("status") != "ok"
            or fine.get("status") != "ok"):
        return None

    res_nat = float(nat["res_geo_arcsec"]) * 1e3
    res_fine = float(fine["res_geo_arcsec"]) * 1e3
    lattice = grid_rows(res_fine, res_nat, subarray)
    tapers = list(lattice[0][2])

    lattice_keys = set()
    for weighting, robust, row_tapers in lattice:
        rkey = 2.0 if weighting == "natural" else round(float(robust), 2)
        for taper in row_tapers:
            lattice_keys.add((weighting, rkey, round(float(taper), 3)))

    # a lattice cell is "on the envelope" when it anchors an imaging-curve
    # interpolant (curve points themselves sit between cells)
    anchors = set()
    for p in imaging_curve:
        for key in p.get("env_keys", []):
            k = env_key(key)
            if k is not None:
                anchors.add(k)
    on_env = anchors & lattice_keys
    off_lattice = len(anchors - lattice_keys)

    row_by_robust = {round(float(r), 2): (w, r, ts)
                     for w, r, ts in lattice if w == "briggs"}
    display_rows = [lattice[0]]
    for robust in sorted(ROBUST_LIST, reverse=True):
        rkey = round(float(robust), 2)
        if rkey in row_by_robust:
            display_rows.append(row_by_robust[rkey])

    def row_label(weighting, robust):
        # fold -0.0 -> 0.0 (config's ROBUST_LIST holds a genuine -0.0; the
        # collect/envelope paths already canonicalize it, this display path
        # read raw rows and showed "-0.0" -- QA review 16 Jul 2026)
        if weighting == "natural":
            return "natural"
        return "%+.1f" % (abs(robust) if robust == 0 else robust)

    rows = []
    for weighting, robust, _row_tapers in display_rows:
        rkey = 2.0 if weighting == "natural" else round(float(robust), 2)
        cells = []
        for taper in tapers:
            key = (weighting, rkey, round(float(taper), 3))
            row = cells_by_key.get(key)
            if row is None:
                cells.append(None)
                continue
            status = row.get("status")
            if status in ("ok", "capped"):
                cells.append(dict(
                    eta=float(row["sigma_dirty"]) / sigma_nat,
                    skirt=float(row["skirt"]) if row["skirt"] else None,
                    res=float(row["res_geo_arcsec"]) * 1e3,
                    env=key in on_env,
                    status=status))
            elif status == "skipped":
                cells.append(dict(status="skipped"))
            elif status == "failed":
                cells.append(dict(status="failed"))
            else:
                cells.append(None)
        rows.append(dict(label=row_label(weighting, robust), cells=cells))
    return dict(tapers=tapers, rows=rows, off_lattice=off_lattice)


def build_sens_table(las):
    """{subarray: {freq_ghz: [...], sigma_nat_ujy: [...]}} -- natural rms in
    microJy/beam for 1 h in a 1 MHz channel, per offered subarray, on a
    0.02-dex grid over the ngVLA receiver ranges (1.2-50.5, 70-116 GHz).
    Uses the line-mode calculator path (no continuum band re-centering) via
    sa_select.sensitivity, incl. donor rescaling for subarrays the memo-96
    calculator lacks. Confusion is deliberately excluded and reported as a
    separate PSF-volume-derived quantity."""
    import csv as _csv
    import math
    from sa_select import sensitivity as sens

    calc_names = {}
    with open(SUBARRAYS_CSV) as f:
        for r in _csv.DictReader(f):
            calc_names[r["name"]] = r["calc_name"].strip() or r["name"]

    freqs = []
    for lo, hi in ((1.2, 50.5), (70.0, 116.0)):
        x = math.log10(lo)
        while 10 ** x < hi:
            freqs.append(round(10 ** x, 4))
            x += 0.02
        freqs.append(hi)

    C_M_S = 2.99792458e8
    out = {}
    for name in ACTIVE_ORDER:
        calc = calc_names.get(name, name)
        sig = []
        for f_ghz in freqs:
            try:
                delta_v = C_M_S * 1e6 / (f_ghz * 1e9)     # 1 MHz channel
                s = sens.natural_rms(calc, f_ghz, t_obs_hr=1.0,
                                     delta_v=delta_v,
                                     include_confusion=False)
                sig.append(round(s * 1e6, 4))             # uJy/beam
            except ValueError:
                sig.append(None)                          # outside a band edge
        out[name] = dict(freq_ghz=freqs, sigma_nat_ujy=sig)
    return out


def build_mfs_sens_table():
    """Thermal continuum rms expressed in the report's 1-MHz basis.

    The browser keeps one common time formula.  Multiplying the fixed-window
    continuum rms by sqrt(window_MHz) produces the equivalent 1-MHz reference;
    dividing by that same fixed bandwidth in the browser recovers the exact
    continuum value.  The controls are pinned to this campaign window.
    """
    from sa_select import sensitivity as sens

    calc_names = {}
    with open(SUBARRAYS_CSV) as handle:
        for row in csv.DictReader(handle):
            calc_names[row["name"]] = row["calc_name"].strip() or row["name"]
    bandwidth_mhz = (FREQ_HI_GHZ - FREQ_LO_GHZ) * 1000.0
    out = {}
    for name in ACTIVE_ORDER:
        sigma = sens.natural_rms(
            calc_names.get(name, name), REF_FREQ_GHZ, t_obs_hr=1.0,
            delta_v=None, include_confusion=False)
        out[name] = {
            "freq_ghz": [REF_FREQ_GHZ],
            "sigma_nat_ujy": [sigma * 1e6 * math.sqrt(bandwidth_mhz)],
        }
    return out


def build_psf_metric_summary(profile_dir=None):
    """Small per-lattice-point PSF metric map embedded in the main payload.

    Full profiles remain lazy-loaded.  Embedding only these scalars lets the
    calculator show confusion synchronously and lets a future MFS selector
    enforce its confusion floor without loading megabytes of profile arrays.
    """
    from export_psf_data import transform_profile_lines

    profile_dir = PROFILE_DIR if profile_dir is None else profile_dir
    out = {}
    for name in ACTIVE_ORDER:
        stem = name.replace("+", "_").replace("-", "_")
        path = os.path.join(profile_dir, stem + ".jsonl")
        if not os.path.isfile(path):
            continue
        with open(path) as handle:
            profiles, _warnings = transform_profile_lines(handle)
        compact = []
        for key, profile in profiles.items():
            required = ("res_geo_arcsec", "restoring_fwhm_geo_arcsec",
                        "psf_squared_volume_first_null_sr")
            if not all(field in profile for field in required):
                continue
            # Compact positional schema used only by report_template.html:
            # key, resolution, restoring-beam geo-mean FWHM, integral(B^2),
            # volume ratio, and whether the radial-minimum fallback supplied
            # the null.
            compact.append([
                key, profile["res_geo_arcsec"],
                profile["restoring_fwhm_geo_arcsec"],
                profile["psf_squared_volume_first_null_sr"],
                profile.get("psf_to_gaussian_volume_ratio"),
                bool(profile.get("first_null_is_proxy")),
            ])
        if compact:
            out[name] = compact
    return out


def annotate_adaptive_validation(display_by):
    """Attach conservative residual-validation states to displayed samples.

    Adaptive convergence belongs to cells, not points.  For the report, a
    point is called residual-validated only when every terminal quadtree cell
    touching it passed the residual convergence test.  Natural weighting,
    taper=0, and coordinates outside the positive-taper Briggs quadtree are
    explicitly ``not-assessed``.  Dominance retirement and unfinished active
    cells do not count as convergence.
    """
    from adaptive import (PointTable, Sampler, results_csv_path,
                          RESIDUAL_VALIDATED, NOT_RESIDUAL_VALIDATED,
                          NOT_ASSESSED)

    counts = {}
    for name, points in display_by.items():
        path = results_csv_path(name)
        sampler = None
        if os.path.isfile(path):
            cap = BEAM_CAP_ARCSEC.get(name)
            table = PointTable.from_csv(
                path, subarray=name,
                beam_cap_mas=(float(cap) * 1e3 if cap is not None else None))
            if table.has_anchors:
                sampler = Sampler(name, table=table,
                                  mode="fresh" if MFS else "retrofit")
        tally = {RESIDUAL_VALIDATED: 0, NOT_RESIDUAL_VALIDATED: 0,
                 NOT_ASSESSED: 0}
        for point in points:
            state = (sampler.point_validation_state(
                point["weighting"], point["robust"], point["taper"])
                if sampler is not None else NOT_ASSESSED)
            point["validation"] = state
            tally[state] += 1
        counts[name] = dict(
            residual_validated=tally[RESIDUAL_VALIDATED],
            not_residual_validated=tally[NOT_RESIDUAL_VALIDATED],
            not_assessed=tally[NOT_ASSESSED])
    return counts


def build_payload():
    """The report's full data payload (the JSON injected as __DATA__) for the
    ACTIVE (rev, sim_mode) routing.  Factored out of main() so the combined
    all-campaigns report can gather one payload per combo (each built in a
    subprocess with that combo's environment, honoring config's env-frozen
    RESULTS_DIR/grid state)."""
    samples_by = {name: [] for name in ACTIVE_ORDER}
    display_by = {name: [] for name in ACTIVE_ORDER}
    resolution_column = ("resolution_arcsec_native" if MFS
                         else "resolution_arcsec_30ghz")
    taper_column = ("taper_arcsec_native" if MFS
                    else "taper_arcsec_30ghz")
    with open(CURVES_CSV) as f:
        for r in csv.DictReader(f):
            name = r["subarray"]
            if name not in samples_by:
                continue
            capped = ((r.get("sample_status") or "ok").strip()
                      == "capped_anchor")
            # DISPLAY trim (shared with refine via sample_from_row): the eta >
            # ~5 regime (>25x natural time) is not of interest for the plots --
            # the engine/selector itself does NOT censor by ETA_CAP
            # (envelope.build_points), so at those extreme resolutions the
            # Python tool still reports a solution where this report shows none.
            # Capped anchors obey the same trim (a beyond-cap anchor with eta >
            # 5 could only support curve points the trim excludes anyway); they
            # feed the envelope but not the dots.
            s = sample_from_row(
                res_mas=float(r[resolution_column]) * 1e3,   # mas
                eta=float(r["eta"]),
                skirt=float(r["skirt"]) if r["skirt"] else None,
                weighting=r["weighting"],
                robust=float(r["robust"]) if r["robust"] else None,
                taper_mas=(float(r[taper_column]) * 1e3
                           if r[taper_column] else 0.0),
                capped=capped)
            if s is None:
                continue
            samples_by[name].append(s)
            if not s["capped"]:
                display_by[name].append(s)

    las = {}
    caps = {name: None for name in ACTIVE_ORDER}
    with open(SUBARRAYS_CSV) as f:
        for r in csv.DictReader(f):
            lam = 0.299792458 / REF_FREQ_GHZ
            las[r["name"]] = dict(
                mas=float(r["las_coeff"]) * lam / float(r["b_min_m"])
                    * 206264.8 * 1e3,
                coeff=float(r["las_coeff"]),
                provisional="PROVISIONAL" in r["las_coeff_note"],
                n_ant=int(r["n_ant"]))
            cap_column = ("beam_cap_arcsec_native" if MFS
                          else "beam_cap_arcsec_30ghz")
            cap = r.get(cap_column, "").strip()
            if r["name"] in caps:
                caps[r["name"]] = float(cap) * 1e3 if cap else None

    skirt_setpoints = ["%.2f" % s0 for s0 in SKIRT_SETPOINTS]
    imaging = {}
    for s0, key in zip(SKIRT_SETPOINTS, skirt_setpoints):
        imaging[key] = ({n: [] for n in ACTIVE_ORDER} if CURVE_TYPES == "ptsrc"
                        else {n: build_curve(samples_by[n], s0,
                                             max_res=caps[n])
                              for n in ACTIVE_ORDER})
        if key != SKIRT_DEFAULT_KEY:
            for curve in imaging[key].values():
                for p in curve:
                    p.pop("env_keys", None)
    heatmaps = {}
    adaptive_leaves = {}
    if os.path.isdir(RESULTS_DIR):
        for base in sorted(os.listdir(RESULTS_DIR)):
            if not base.endswith(".csv") or ".csv.shard_" in base:
                continue
            path = os.path.join(RESULTS_DIR, base)
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
            if not rows:
                continue
            name = next((r.get("subarray", "").strip()
                         for r in rows if r.get("subarray")), "")
            if name not in ACTIVE_ORDER:
                continue
            if MFS:
                # The collected native table deliberately carries no hidden
                # topology state. Reconstruct the AMR leaves from the durable
                # result rows, exactly as the sampler does after a restart.
                from adaptive import PointTable, Sampler
                table = PointTable(rows, subarray=name,
                                   beam_cap_mas=caps.get(name))
                adaptive_leaves[name] = Sampler(
                    name, table=table, beam_cap_mas=caps.get(name)
                ).envelope_leaves()
                continue                 # legacy rectangular heatmap is invalid
            cells_by_key = best_result_rows(rows)
            nat = cells_by_key.get(("natural", 2.0, 0.0))
            if not nat or nat.get("status") != "ok":
                continue
            hm = build_heatmap(name, rows, float(nat["sigma_dirty"]),
                               imaging[SKIRT_DEFAULT_KEY][name])
            if hm is not None:
                heatmaps[name] = hm
    for curve in imaging[SKIRT_DEFAULT_KEY].values():
        # anchors only feed the default-threshold heatmaps
        for p in curve:
            p.pop("env_keys", None)
    pointsource = {n: build_curve(samples_by[n], max_res=caps[n],
                                  leaves=adaptive_leaves.get(n))
                   for n in ACTIVE_ORDER}
    if MFS:
        missing_topology = [n for n in ACTIVE_ORDER
                            if samples_by[n] and n not in adaptive_leaves]
        if missing_topology:
            raise RuntimeError(
                "MFS report cannot reconstruct adaptive topology for: %s"
                % ", ".join(missing_topology))
    for curve in pointsource.values():
        for p in curve:
            p.pop("env_keys", None)

    validation_counts = annotate_adaptive_validation(display_by)

    # Display-only smoothing (see smooth_curve above): a PARALLEL eta array
    # per curve, keyed identically to `imaging`/`pointsource` so neither of
    # those (nor their point dicts, nor any downstream consumer -- notably
    # backfill_psf.build_curve callers and the PSF-inspector's env_keys
    # lookups) is touched.  Every skirt setpoint gets one, not just the
    # default, since the template's s0 selector can switch to any of them.
    imaging_smooth, smooth_report = {}, []
    for key, curves in imaging.items():
        imaging_smooth[key] = {}
        for name, curve in curves.items():
            smooth, stats = smooth_curve(curve, label="imaging[%s] %s"
                                          % (key, name))
            imaging_smooth[key][name] = smooth
            smooth_report.append((("imaging", key, name), stats))
    pointsource_smooth = {}
    for name, curve in pointsource.items():
        smooth, stats = smooth_curve(curve, label="pointsource %s" % name)
        pointsource_smooth[name] = smooth
        smooth_report.append((("pointsource", None, name), stats))
    _print_smooth_report(smooth_report)

    data = dict(order=ACTIVE_ORDER, las=las, caps=caps, samples=display_by,
                skirt_setpoints=skirt_setpoints,
                s0_default=SKIRT_DEFAULT_KEY,
                imaging=imaging,
                imaging_smooth=imaging_smooth,
                pointsource=pointsource,
                pointsource_smooth=pointsource_smooth,
                counts={n: len(display_by[n]) for n in ACTIVE_ORDER},
                validation_counts=validation_counts,
                heatmaps=heatmaps)
    if MFS:
        data.update(ref_freq_ghz=REF_FREQ_GHZ,
                    fixed_window=dict(band=BAND, lo_ghz=FREQ_LO_GHZ,
                                      hi_ghz=FREQ_HI_GHZ))

    # core+spiral natural-PSF radial profile measured 5 Jul 2026 (subsampled
    # diagnostic dump; regenerate with the snippet in PLAN.md if needed)
    data["profile"] = dict(
        subarray="core+spiral", fitted_fwhm_mas=285.7, memo121_fwhm_mas=147.7,
        r_arcsec=[0.0055, 0.0495, 0.0935, 0.1375, 0.1815, 0.2255, 0.2695,
                  0.3135, 0.3575, 0.4015, 0.4455, 0.4895, 0.5335, 0.5775,
                  0.6215, 0.6655, 0.7095, 0.7535, 0.7975, 0.8415, 0.8855,
                  0.9295, 0.9735, 1.0175, 1.0615, 1.1055, 1.1495, 1.1935,
                  1.2375, 1.2815, 1.3255, 1.3695, 1.4135, 1.4575, 1.5015,
                  1.5455, 1.5895, 1.6335],
        psf=[1.000, 0.754, 0.537, 0.468, 0.395, 0.342, 0.291, 0.249, 0.209,
             0.176, 0.147, 0.120, 0.100, 0.080, 0.070, 0.058, 0.050, 0.048,
             0.042, 0.038, 0.039, 0.039, 0.035, 0.033, 0.036, 0.038, 0.036,
             0.032, 0.029, 0.026, 0.028, 0.024, 0.019, 0.016, 0.016, 0.016,
             0.018, 0.018])

    # natural-weighting point-source rms basis for the in-page calculator:
    # sigma_nat (Jy/beam) for 1 h on-source in a 1 MHz channel, on a log
    # frequency grid over the receiver bands.  Scales exactly as
    # 1/sqrt(bandwidth * time); the page applies the curve engine's eta.
    data["sens"] = build_mfs_sens_table() if MFS else build_sens_table(las)
    from sa_select import sensitivity as _sensitivity
    data["confusion_model"] = _sensitivity.confusion_model()
    data["psf_metrics"] = build_psf_metric_summary()

    # QA cross-check vs the sensitivity calculator's native beams
    data["qa"] = [
        dict(sa="core-inner", nat_sim=2036.65, nat_calc=None, skirt_nat=0.104),
        dict(sa="core", nat_sim=710.1, nat_calc=725.6, skirt_nat=0.116),
        dict(sa="spiral", nat_sim=76.13, nat_calc=76.15, skirt_nat=0.088),
        dict(sa="mid", nat_sim=2.96, nat_calc=2.91, skirt_nat=0.227),
        dict(sa="core+spiral", nat_sim=285.7, nat_calc=147.7, skirt_nat=0.274),
        dict(sa="spiral+mid", nat_sim=11.12, nat_calc=4.37, skirt_nat=0.308),
        dict(sa="core+mid", nat_sim=17.81, nat_calc=None, skirt_nat=0.507),
        dict(sa="main", nat_sim=None, nat_calc=2.42, skirt_nat=None),
    ]

    # per-combo header/labels/notes: the template applies these in BOTH the
    # combined report and standalone per-combo reports (so e.g. the snapshot
    # physics note and the Rev-F-reference card gating work everywhere)
    data["combo"] = combo_entry(REV, SIM_MODE, BAND)

    # Subarrays with a lazy-load PSF payload on disk at build time.  The page
    # uses this to tell "never exported" apart from "the psf/ folder is not
    # next to this HTML file" when a payload script fails to load.
    psf_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "reports", "psf", data["combo"]["key"])
    data["psf_exported"] = sorted(
        n for n in ACTIVE_ORDER
        if os.path.isfile(os.path.join(
            psf_dir, n.replace("+", "_").replace("-", "_") + ".js")))
    return data


def main(out_path, title_label=None):
    data = build_payload()
    with open(TEMPLATE) as f:
        html = f.read()
    html = html.replace("__DATA__", json.dumps(data))
    # For a non-default combo, relabel the static "Rev F / 4 h track" title text
    # so the page names its own configuration.  Done as targeted string
    # replacements on the rendered HTML (NOT the shared template), so the
    # default (title_label=None) output stays byte-for-byte identical.  The
    # profile/qa diagnostic blocks remain the Rev F reference values (a known
    # cosmetic limitation, noted in PLAN.md).
    if title_label:
        html = (html
                .replace("NGVLA Rev F subarray curves",
                         "NGVLA %s subarray curves" % title_label)
                .replace("Rev&thinsp;F taperability",
                         "%s taperability" % title_label)
                .replace("simulations of each Rev&thinsp;F",
                         "simulations of each %s" % title_label))
    _atomic_write(out_path, html)
    print("wrote", out_path)


def _atomic_write(out_path, html):
    """tmp + os.replace so concurrent collect jobs (four polish campaigns can
    finish together) never leave a truncated or interleaved report."""
    tmp = out_path + ".tmp.%d" % os.getpid()
    with open(tmp, "w") as f:
        f.write(html)
    os.replace(tmp, out_path)


_REV_DISPLAY = {"revF": "Rev F", "revD": "Rev D", "revC": "Rev C.01"}
_REV_HTML = {"revF": "Rev&thinsp;F", "revD": "Rev&thinsp;D",
             "revC": "Rev&thinsp;C.01"}
_SIM_LABEL = {"track": "4 h track", "snapshot": "snapshot"}
_SIM_DESC_HTML = {"track": "4&thinsp;h track",
                  "snapshot": "single 60&thinsp;s snapshot at transit"}

# rendered under the header for snapshot combos (the 15 Jul 2026 diagnosis:
# the missing sub-natural branch is physics under the adopted convention, and
# fragmented LONG-family segments are honest coverage gaps)
_SNAPSHOT_NOTE_HTML = (
    "<strong>Snapshot mode:</strong> The simulation uses one monochromatic "
    "60&thinsp;s integration at transit. Each baseline gives one uv sample. "
    "On the current density grid, most occupied uv cells contain no more "
    "than one visibility. Thus, Briggs weighting has little effect for the "
    "core, spiral, mid, core-inner, and long subarrays. Their curves start "
    "near the natural-weighting beam. Composite subarrays can reach finer "
    "beams because more than one sample can occur in a uv cell. A real "
    "continuum snapshot has more uv coverage from its bandwidth and time "
    "samples. Briggs weighting can have more effect on real data. Snapshot "
    "beams can also be long and narrow. The plotted geometric-mean resolution "
    "does not show the axis ratio. Dotted LONG-family segments show measured "
    "coverage gaps. See PLAN.md for the analysis from 15 Jul 2026.")

# the imaging-curve explanation shared by every combo's subtitle (matches the
# template's static paragraph)
_SUB_TAIL_HTML = (
    "The imaging curves use a selectable PSF skirt limit, s<sub>0</sub>. "
    "The PSF skirt is the average PSF level at a radius of one FWHM. The "
    "default limit is 10%. At each resolution, the curve shows the result "
    "with the lowest &eta; that meets the limit. If no result meets the "
    "limit, the curve shows the lowest available skirt and uses a hollow "
    "marker.")


def combo_entry(rev, sim_mode, band="", ref_freq_ghz=None,
                freq_lo_ghz=None, freq_hi_ghz=None):
    """Dropdown metadata + per-combo header HTML for the combined report."""
    rev_html = _REV_HTML.get(rev, rev)
    snap = sim_mode == "snapshot"
    if band:
        ref = REF_FREQ_GHZ if ref_freq_ghz is None else float(ref_freq_ghz)
        flo = FREQ_LO_GHZ if freq_lo_ghz is None else float(freq_lo_ghz)
        fhi = FREQ_HI_GHZ if freq_hi_ghz is None else float(freq_hi_ghz)
        mode_html = _SIM_DESC_HTML.get(sim_mode, sim_mode)
        h1 = ("%s %s broadband MFS point-source taperability curves"
              % (rev_html, band.upper()))
        sub = ("These plots show point-source sensitivity cost (&eta;) against "
               "the native MFS beam for the fixed %.3g&ndash;%.3g&thinsp;GHz "
               "spectral window (reference %.3g&thinsp;GHz). Sensitivity cost "
               "is the image rms divided by the same-window natural-weighting "
               "rms. The data come from %s noise simulations at declination "
               "+24&deg;. Fixed-window MFS curves are not monochromatic "
               "30/f-scaled curves."
               % (flo, fhi, ref, mode_html))
        return dict(key="%s_%s_%s" % (rev, sim_mode, band),
                    label="%s — %s — %s" % (_REV_DISPLAY.get(rev, rev),
                                             _SIM_LABEL.get(sim_mode, sim_mode),
                                             band.upper()),
                    h1_html=h1, sub_html=sub, note_html="",
                    imaging_omitted=True, calculator_omitted=False)
    h1 = "%s %staperability &amp; sculptability curves" % (
        rev_html, "snapshot " if snap else "")
    sub = ("These plots show sensitivity cost (&eta;) against angular "
           "resolution at 30&thinsp;GHz. Sensitivity cost is the image rms "
           "divided by the rms for natural weighting. The sensitivity "
           "calculation uses underlying code similar to the "
           "<a href=\"https://ngect.nrao.edu\">ngVLA Exposure Calculator "
           "Tool (ngECT)</a>. The data come from "
           "noise simulations of each %s subarray. Each simulation uses a "
           "%s at declination +24&deg;. The simulations use a grid of "
           "Briggs robust and uv-taper values, with adaptive refinement "
           "where needed. %s"
           % (rev_html, _SIM_DESC_HTML.get(sim_mode, sim_mode),
              _SUB_TAIL_HTML))
    return dict(key="%s_%s" % (rev, sim_mode),
                label="%s — %s" % (_REV_DISPLAY.get(rev, rev),
                                   _SIM_LABEL.get(sim_mode, sim_mode)),
                h1_html=h1, sub_html=sub,
                note_html=_SNAPSHOT_NOTE_HTML if snap else "")


def combined_combo_plan(reg_rows, release=False):
    """Map config-registry rows to the combos a combined build should offer:
    [(row, entry), ...] in registry order, entry being the combo_entry()
    dropdown metadata.  Release mode keeps ONLY the RELEASE_COMBOS keys and
    stamps entry["imaging_omitted"] = True on the RELEASE_PTSRC_ONLY ones
    (the page reads that flag per active campaign).  Pure over the row dicts:
    sample availability is checked separately by the caller, so a registered
    combo with no samples yet is still skipped gracefully there."""
    plan = []
    for r in reg_rows:
        band = (r.get("band") or "").strip().lower()
        entry = combo_entry(
            r["rev"].strip(), r["sim_mode"].strip(), band,
            r.get("ref_freq_ghz") or None, r.get("freq_lo_ghz") or None,
            r.get("freq_hi_ghz") or None)
        if release:
            if entry["key"] not in RELEASE_COMBOS:
                continue
            if entry["key"] in RELEASE_PTSRC_ONLY:
                entry["imaging_omitted"] = True
        plan.append((r, entry))
    return plan


PSF_REGISTER_RE = re.compile(
    r'^window\.PSF_REGISTER\(\s*"([^"]+)"\s*,\s*(.*)\)\s*;?\s*$', re.S)


def _reject_json_constant(tok):
    """parse_constant callback for json.loads: Python's json module silently
    ACCEPTS the NaN/Infinity/-Infinity extension by default, but the
    browser's JSON.parse does not -- an embedded payload containing one
    would parse fine here and then fail client-side.  Reject it up front."""
    raise ValueError("JSON constant %r is not valid JSON (the browser's "
                     "JSON.parse would reject it)" % (tok,))


def embed_psf_payloads(html, combo_keys, psf_base=None):
    """Inline every release-campaign PSF payload into `html` as gzip+base64
    <script type="text/plain"> blocks, so the release page travels as ONE
    file (no sibling reports/psf/ directory).  The lazy sibling-file loader
    (report_template.html's loadPsfData) checks for a matching
    data-psf-id block FIRST and, if found, inflates it client-side via
    DecompressionStream -- the blocks are inert text (a <script
    type="text/plain"> never executes), so they are safe to drop anywhere in
    the DOM as long as they exist before the page's own script tries to read
    them.

    For each combo key (in the given order), reads sorted
    <psf_base>/<key>/*.js -- each file is exactly one
    window.PSF_REGISTER("<comboKey>/<subarray>", {...json...}); wrapper (a
    missing combo directory is skipped, not an error: not every campaign has
    PSF data exported).  Returns the new html with all blocks inserted
    immediately before the template's single <script> tag (before the main
    script runs, since it renders an initial PSF panel synchronously)."""
    if psf_base is None:
        psf_base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "reports", "psf")
    blocks = []
    for key in combo_keys:
        combo_dir = os.path.join(psf_base, key)
        if not os.path.isdir(combo_dir):
            continue
        for base in sorted(os.listdir(combo_dir)):
            if not base.endswith(".js"):
                continue
            path = os.path.join(combo_dir, base)
            with open(path) as f:
                text = f.read()
            m = PSF_REGISTER_RE.match(text)
            if not m:
                raise ValueError(
                    "embed_psf_payloads: %s does not match the "
                    "window.PSF_REGISTER(...) wrapper" % path)
            payload_id, json_text = m.group(1), m.group(2)
            if "\\" in payload_id:
                # the regex captures the SOURCE spelling of the id string;
                # an escape (e.g. \/) would embed under the escaped spelling
                # and never be found by the loader's literal id lookup
                raise ValueError(
                    "embed_psf_payloads: %s: id %r contains a JS escape -- "
                    "escaped ids are unsupported" % (path, payload_id))
            try:
                json.loads(json_text, parse_constant=_reject_json_constant)
            except ValueError as exc:
                raise ValueError("embed_psf_payloads: %s: %s"
                                 % (path, exc)) from None
            compressed = gzip.compress(json_text.encode("utf-8"), 9)
            b64 = base64.b64encode(compressed).decode("ascii")
            blocks.append('<script type="text/plain" data-psf-id="%s">%s'
                          '</script>' % (payload_id, b64))
    marker = "<script>"
    idx = html.find(marker)
    if idx == -1:
        raise ValueError("embed_psf_payloads: no <script> tag found in html")
    return html[:idx] + "\n".join(blocks) + "\n" + html[idx:]


def build_combined(out_path, release=False):
    """The all-campaigns report: one payload per registered (rev, sim_mode)
    with curve data, each built by a SUBPROCESS running this script with that
    combo's environment (config freezes RESULTS_DIR / grid state at import,
    so a single process cannot build them all), injected together with a
    campaign dropdown the page uses to swap its contents.  release=True
    builds the public page instead (combos restricted / flagged per
    combined_combo_plan, plain "NGVLA subarray curves" title)."""
    import subprocess
    import tempfile

    reg = os.path.join(DATA_DIR, "config_registry.csv")
    with open(reg, newline="") as f:
        reg_rows = list(csv.DictReader(f))
    combos, payloads = [], {}
    for r, entry in combined_combo_plan(reg_rows, release=release):
        rev, mode = r["rev"].strip(), r["sim_mode"].strip()
        band = (r.get("band") or "").strip().lower()
        samples_csv = os.path.join(DATA_DIR, r["samples_csv"].strip())
        if not os.path.isfile(samples_csv) or os.path.getsize(samples_csv) < 100:
            print("combined: skipping %s/%s/%s (no curve samples yet)"
                  % (rev, mode, band or "mono"))
            continue
        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="payload_")
        os.close(fd)
        try:
            env = dict(os.environ, NGVLA_REV=rev, NGVLA_SIM_MODE=mode,
                       NGVLA_BAND=band)
            if band:
                nchan = (r.get("nchan") or "").strip()
                if not nchan:
                    raise RuntimeError(
                        "combined: %s/%s/%s has samples but registry nchan "
                        "is unset" % (rev, mode, band))
                env["NGVLA_NCHAN"] = nchan
            subprocess.run(
                [sys.executable, os.path.abspath(__file__),
                 "--rev", rev, "--sim-mode", mode, "--band", band,
                 "--payload-json", tmp],
                env=env, check=True)
            with open(tmp) as f:
                payload = json.load(f)
        finally:
            os.unlink(tmp)
        combos.append(entry)
        payloads[entry["key"]] = payload
        print("combined: gathered %s/%s/%s (%d subarrays)"
              % (rev, mode, band or "mono", len(payload.get("order", []))))
    if not combos:
        raise SystemExit("combined: no combo has curve data")
    # dropdown order per bmason: rev first (F, D, C), track before snapshot;
    # unknowns last
    pref = ["revF_track", "revF_snapshot", "revD_track", "revD_snapshot",
            "revC_track"]
    combos.sort(key=lambda c: (pref.index(c["key"]) if c["key"] in pref
                               else len(pref), c["key"]))
    default = "revF_track" if "revF_track" in payloads else combos[0]["key"]
    data = dict(payloads=payloads, combos=combos, default=default)
    with open(TEMPLATE) as f:
        html = f.read()
    html = html.replace("__DATA__", json.dumps(data))
    html = html.replace("NGVLA Rev F subarray curves",
                        "NGVLA subarray curves" if release
                        else "NGVLA subarray curves — all campaigns")
    if release:
        # the release page travels alone (scp'd as one HTML file), so its PSF
        # payloads are embedded inline rather than left as sibling
        # reports/psf/<key>/*.js files (see embed_psf_payloads)
        html = embed_psf_payloads(html, [c["key"] for c in combos])
        blocks = re.findall(
            r'<script type="text/plain" data-psf-id="[^"]*">([^<]*)</script>',
            html)
        mb = sum(len(b) for b in blocks) / 1e6
        print("release: embedded %d PSF payload blocks (%.1f MB base64)"
              % (len(blocks), mb))
    _atomic_write(out_path, html)
    print("wrote", out_path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out_path", nargs="?", default=None,
                    help="output HTML path (default: "
                         "<rev>-<sim_mode>-curves.html, or revf-curves.html)")
    ap.add_argument("--rev", default=REV,
                    help="config revision (default: $NGVLA_REV or revF)")
    ap.add_argument("--sim-mode", default=SIM_MODE, dest="sim_mode",
                    help="simulation mode (default: $NGVLA_SIM_MODE or track)")
    ap.add_argument("--band", default=BAND,
                    help="fixed-window MFS band (default: $NGVLA_BAND or mono)")
    ap.add_argument("--payload-json", default=None, metavar="PATH",
                    help="write the combo's data payload as JSON instead of "
                         "an HTML report (used by --combined)")
    ap.add_argument("--combined", action="store_true",
                    help="build the all-campaigns report (one payload per "
                         "registered combo with data, campaign dropdown); "
                         "ignores --rev/--sim-mode/the environment")
    ap.add_argument("--release", action="store_true",
                    help="with --combined only: build the public release page "
                         "(RELEASE_COMBOS campaigns only, point-source-only "
                         "campaigns flagged imaging_omitted)")
    args = ap.parse_args()

    if args.release and not args.combined:
        ap.error("--release is only valid together with --combined")

    if args.combined:
        default_out = ("reports/ngvla-curves-release.html" if args.release
                       else "reports/ngvla-curves.html")
        build_combined(args.out_path or default_out, release=args.release)
        sys.exit(0)

    # RESULTS_DIR (the heatmap source) is derived from the environment at
    # import time, so --rev/--sim-mode MUST agree with NGVLA_REV/NGVLA_SIM_MODE.
    # Refuse a mismatch rather than silently drawing another combo's heatmaps.
    if (args.rev, args.sim_mode, args.band) != (REV, SIM_MODE, BAND):
        ap.error("--rev/--sim-mode/--band (%s/%s/%s) disagree with the environment "
                 "(NGVLA_REV=%s NGVLA_SIM_MODE=%s NGVLA_BAND=%s); export those to match, so "
                 "RESULTS_DIR points at the right results dir"
                 % (args.rev, args.sim_mode, args.band, REV, SIM_MODE, BAND))

    is_default = (args.rev, args.sim_mode, args.band) == ("revF", "track", "")
    if not is_default:
        SUBARRAYS_CSV, CURVES_CSV = registry_paths(args.rev, args.sim_mode,
                                                   args.band)
        ACTIVE_ORDER = offered_order(SUBARRAYS_CSV)
        label = "%s — %s" % (_REV_DISPLAY.get(args.rev, args.rev),
                                  args.sim_mode)
        suffix = "-%s" % args.band if args.band else ""
        default_out = "%s-%s%s-curves.html" % (
            args.rev.lower(), args.sim_mode, suffix)
    else:
        label = None
        default_out = "revf-curves.html"

    if args.payload_json:
        with open(args.payload_json, "w") as f:
            json.dump(build_payload(), f)
        print("wrote payload", args.payload_json)
        sys.exit(0)

    main(args.out_path or default_out, title_label=label)

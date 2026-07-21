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
import csv
import json
import os
import sys

import numpy as np

from config import REPO, RESULTS_DIR, ROBUST_LIST, grid_rows, REV, SIM_MODE

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

# Data routing.  These module globals default to (revF, track) so the plain
# `make_report.py out.html` call is byte-identical to the original; __main__
# re-points them for a different registered (rev, sim_mode).  ACTIVE_ORDER is
# ORDER filtered to the combo's offered subarrays (identical to ORDER for the
# default, since subarrays.csv holds exactly those 14).
CURVES_CSV = os.path.join(DATA_DIR, "revf_curves.csv")
SUBARRAYS_CSV = os.path.join(DATA_DIR, "subarrays.csv")
ACTIVE_ORDER = ORDER


def registry_paths(rev, sim_mode):
    """(subarrays_csv, samples_csv) absolute paths for (rev, sim_mode) from
    config_registry.csv; SystemExit with guidance if the combo is absent."""
    reg = os.path.join(DATA_DIR, "config_registry.csv")
    with open(reg, newline="") as f:
        for r in csv.DictReader(f):
            if r["rev"].strip() == rev and r["sim_mode"].strip() == sim_mode:
                return (os.path.join(DATA_DIR, r["subarrays_csv"].strip()),
                        os.path.join(DATA_DIR, r["samples_csv"].strip()))
    raise SystemExit("make_report.py: no config_registry.csv row for "
                     "(rev=%r, sim_mode=%r)" % (rev, sim_mode))


def offered_order(subarrays_csv):
    """ORDER restricted to the subarrays this combo actually offers, in ORDER's
    display order (so color slots and layout are reused)."""
    with open(subarrays_csv, newline="") as f:
        offered = {r["name"].strip() for r in csv.DictReader(f)}
    return [n for n in ORDER if n in offered]


def build_curve(samples, skirt_max=None, max_res=None):
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
    for c in Envelope(samples).curve(skirt_max=skirt_max, grid_dex=GRID_DEX,
                                     max_res=max_res):
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

    Repair/fill jobs can leave stale rows behind.  Prefer offerable
    measurements over diagnostics, and for identical statuses keep the later
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
    calculator lacks."""
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
                                     delta_v=delta_v)
                sig.append(round(s * 1e6, 4))             # uJy/beam
            except ValueError:
                sig.append(None)                          # outside a band edge
        out[name] = dict(freq_ghz=freqs, sigma_nat_ujy=sig)
    return out


def build_payload():
    """The report's full data payload (the JSON injected as __DATA__) for the
    ACTIVE (rev, sim_mode) routing.  Factored out of main() so the combined
    all-campaigns report can gather one payload per combo (each built in a
    subprocess with that combo's environment, honoring config's env-frozen
    RESULTS_DIR/grid state)."""
    samples_by = {name: [] for name in ACTIVE_ORDER}
    display_by = {name: [] for name in ACTIVE_ORDER}
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
                res_mas=float(r["resolution_arcsec_30ghz"]) * 1e3,   # mas
                eta=float(r["eta"]),
                skirt=float(r["skirt"]) if r["skirt"] else None,
                weighting=r["weighting"],
                robust=float(r["robust"]) if r["robust"] else None,
                taper_mas=(float(r["taper_arcsec_30ghz"]) * 1e3
                           if r["taper_arcsec_30ghz"] else 0.0),
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
            lam = 0.299792458 / 30.0
            las[r["name"]] = dict(
                mas=float(r["las_coeff"]) * lam / float(r["b_min_m"])
                    * 206264.8 * 1e3,
                coeff=float(r["las_coeff"]),
                provisional="PROVISIONAL" in r["las_coeff_note"],
                n_ant=int(r["n_ant"]))
            cap = r.get("beam_cap_arcsec_30ghz", "").strip()
            if r["name"] in caps:
                caps[r["name"]] = float(cap) * 1e3 if cap else None

    skirt_setpoints = ["%.2f" % s0 for s0 in SKIRT_SETPOINTS]
    imaging = {}
    for s0, key in zip(SKIRT_SETPOINTS, skirt_setpoints):
        imaging[key] = {n: build_curve(samples_by[n], s0, max_res=caps[n])
                        for n in ACTIVE_ORDER}
        if key != SKIRT_DEFAULT_KEY:
            for curve in imaging[key].values():
                for p in curve:
                    p.pop("env_keys", None)
    heatmaps = {}
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
    pointsource = {n: build_curve(samples_by[n], max_res=caps[n])
                   for n in ACTIVE_ORDER}
    for curve in pointsource.values():
        for p in curve:
            p.pop("env_keys", None)

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
                heatmaps=heatmaps)

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
    data["sens"] = build_sens_table(las)

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
    data["combo"] = combo_entry(REV, SIM_MODE)
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


_REV_DISPLAY = {"revF": "Rev F", "revD": "Rev D"}
_REV_HTML = {"revF": "Rev&thinsp;F", "revD": "Rev&thinsp;D"}
_SIM_LABEL = {"track": "4 h track", "snapshot": "snapshot"}
_SIM_DESC_HTML = {"track": "4&thinsp;h track",
                  "snapshot": "single 60&thinsp;s snapshot at transit"}

# rendered under the header for snapshot combos (the 15 Jul 2026 diagnosis:
# the missing sub-natural branch is physics under the adopted convention, and
# fragmented LONG-family segments are honest coverage gaps)
_SNAPSHOT_NOTE_HTML = (
    "<strong>Snapshot mode:</strong> a single 60&thinsp;s monochromatic "
    "integration gives each baseline one uv sample, so on the density grid "
    "used by Briggs weighting here (set by the untapered image&rsquo;s "
    "imsize&thinsp;&times;&thinsp;cell) nearly every occupied uv cell holds "
    "&le;&thinsp;1 visibility and robust weighting has almost no lever "
    "&mdash; for sparse single-component subarrays (core, spiral, mid, "
    "core-inner, long) the curves legitimately <em>begin at &asymp; the "
    "natural-weighting beam</em> (verified on the untapered lattice rows, "
    "where the gridding convention is identical for every robust). Only "
    "composite subarrays, whose dense core cluster still multi-occupies uv "
    "cells, reach finer-than-natural beams. A real continuum snapshot has "
    "bandwidth + multi-dump uv filling that this monochromatic sim omits, "
    "so robust may recover some lever in practice (open control, PLAN.md). "
    "Snapshot beams are also strongly elongated (the geometric-mean "
    "resolution shown hides the axis ratio), and fragmented (dotted) "
    "LONG-family segments are rendered exactly as measured &mdash; "
    "consistent with sparse instantaneous uv coverage. "
    "Diagnosis 15 Jul 2026, PLAN.md.")

# the imaging-curve explanation shared by every combo's subtitle (matches the
# template's static paragraph)
_SUB_TAIL_HTML = (
    "The <em>imaging</em> curves constrain the PSF skirt &mdash; the "
    "azimuthally averaged PSF level at a radius of one FWHM (memo&thinsp;65 "
    "metric&thinsp;2b) &mdash; to a selectable threshold s<sub>0</sub> (10% "
    "by default, the memo&thinsp;121 criterion): at each resolution the "
    "cheapest (min-&eta;) beam meeting the criterion is shown, and where no "
    "beam can meet it the <em>best achievable</em> skirt is reported and "
    "flagged (hollow), never trading resolution away.")


def combo_entry(rev, sim_mode):
    """Dropdown metadata + per-combo header HTML for the combined report."""
    rev_html = _REV_HTML.get(rev, rev)
    snap = sim_mode == "snapshot"
    h1 = "%s %staperability &amp; sculptability curves" % (
        rev_html, "snapshot " if snap else "")
    sub = ("Sensitivity cost (&eta;, the image rms relative to natural "
           "weighting) versus achieved resolution at the 30&thinsp;GHz "
           "reference frequency, measured from noise simulations of each "
           "%s subarray (%s, dec&thinsp;+24&deg;) over a grid of Briggs "
           "robust and uv-taper values. %s"
           % (rev_html, _SIM_DESC_HTML.get(sim_mode, sim_mode),
              _SUB_TAIL_HTML))
    return dict(key="%s_%s" % (rev, sim_mode),
                label="%s — %s" % (_REV_DISPLAY.get(rev, rev),
                                   _SIM_LABEL.get(sim_mode, sim_mode)),
                h1_html=h1, sub_html=sub,
                note_html=_SNAPSHOT_NOTE_HTML if snap else "")


def build_combined(out_path):
    """The all-campaigns report: one payload per registered (rev, sim_mode)
    with curve data, each built by a SUBPROCESS running this script with that
    combo's environment (config freezes RESULTS_DIR / grid state at import,
    so a single process cannot build them all), injected together with a
    campaign dropdown the page uses to swap its contents."""
    import subprocess
    import tempfile

    reg = os.path.join(DATA_DIR, "config_registry.csv")
    with open(reg, newline="") as f:
        reg_rows = list(csv.DictReader(f))
    combos, payloads = [], {}
    for r in reg_rows:
        rev, mode = r["rev"].strip(), r["sim_mode"].strip()
        samples_csv = os.path.join(DATA_DIR, r["samples_csv"].strip())
        if not os.path.isfile(samples_csv) or os.path.getsize(samples_csv) < 100:
            print("combined: skipping %s/%s (no curve samples yet)"
                  % (rev, mode))
            continue
        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="payload_")
        os.close(fd)
        try:
            env = dict(os.environ, NGVLA_REV=rev, NGVLA_SIM_MODE=mode)
            subprocess.run(
                [sys.executable, os.path.abspath(__file__),
                 "--rev", rev, "--sim-mode", mode, "--payload-json", tmp],
                env=env, check=True)
            with open(tmp) as f:
                payload = json.load(f)
        finally:
            os.unlink(tmp)
        entry = combo_entry(rev, mode)
        combos.append(entry)
        payloads[entry["key"]] = payload
        print("combined: gathered %s/%s (%d subarrays)"
              % (rev, mode, len(payload.get("order", []))))
    if not combos:
        raise SystemExit("combined: no combo has curve data")
    # dropdown order per bmason: Rev F track, Rev F snapshot, Rev D track,
    # Rev D snapshot (rev first, track before snapshot; unknowns last)
    pref = ["revF_track", "revF_snapshot", "revD_track", "revD_snapshot"]
    combos.sort(key=lambda c: (pref.index(c["key"]) if c["key"] in pref
                               else len(pref), c["key"]))
    default = "revF_track" if "revF_track" in payloads else combos[0]["key"]
    data = dict(payloads=payloads, combos=combos, default=default)
    with open(TEMPLATE) as f:
        html = f.read()
    html = html.replace("__DATA__", json.dumps(data))
    html = html.replace("NGVLA Rev F subarray curves",
                        "NGVLA subarray curves — all campaigns")
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
    ap.add_argument("--payload-json", default=None, metavar="PATH",
                    help="write the combo's data payload as JSON instead of "
                         "an HTML report (used by --combined)")
    ap.add_argument("--combined", action="store_true",
                    help="build the all-campaigns report (one payload per "
                         "registered combo with data, campaign dropdown); "
                         "ignores --rev/--sim-mode/the environment")
    args = ap.parse_args()

    if args.combined:
        build_combined(args.out_path or "reports/ngvla-curves.html")
        sys.exit(0)

    # RESULTS_DIR (the heatmap source) is derived from the environment at
    # import time, so --rev/--sim-mode MUST agree with NGVLA_REV/NGVLA_SIM_MODE.
    # Refuse a mismatch rather than silently drawing another combo's heatmaps.
    if (args.rev, args.sim_mode) != (REV, SIM_MODE):
        ap.error("--rev/--sim-mode (%s/%s) disagree with the environment "
                 "(NGVLA_REV=%s NGVLA_SIM_MODE=%s); export those to match, so "
                 "RESULTS_DIR points at the right results dir"
                 % (args.rev, args.sim_mode, REV, SIM_MODE))

    is_default = (args.rev, args.sim_mode) == ("revF", "track")
    if not is_default:
        SUBARRAYS_CSV, CURVES_CSV = registry_paths(args.rev, args.sim_mode)
        ACTIVE_ORDER = offered_order(SUBARRAYS_CSV)
        label = "%s — %s" % (_REV_DISPLAY.get(args.rev, args.rev),
                                  args.sim_mode)
        default_out = "%s-%s-curves.html" % (args.rev.lower(), args.sim_mode)
    else:
        label = None
        default_out = "revf-curves.html"

    if args.payload_json:
        with open(args.payload_json, "w") as f:
            json.dump(build_payload(), f)
        print("wrote payload", args.payload_json)
        sys.exit(0)

    main(args.out_path or default_out, title_label=label)

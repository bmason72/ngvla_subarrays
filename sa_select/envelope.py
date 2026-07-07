"""
Shared curve engine: piecewise row interpolation of the (robust, taper)
lattice, used by BOTH the selector (`curves.CurveLibrary.solve`) and the
report (`curvegen/make_report.py`).  Introduced after the 6 Jul 2026
curve-anomaly post-mortem (`curve_anomaly_postmortem.md`): the previous
hard-window + hard-threshold + window-local-relaxation logic turned lattice
quantization into isolated pop-ups/drop-outs in the curves.

The model
---------
Sweep samples live on *rows*: one weighting/robust value per row, taper
varying.  Along a row, resolution, eta and skirt vary smoothly with taper, so
between two adjacent measured points we interpolate:

  * log(eta)  linearly in log(resolution)   (eta is multiplicative),
  * skirt     linearly in log(resolution)   (skirt can be ~0 or negative),
  * log(taper) likewise, so the reported tclean parameter is interpolated too.

Conservative rules (post-mortem + Codex review):
  * segments connect only ADJACENT-IN-TAPER samples, and only when the taper
    step and resolution step are lattice-like (no bridging pruned holes or
    isolated refinement points: MAX_TAPER_STEP / MAX_RES_STEP);
  * NO extrapolation past a row's ends (eta-cap, beam-cap and convergence
    prunes end rows for a reason);
  * one eta-cap policy (ETA_CAP) for every consumer;
  * hygiene at load: robust -0.0 -> 0.0, exact-duplicate lattice points
    dropped;
  * where the imaging threshold cannot be met, the relaxed criterion uses the
    best skirt achievable *from the interpolated families* at that resolution
    (continuous in resolution), never a per-window sample min;
  * interpolated answers say so, and carry their measured anchor points.

Queries
-------
`solve_at(theta)` evaluates the families exactly at a target resolution;
`solve(theta, margin)` minimizes over the beam-tolerance interval
[theta*(1-margin), theta*(1+margin)] (the interval endpoints and any measured
points inside it are the only possible minima of the piecewise-linear
interpolants, so the search is exact, not gridded).
"""

import math
from typing import Dict, List, Optional, Sequence, Tuple

ETA_CAP = 5.0          # curves/answers above this are not meaningful (policy)
RELAX_FACTOR = 1.15    # relaxed pool: skirt <= best_achievable * this
MAX_TAPER_STEP = 2.05  # max adjacent taper ratio a segment may span
MAX_RES_STEP = 1.6     # max adjacent resolution ratio a segment may span
ZERO_TAPER_RES_STEP = 1.3   # gate for the taper 0 -> first-taper segment
MAX_ROBUST_GAP = 0.45  # column segments only across lattice-adjacent rows
# Columns tolerate a larger resolution step than rows: a wide res span
# between lattice-adjacent robusts is genuine physics (the beam changes
# fastest with robust near 0 for the big-N arrays), not a pruned hole --
# every robust is measured at a given taper or deliberately dead.  Denser
# robust sampling (e.g. step 0.2 near 0) can shrink the interpolation span
# in a future campaign.
MAX_RES_STEP_COLUMN = 2.0

# The eta-skirt trade (bmason, 6 Jul 2026): where skirt <= skirt_max cannot
# be had cheaply, skirt and eta trade ONE FOR ONE over a span of TRADE_SPAN
# above the requested threshold -- i.e. the imaging objective is
# J = eta + TRADE_SLOPE * max(0, skirt - skirt_max), minimized over beams
# with skirt <= skirt_max + TRADE_SPAN (bmason's stated case: threshold 0.10
# trades up to 0.25).  A strict beam only wins if pushing the skirt below
# skirt_max costs less eta than the trade charges, which makes the imaging
# curve continuous where hard strict-first preference produced spikes
# (post-mortem addendum).  Beyond the trade cap the old best-achievable
# relaxation (flagged) is the fallback.
TRADE_SLOPE = 1.0
TRADE_SPAN = 0.15


# --------------------------------------------------------------------------- #
# data model


class Point:
    """One measured lattice sample, in whatever resolution unit the caller
    uses (the engine only ever compares resolutions to each other)."""

    __slots__ = ("res", "eta", "skirt", "weighting", "robust", "taper", "ref")

    def __init__(self, res, eta, skirt, weighting, robust, taper, ref=None):
        self.res = float(res)
        self.eta = float(eta)
        self.skirt = None if skirt is None else float(skirt)
        self.weighting = weighting
        self.robust = _canon_robust(weighting, robust)
        self.taper = 0.0 if taper is None else float(taper)
        self.ref = ref          # caller's original object (e.g. CurveSample)


class Choice:
    """An engine answer: an exact or interpolated (weighting, robust, taper)
    operating point.  `anchors` are the measured Points it interpolates
    between (one element = an actual measurement)."""

    __slots__ = ("res", "eta", "skirt", "weighting", "robust", "taper",
                 "anchors", "relaxed", "traded", "best_skirt")

    def __init__(self, res, eta, skirt, weighting, robust, taper, anchors,
                 relaxed=False, best_skirt=None):
        self.res, self.eta, self.skirt = res, eta, skirt
        self.weighting, self.robust, self.taper = weighting, robust, taper
        self.anchors = anchors
        self.relaxed = relaxed          # beyond TRADE_MAX: best-achievable
        self.traded = False             # skirt in (skirt_max, TRADE_MAX]
        self.best_skirt = best_skirt

    @property
    def interpolated(self):
        return len(self.anchors) == 2


def _canon_robust(weighting, robust):
    """Hygiene: natural rows have no robust; -0.0 and 0.0 are one branch."""
    if weighting == "natural":
        return None
    r = float(robust)
    return 0.0 if r == 0.0 else r    # folds -0.0 into 0.0


# --------------------------------------------------------------------------- #
# rows and segments


class Segment:
    """The interpolant between two measured points along ONE lattice axis:
    a ROW segment varies taper at fixed robust; a COLUMN segment varies
    robust at fixed taper (the 2-D densification that removes the discrete-
    robust staircase).  Together the row and column families cover, in
    resolution, everything a bilinear cell interior would (a bilinear
    surface attains its extrema on cell corners)."""

    __slots__ = ("a", "b", "lo", "hi", "column")

    def __init__(self, a: Point, b: Point, column=False):
        self.a, self.b = a, b
        self.lo = min(a.res, b.res)
        self.hi = max(a.res, b.res)
        self.column = column

    def covers(self, res):
        return self.lo <= res <= self.hi

    def _frac(self, res):
        """Position of `res` within the segment, in log-resolution."""
        if self.a.res == self.b.res:
            return 0.0
        return (math.log(res / self.a.res)
                / math.log(self.b.res / self.a.res))

    def at(self, res) -> Choice:
        """Interpolated operating point at resolution `res` (must be covered)."""
        u = self._frac(res)
        a, b = self.a, self.b
        eta = math.exp((1 - u) * math.log(a.eta) + u * math.log(b.eta))
        skirt = None
        if a.skirt is not None and b.skirt is not None:
            skirt = (1 - u) * a.skirt + u * b.skirt
        if self.column:
            # fixed taper, interpolated robust
            robust = (1 - u) * a.robust + u * b.robust
            return Choice(res, eta, skirt, a.weighting, round(robust, 3),
                          a.taper, (a, b))
        if a.taper > 0 and b.taper > 0:
            taper = math.exp((1 - u) * math.log(a.taper)
                             + u * math.log(b.taper))
        else:
            taper = (1 - u) * a.taper + u * b.taper
        return Choice(res, eta, skirt, a.weighting, a.robust, taper, (a, b))

    def skirt_measured(self):
        return self.a.skirt is not None and self.b.skirt is not None

    def skirt_crossings(self, threshold) -> List[float]:
        """Resolutions inside the segment where the interpolated skirt equals
        `threshold` (0 or 1 of them: skirt is linear in log-res here)."""
        if not self.skirt_measured():
            return []
        sa, sb = self.a.skirt, self.b.skirt
        if (sa - threshold) * (sb - threshold) >= 0:
            return []
        u = (threshold - sa) / (sb - sa)
        return [self.a.res * (self.b.res / self.a.res) ** u]


def build_points(samples: Sequence[dict], key=None) -> List[Point]:
    """Samples (mappings or objects with res/eta/skirt/weighting/robust/taper
    attributes) -> hygienic Point list: robust canonicalized, exact duplicate
    lattice points dropped (first kept), eta-cap applied."""
    pts, seen = [], set()
    for s in samples:
        get = s.get if isinstance(s, dict) else lambda k, _s=s: getattr(_s, k)
        ref = s["ref"] if isinstance(s, dict) and "ref" in s else s
        p = Point(get("res"), get("eta"), get("skirt"), get("weighting"),
                  get("robust"), get("taper"), ref=ref)
        if p.eta > ETA_CAP:
            continue
        k = (p.weighting, p.robust, round(p.taper, 6))
        if k in seen:
            continue
        seen.add(k)
        pts.append(p)
    return pts


def build_segments(points: Sequence[Point]) -> List[Segment]:
    """Group points into rows (weighting, robust), sort by taper, and connect
    adjacent pairs whose taper/resolution steps are lattice-like; then do the
    same along COLUMNS (fixed taper, adjacent Briggs robust values) so the
    envelope is continuous in the robust direction too."""
    rows: Dict[Tuple, List[Point]] = {}
    for p in points:
        rows.setdefault((p.weighting, p.robust), []).append(p)
    segments = []
    for row in rows.values():
        row.sort(key=lambda p: p.taper)
        for a, b in zip(row, row[1:]):
            if a.taper == 0:
                # untapered -> first taper: beams should barely differ
                if max(a.res, b.res) / min(a.res, b.res) > ZERO_TAPER_RES_STEP:
                    continue
            elif b.taper / a.taper > MAX_TAPER_STEP:
                continue        # pruned hole or isolated refinement point
            if max(a.res, b.res) / min(a.res, b.res) > MAX_RES_STEP:
                continue
            segments.append(Segment(a, b))

    # column segments: natural rows have no robust coordinate, so columns
    # connect Briggs rows only; the gap gate keeps interpolation between
    # lattice-adjacent rows (never across a missing/pruned row)
    cols: Dict[float, List[Point]] = {}
    for p in points:
        if p.weighting == "briggs":
            cols.setdefault(round(p.taper, 6), []).append(p)
    for col in cols.values():
        col.sort(key=lambda p: p.robust)
        for a, b in zip(col, col[1:]):
            if b.robust - a.robust > MAX_ROBUST_GAP:
                continue
            if max(a.res, b.res) / min(a.res, b.res) > MAX_RES_STEP_COLUMN:
                continue
            segments.append(Segment(a, b, column=True))
    return segments


# --------------------------------------------------------------------------- #
# the engine


class Envelope:
    """Interpolated curve families for ONE subarray's samples."""

    def __init__(self, samples: Sequence):
        self.points = build_points(samples)
        self.segments = build_segments(self.points)

    def coverage(self) -> Optional[Tuple[float, float]]:
        if not self.points:
            return None
        res = [p.res for p in self.points]
        return min(res), max(res)

    # -- candidate enumeration over a resolution interval ------------------- #

    def _candidates(self, lo, hi, skirt_max=None) -> List[Choice]:
        """Every possible minimum of eta (and of skirt) over [lo, hi]:
        measured points inside the interval, interval-edge crossings of each
        segment, and skirt-threshold crossings inside the interval.  Exact
        for piecewise-log-linear interpolants."""
        out = []
        for p in self.points:
            if lo <= p.res <= hi:
                if skirt_max is not None and (p.skirt is None
                                              or p.skirt > skirt_max):
                    continue
                out.append(Choice(p.res, p.eta, p.skirt, p.weighting,
                                  p.robust, p.taper, (p,)))
        for seg in self.segments:
            if skirt_max is not None and not seg.skirt_measured():
                continue
            edges = [r for r in (lo, hi) if seg.covers(r)]
            for r in edges:
                c = seg.at(r)
                if skirt_max is None or c.skirt <= skirt_max:
                    out.append(c)
            if skirt_max is not None:
                for r in seg.skirt_crossings(skirt_max):
                    if lo <= r <= hi:
                        out.append(seg.at(r))
        return out

    # -- queries ------------------------------------------------------------ #

    def _trade_stationary(self, seg, lo, hi, skirt_max, trade_max, slope):
        """Interior minima of J = eta + slope*(skirt - skirt_max) within one
        segment: eta is exp-linear and skirt linear in x = ln(res), so
        J'(x) = B*eta(x) + slope*D = 0 has the closed form eta(x*) =
        -slope*D/B.  Returns the corresponding Choices (0 or 1)."""
        if not seg.skirt_measured() or seg.a.res == seg.b.res:
            return []
        x0, x1 = math.log(seg.a.res), math.log(seg.b.res)
        B = (math.log(seg.b.eta) - math.log(seg.a.eta)) / (x1 - x0)
        D = (seg.b.skirt - seg.a.skirt) / (x1 - x0)
        if B == 0 or D == 0 or (-slope * D / B) <= 0:
            return []
        x_star = x0 + (math.log(-slope * D / B) - math.log(seg.a.eta)) / B
        # bounds-check in log space: near-flat eta rows put x_star far
        # outside the segment and exp() would overflow
        x_lo = math.log(max(lo, seg.lo))
        x_hi = math.log(min(hi, seg.hi))
        if not (x_lo <= x_star <= x_hi):
            return []
        res = math.exp(x_star)
        c = seg.at(res)
        # only meaningful on the penalized side of the objective
        if c.skirt is None or not (skirt_max < c.skirt <= trade_max):
            return []
        return [c]

    def solve(self, theta, margin=0.0, skirt_max=None, relax=True,
              trade_slope=TRADE_SLOPE, trade_max=None
              ) -> Optional[Choice]:
        """Cheapest way to reach resolution `theta` within +-margin.

        Point-source (skirt_max=None): minimum eta.

        Imaging (skirt_max given, relax=True): minimize the eta-skirt trade
        J = eta + trade_slope*max(0, skirt - skirt_max) over beams with
        skirt <= trade_max (bmason's 1-for-1 trade, 6 Jul 2026).  A beam
        with skirt above skirt_max that wins the trade has traded=True.
        If nothing has skirt <= trade_max, fall back to the best skirt
        achievable over the interval (relaxed=True, best_skirt set).

        relax=False: hard skirt <= skirt_max threshold, no trade.
        Returns None when the families give no answer in the interval.
        """
        lo, hi = theta * (1 - margin), theta * (1 + margin)
        if skirt_max is None or not relax:
            cands = self._candidates(lo, hi, skirt_max)
            return min(cands, key=lambda c: c.eta) if cands else None
        if trade_max is None:
            trade_max = skirt_max + TRADE_SPAN

        # the trade objective over skirt <= trade_max: possible minima are
        # measured points, interval edges, skirt crossings at trade_max
        # (feasibility edge) and at skirt_max (penalty kink), plus interior
        # stationary points of the penalized branch
        cands = self._candidates(lo, hi, trade_max)
        for seg in self.segments:
            for r in seg.skirt_crossings(skirt_max):
                if lo <= r <= hi:
                    cands.append(seg.at(r))
            cands.extend(self._trade_stationary(seg, lo, hi, skirt_max,
                                                trade_max, trade_slope))
        if cands:
            def J(c):
                return c.eta + trade_slope * max(0.0, c.skirt - skirt_max)
            choice = min(cands, key=J)
            choice.traded = choice.skirt > skirt_max + 1e-12
            return choice

        # nothing under trade_max: best achievable skirt over the interval
        # (continuous in theta), cheapest choice within RELAX_FACTOR of it
        with_skirt = [c for c in self._candidates(lo, hi)
                      if c.skirt is not None]
        if not with_skirt:
            return None
        best = min(c.skirt for c in with_skirt)
        pool = self._candidates(lo, hi, best * RELAX_FACTOR)
        if not pool:            # numerical edge: fall back to the best point
            pool = [min(with_skirt, key=lambda c: c.skirt)]
        choice = min(pool, key=lambda c: c.eta)
        choice.relaxed, choice.best_skirt = True, best
        return choice

    def curve(self, skirt_max=None, relax=True, grid_dex=0.01,
              margin=0.0) -> List[Choice]:
        """The full curve on a log grid of target resolutions (gaps where the
        families give no answer).  margin=0 evaluates the pure envelope."""
        cov = self.coverage()
        if cov is None:
            return []
        lo, hi = (math.log10(cov[0]), math.log10(cov[1]))
        out, x = [], lo
        while x <= hi + 1e-12:
            c = self.solve(10 ** x, margin=margin, skirt_max=skirt_max,
                           relax=relax)
            if c is not None:
                out.append(c)
            x += grid_dex
        return out

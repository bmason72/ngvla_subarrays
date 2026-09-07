"""
Shared curve engine: piecewise row interpolation of the (robust, taper)
lattice, used by BOTH the selector (`curves.CurveLibrary.solve`) and the
report (`curvegen/make_report.py`).  Introduced after the 6 Jul 2026
curve-anomaly post-mortem (`docs/postmortems/2026-07-06-curve-anomaly.md`): the previous
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
  * results are not eta-censored -- the engine reports what it finds at every
    resolution (ETA_CAP is a compute-grid/plotting bound only);
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

ETA_CAP = 5.0          # ~25x natural observing time: a compute-grid pruning
#                        and report-plotting bound only.  The engine/selector
#                        does NOT censor by it (bmason 8 Jul 2026); it is kept
#                        for `make_report`'s display trim and `config`'s sweep
#                        pruning.
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
# Threshold-relax default (bmason 8 Jul 2026): where skirt <= s0 is not
# achievable at a resolution, report the BEST achievable skirt (min-skirt),
# breaking ties in skirt by eta within this tolerance.  No relaxed-specific
# eta gate -- we report the best PSF found whatever the eta (the engine does
# not censor by ETA_CAP; that is a compute-grid / plotting notion only).
# (The retired 1-for-1 trade lives on only as mode="legacy_trade".)
SKIRT_TIE_TOL = 1e-6

# Bilinear cell interior (7 Jul 2026).  Row + column segments only sample the
# lattice EDGES; under the skirt constraint the cheapest beam at a target
# resolution can sit in a cell INTERIOR (both robust and taper between nodes)
# -- confirmed by probe measurements at robust +-0.6 that found admissible
# points (skirt 0.23-0.24, under the trade cap) cheaper than any edge.  A cell
# is the 2-D bilinear interpolant over four lattice-adjacent corner points
# {robust r0<r1} x {taper t0<t1}; log(res), log(eta) and skirt are bilinear in
# the normalized cell coordinates (s along robust, u along taper), which agrees
# EXACTLY with the row/column interpolants on all four edges and only adds
# interior operating points.  The engine enumerates the analytic critical
# points of the constrained problem along the fixed-resolution locus
# (eta-stationary, skirt-stationary, skirt=threshold crossings -- all closed-
# form quadratics) plus a deterministic scan+refine for the one transcendental
# case (the penalized eta+skirt stationary point), then validates each
# candidate by recomputing (res, skirt, eta).  See the 7 Jul 2026 design
# consult in docs/plans/PLAN.md sec.13 and tests/test_envelope.py::TestBilinearCells.
CELL_RES_TOL = 1e-6      # |log(res_candidate/theta)| tolerance for validation
CELL_SINGULAR = 1e-12    # |C + D s| below this is the iso-resolution singularity
CELL_DEGEN = 1e-12       # polynomial coefficient magnitude treated as zero
PENALIZED_SCAN_N = 25    # deterministic samples of the penalized branch per cell
PENALIZED_REFINE = 40    # golden-section iterations refining the scan minimum
VERT_SCAN = 64           # samples along an iso-resolution vertical cell branch
# When a query spans a +-margin beam window (the selector's default 5%), the
# cheapest cell interior can sit at a resolution INSIDE the band (e.g. riding
# the trade cap), not only at the band endpoints -- so we scan the band at
# this many log-spaced resolutions and evaluate the per-resolution-exact cell
# candidates at each (codex guard, 7 Jul 2026).  margin=0 (the report) stays a
# single exact evaluation.
CELL_BAND_SCAN = 32


# --------------------------------------------------------------------------- #
# data model


class Point:
    """One measured lattice sample, in whatever resolution unit the caller
    uses (the engine only ever compares resolutions to each other)."""

    __slots__ = ("res", "eta", "skirt", "weighting", "robust", "taper",
                 "capped", "ref")

    def __init__(self, res, eta, skirt, weighting, robust, taper, capped=False,
                 ref=None):
        self.res = float(res)
        self.eta = float(eta)
        self.skirt = None if skirt is None else float(skirt)
        self.weighting = weighting
        self.robust = _canon_robust(weighting, robust)
        self.taper = 0.0 if taper is None else float(taper)
        self.capped = bool(capped)
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
        # 2 anchors = a row/column edge interpolant; 4 = a bilinear cell
        # interior; 1 = an exact measured point.
        return len(self.anchors) >= 2


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


def build_points(samples: Sequence[dict]) -> List[Point]:
    """Samples (mappings or objects with res/eta/skirt/weighting/robust/taper
    attributes) -> hygienic Point list: robust canonicalized, exact duplicate
    lattice points dropped (first kept).  NO eta cap is applied here -- the
    engine reports what it finds at every resolution (bmason 8 Jul 2026: don't
    censor results; ETA_CAP is only a compute-grid / plotting notion)."""
    pts, seen = [], set()
    for s in samples:
        get = s.get if isinstance(s, dict) else lambda k, _s=s: getattr(_s, k)
        ref = s["ref"] if isinstance(s, dict) and "ref" in s else s
        if isinstance(s, dict):
            capped = bool(s.get("capped", False)
                          or s.get("sample_status") in ("capped",
                                                        "capped_anchor"))
        else:
            capped = getattr(s, "sample_status", "") in ("capped",
                                                           "capped_anchor")
        p = Point(get("res"), get("eta"), get("skirt"), get("weighting"),
                  get("robust"), get("taper"), capped=capped, ref=ref)
        k = (p.weighting, p.robust, round(p.taper, 6))
        if k in seen:
            continue
        seen.add(k)
        pts.append(p)
    return pts


def derive_robust_gap_limit(points: Sequence[Point]) -> float:
    """Per-table column-segment gap tolerance, derived from the measured
    Briggs robust values instead of hardcoding the mono 0.4 step (bmason D8,
    6 Sep 2026: MFS campaigns sample robust more densely, e.g. 0.2).

    Gaps are measured WITHIN each taper column separately (fixed taper,
    consecutive Briggs robusts at that exact taper), because the campaigns
    this engine reads from accumulate refinement unevenly: some taper
    columns get bisected by refine.py's secant targeting
    (curvegen/refine.py:secant_on_slice, which CAN write a probe at an
    off-grid robust bracketed between two adjacent lattice rows) while
    others keep the original, coarser lattice step.  A table-wide "smallest
    gap" or "smallest gap over the union of all tapers' robusts" is blind to
    this -- a single heavily-refined column can make the whole table look
    finer than an untouched column really is.  Pooling every column's own
    gaps and taking the 75th percentile recovers the campaign's NOMINAL
    lattice step even when a fraction of columns have been locally refined
    to a finer step (verified against the accumulated Rev F track table,
    where refine has densified some regions to 0.2/0.1 while others remain
    at the original 0.4: the pooled 75th percentile is exactly 0.4 for every
    subarray checked).  Falls back to MAX_ROBUST_GAP (the legacy constant)
    when fewer than two gap measurements exist (e.g. seeds only, or a
    single column with a single gap -- there is no statistic to recover a
    "nominal step" from one number, so the conservative legacy bound wins)."""
    cols: Dict[float, List[float]] = {}
    for p in points:
        if p.weighting == "briggs" and p.robust is not None:
            cols.setdefault(round(p.taper, 6), []).append(round(p.robust, 6))
    gaps = []
    for robs in cols.values():
        robs = sorted(set(robs))
        gaps.extend(round(b - a, 6) for a, b in zip(robs, robs[1:]))
    if len(gaps) < 2:
        return MAX_ROBUST_GAP
    gaps.sort()
    step = gaps[min(int(len(gaps) * 0.75), len(gaps) - 1)]
    return 1.125 * step


def build_segments(points: Sequence[Point],
                   gap_limit: float = MAX_ROBUST_GAP) -> List[Segment]:
    """Group points into rows (weighting, robust), sort by taper, and connect
    adjacent pairs whose taper/resolution steps are lattice-like; then do the
    same along COLUMNS (fixed taper, adjacent Briggs robust values) so the
    envelope is continuous in the robust direction too.  `gap_limit` is the
    max adjacent-robust spacing a column segment may span (see
    derive_robust_gap_limit); it defaults to the legacy constant for callers
    that do not derive it per-table."""
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
            if b.robust - a.robust > gap_limit:
                continue
            if max(a.res, b.res) / min(a.res, b.res) > MAX_RES_STEP_COLUMN:
                continue
            segments.append(Segment(a, b, column=True))
    return segments


# --------------------------------------------------------------------------- #
# bilinear cells (the 2-D interior between four lattice-adjacent corners)


def _quad_roots(a, b, c):
    """Real roots of a*x^2 + b*x + c = 0, with linear and degenerate fallbacks.
    A near-zero discriminant is treated as a tangent (one double root) so the
    skirt-contour tangency case is not silently dropped."""
    if abs(a) <= CELL_DEGEN:
        if abs(b) <= CELL_DEGEN:
            return []
        return [-c / b]
    disc = b * b - 4 * a * c
    if disc < 0:
        return [-b / (2 * a)] if disc > -CELL_DEGEN else []
    sq = math.sqrt(disc)
    return [(-b + sq) / (2 * a), (-b - sq) / (2 * a)]


class Cell:
    """Bilinear interpolant over four lattice-adjacent corner Points forming a
    (robust r0<r1) x (taper t0<t1) rectangle.  Normalized cell coordinates
    (s in [0,1] along robust, u in [0,1] along taper); log(res), log(eta) and
    skirt are each bilinear in (s,u):

        F(s,u) = F00 + (F10-F00) s + (F01-F00) u + (F00-F10-F01+F11) s u

    This agrees EXACTLY with the row and column edge interpolants on all four
    edges (on s=0 both x and e are affine in u, so e is linear in x = the row
    interpolant; likewise the other edges), so a cell only ADDS interior
    operating points.  At a target resolution theta the feasible set is the
    1-D locus {x(s,u)=log theta}; along it the constrained optimum's critical
    points (eta-stationary, skirt-stationary, skirt=level crossings) are
    closed-form quadratics, and the one transcendental case (the penalized
    eta+skirt stationary point) is found by a deterministic scan + refine."""

    __slots__ = ("p00", "p10", "p01", "p11", "r0", "r1", "t0", "t1",
                 "A", "B", "C", "D", "Ae", "Be", "Ce", "De",
                 "Ak", "Bk", "Ck", "Dk", "skirt_ok", "_rlo", "_rhi")

    def __init__(self, p00, p10, p01, p11):
        # corners: p00=(r0,t0)  p10=(r1,t0)  p01=(r0,t1)  p11=(r1,t1)
        self.p00, self.p10, self.p01, self.p11 = p00, p10, p01, p11
        self.r0, self.r1 = p00.robust, p10.robust
        self.t0, self.t1 = p00.taper, p01.taper
        x00, x10 = math.log(p00.res), math.log(p10.res)
        x01, x11 = math.log(p01.res), math.log(p11.res)
        self.A, self.B, self.C = x00, x10 - x00, x01 - x00
        self.D = x00 - x10 - x01 + x11
        e00, e10 = math.log(p00.eta), math.log(p10.eta)
        e01, e11 = math.log(p01.eta), math.log(p11.eta)
        self.Ae, self.Be, self.Ce = e00, e10 - e00, e01 - e00
        self.De = e00 - e10 - e01 + e11
        self.skirt_ok = all(p.skirt is not None
                            for p in (p00, p10, p01, p11))
        if self.skirt_ok:
            k00, k10, k01, k11 = (p00.skirt, p10.skirt, p01.skirt, p11.skirt)
            self.Ak, self.Bk, self.Ck = k00, k10 - k00, k01 - k00
            self.Dk = k00 - k10 - k01 + k11
        else:
            self.Ak = self.Bk = self.Ck = self.Dk = None
        rr = [p.res for p in (p00, p10, p01, p11)]
        # a bilinear surface attains its extrema on the corners, so the cell's
        # resolution range is exactly the corner range -- a valid quick reject
        self._rlo, self._rhi = min(rr), max(rr)

    def brackets(self, lo, hi):
        return self._rhi >= lo and self._rlo <= hi

    def _u_of_s(self, s, xstar):
        denom = self.C + self.D * s
        if abs(denom) < CELL_SINGULAR:
            return None                    # iso-resolution singularity
        return (xstar - self.A - self.B * s) / denom

    def _skirt(self, s, u):
        return self.Ak + self.Bk * s + self.Ck * u + self.Dk * s * u

    def _point(self, s, u):
        """Validated Choice at explicit normalized (s, u) (Codex Q4: recompute
        (res, eta, skirt) and check every candidate).  None if out of the cell
        or eta-capped."""
        if not (0.0 <= s <= 1.0 and 0.0 <= u <= 1.0):
            return None
        eta = math.exp(self.Ae + self.Be * s + self.Ce * u + self.De * s * u)
        if not math.isfinite(eta):
            return None
        x = self.A + self.B * s + self.C * u + self.D * s * u
        skirt = self._skirt(s, u) if self.skirt_ok else None
        robust = round(self.r0 + (self.r1 - self.r0) * s, 3)
        if self.t0 > 0 and self.t1 > 0:
            taper = math.exp((1 - u) * math.log(self.t0)
                             + u * math.log(self.t1))
        else:
            taper = (1 - u) * self.t0 + u * self.t1
        return Choice(math.exp(x), eta, skirt, "briggs", robust, taper,
                      (self.p00, self.p10, self.p01, self.p11))

    def _make(self, s, xstar):
        """Validated Choice on the res=theta locus, i.e. at (s, u(s))."""
        if not (0.0 <= s <= 1.0):
            return None
        u = self._u_of_s(s, xstar)
        if u is None:
            return None
        c = self._point(s, u)
        if c is None:
            return None
        if abs(math.log(c.res) - xstar) > CELL_RES_TOL * max(1.0, abs(xstar)):
            return None
        return c

    def _valid_intervals(self, xstar):
        """Sub-intervals of s in [0,1] where u(s) in [0,1] and the sign of
        (C+D s) does not flip (no singularity crossing).  Used to scan the
        penalized branch (Codex Q4: split at the singularity)."""
        breaks = {0.0, 1.0}
        if abs(self.D) > CELL_DEGEN:              # singularity C + D s = 0
            breaks.add(-self.C / self.D)
        if abs(self.B) > CELL_DEGEN:              # u(s) = 0
            breaks.add((xstar - self.A) / self.B)
        bd = self.B + self.D
        if abs(bd) > CELL_DEGEN:                  # u(s) = 1
            breaks.add((xstar - self.A - self.C) / bd)
        pts = sorted(b for b in breaks if 0.0 <= b <= 1.0)
        intervals = []
        for a, b in zip(pts, pts[1:]):
            if b - a < 1e-9:
                continue
            u = self._u_of_s(0.5 * (a + b), xstar)
            if u is not None and 0.0 <= u <= 1.0:
                intervals.append((a, b))
        return intervals

    def interior_candidates(self, theta, cap=None, skirt_kink=None,
                            slope=TRADE_SLOPE):
        """Interior operating points on the res=theta locus that can be the
        constrained minimum.  Emits eta-stationary points always; if the cell
        has skirt at all corners, also skirt-stationary points (for relaxed
        best-achievable skirt), skirt=cap / skirt=skirt_kink crossings, and --
        when both cap and skirt_kink are given -- the penalized-branch min.
        Callers filter by their own skirt cap; every point is validated."""
        if theta < self._rlo * (1 - 1e-9) or theta > self._rhi * (1 + 1e-9):
            return []
        xstar = math.log(theta)
        out = []

        def add(s):
            c = self._make(s, xstar)
            if c is not None:
                out.append(c)

        L = xstar - self.A
        # eta-stationary: alpha D s^2 + 2 alpha C s + (beta C - gamma D) = 0
        alpha = self.Be * self.D - self.De * self.B
        beta = self.Ae * self.D + self.Be * self.C + self.De * L - self.Ce * self.B
        gamma = self.Ae * self.C + self.Ce * L
        for s in _quad_roots(alpha * self.D, 2 * alpha * self.C,
                             beta * self.C - gamma * self.D):
            add(s)

        if self.skirt_ok:
            alphak = self.Bk * self.D - self.Dk * self.B
            betak = (self.Ak * self.D + self.Bk * self.C
                     + self.Dk * L - self.Ck * self.B)
            gammak = self.Ak * self.C + self.Ck * L
            # skirt-stationary (best-achievable-skirt minima for relaxation)
            for s in _quad_roots(alphak * self.D, 2 * alphak * self.C,
                                 betak * self.C - gammak * self.D):
                add(s)
            # skirt = level crossings (feasibility edge and trade kink)
            for lv in (cap, skirt_kink):
                if lv is None:
                    continue
                for s in _quad_roots(alphak, betak - lv * self.D,
                                     gammak - lv * self.C):
                    add(s)
            # penalized-branch stationary point (transcendental -> numeric)
            if cap is not None and skirt_kink is not None:
                self._penalized_min(xstar, cap, skirt_kink, slope, out)

        # iso-resolution vertical branch (Codex Q4/guard): when the singular
        # column s0 = -C/D lies in the cell AND the locus numerator vanishes
        # there, the whole line s=s0 is at res=theta -- the u(s) parametrization
        # misses it.  Sample it directly along u.
        if abs(self.D) > CELL_DEGEN:
            s0 = -self.C / self.D
            if (0.0 <= s0 <= 1.0
                    and abs(xstar - self.A - self.B * s0)
                    <= CELL_RES_TOL * max(1.0, abs(xstar))):
                for i in range(VERT_SCAN + 1):
                    c = self._point(s0, i / VERT_SCAN)
                    if c is not None:
                        out.append(c)
        return out

    def _penalized_min(self, xstar, cap, skirt_kink, slope, out):
        """Minimize J = eta + slope*max(0, skirt-skirt_kink) along the locus
        where skirt is in (skirt_kink, cap] (the traded regime).  Deterministic
        scan then golden-section refine around the best sample (Codex Q5: do
        not assume unimodality globally; refine locally around a scanned low)."""
        def Jval(s):
            c = self._make(s, xstar)
            if c is None or c.skirt is None:
                return None
            if not (skirt_kink - 1e-12 < c.skirt <= cap + 1e-12):
                return None
            return c.eta + slope * max(0.0, c.skirt - skirt_kink)

        for a, b in self._valid_intervals(xstar):
            best_s, best_j, step = None, None, (b - a) / PENALIZED_SCAN_N
            for i in range(PENALIZED_SCAN_N + 1):
                s = a + step * i
                j = Jval(s)
                if j is not None and (best_j is None or j < best_j):
                    best_j, best_s = j, s
            if best_s is None:
                continue
            lo, hi = max(a, best_s - step), min(b, best_s + step)
            phi = 0.5 * (math.sqrt(5) - 1)
            c1, c2 = hi - phi * (hi - lo), lo + phi * (hi - lo)
            for _ in range(PENALIZED_REFINE):
                j1, j2 = Jval(c1), Jval(c2)
                if j1 is None or j2 is None:
                    break
                if j1 < j2:
                    hi, c2 = c2, c1
                    c1 = hi - phi * (hi - lo)
                else:
                    lo, c1 = c1, c2
                    c2 = lo + phi * (hi - lo)
            add_s = 0.5 * (lo + hi)
            c = self._make(add_s, xstar)
            if c is not None:
                out.append(c)


def build_cells(points: Sequence[Point],
               gap_limit: float = MAX_ROBUST_GAP) -> List["Cell"]:
    """Bilinear cells from briggs points.  A cell spans (robust r0<r1) x
    (taper t0<t1) with all four corners measured.  To stay EXACTLY consistent
    with the 1-D row/column interpolants (so a cell can never undercut a more
    accurate edge fit), each of the four edges must be free of intervening
    measured points -- i.e. r0,r1 are consecutive among the robusts carrying
    taper t0 (and t1), and t0,t1 are consecutive among the tapers measured at
    robust r0 (and r1).  This handles the refined/probed lattice, where extra
    points along one row/column would otherwise make a naive corner grid
    inconsistent, and it keeps cells minimal (never bridging a measured node).
    The same lattice-step gates as the edge segments apply; natural rows have
    no robust coordinate and are excluded (as they are from columns)."""
    has: Dict[Tuple[float, float], Point] = {}
    tkey: Dict[float, float] = {}
    for p in points:
        if p.weighting != "briggs":
            continue
        tk = round(p.taper, 6)
        has.setdefault((p.robust, tk), p)            # dupes already dropped
        tkey.setdefault(tk, p.taper)
    robusts = sorted({r for r, _ in has})
    tapers_of = {r: sorted(tk for (rr, tk) in has if rr == r)
                 for r in robusts}
    robusts_of: Dict[float, List[float]] = {}
    for (r, tk) in has:
        robusts_of.setdefault(tk, []).append(r)
    for tk in robusts_of:
        robusts_of[tk].sort()

    cells = []
    for i, r0 in enumerate(robusts):
        for r1 in robusts[i + 1:]:
            if r1 - r0 > gap_limit:
                break                                # robusts are sorted
            shared = sorted(set(tapers_of[r0]) & set(tapers_of[r1]))
            for t0, t1 in zip(shared, shared[1:]):
                a0, a1 = tkey[t0], tkey[t1]
                if a0 > 0.0 and a1 / a0 > MAX_TAPER_STEP:
                    continue                          # pruned-hole taper step
                # edge cleanliness: no measured point interior to any edge
                if (any(t0 < tt < t1 for tt in tapers_of[r0])
                        or any(t0 < tt < t1 for tt in tapers_of[r1])):
                    continue                          # a row edge is not clean
                if (any(r0 < rr < r1 for rr in robusts_of[t0])
                        or any(r0 < rr < r1 for rr in robusts_of[t1])):
                    continue                          # a column edge is not clean
                p00, p10 = has[(r0, t0)], has[(r1, t0)]
                p01, p11 = has[(r0, t1)], has[(r1, t1)]
                zt = ZERO_TAPER_RES_STEP if a0 == 0.0 else MAX_RES_STEP
                if (max(p00.res, p01.res) / min(p00.res, p01.res) > zt
                        or max(p10.res, p11.res) / min(p10.res, p11.res) > zt):
                    continue                          # taper-direction res step
                if (max(p00.res, p10.res) / min(p00.res, p10.res)
                        > MAX_RES_STEP_COLUMN
                        or max(p01.res, p11.res) / min(p01.res, p11.res)
                        > MAX_RES_STEP_COLUMN):
                    continue                          # robust-direction res step
                cells.append(Cell(p00, p10, p01, p11))
    return cells


def _leaf_attr(leaf, name, default=None):
    return leaf.get(name, default) if isinstance(leaf, dict) \
        else getattr(leaf, name, default)


def build_leaf_families(points: Sequence[Point], leaves: Sequence,
                        gap_limit: float = MAX_ROBUST_GAP
                        ) -> Tuple[List[Segment], List["Cell"]]:
    """Build adaptive leaf edges and bilinear interiors.

    ``leaves`` is a sequence of objects/mappings carrying ``r0,r1,t0,t1`` and
    an optional truthy ``cut`` flag.  Unlike :func:`build_cells`, topology is
    supplied explicitly: non-dyadic auxiliary points may split a leaf edge
    into consecutive segments (hanging-node registration), but can never
    become cell corners.  Cut leaves contribute their measured edges only and
    no interior bilinear interpolation.  Capped points are resolution-censored
    and therefore cannot define an adaptive edge or cell.

    Natural-row and taper-zero seam families retain the established regular
    segment rules; they are outside the positive-taper quadtree.
    """
    usable = [p for p in points if not p.capped]
    by_key = {(round(p.robust, 6), round(p.taper, 6)): p for p in usable
              if p.weighting == "briggs" and p.robust is not None}

    # Preserve only the 1-D families outside the adaptive domain from the
    # regular enumerator.  Positive-taper Briggs edges are reconstructed below
    # from the explicit leaves.
    segments = [s for s in build_segments(usable, gap_limit)
                if s.a.weighting == "natural"
                or (s.a.weighting == "briggs"
                    and (s.a.taper == 0.0 or s.b.taper == 0.0))]
    seg_seen = set()
    for s in segments:
        ka = (s.a.weighting, s.a.robust, round(s.a.taper, 6))
        kb = (s.b.weighting, s.b.robust, round(s.b.taper, 6))
        seg_seen.add(tuple(sorted((ka, kb), key=repr)))

    cells = []

    def add_edge(edge_points, column):
        edge_points = sorted(edge_points,
                             key=(lambda p: p.robust) if column
                             else (lambda p: p.taper))
        for a, b in zip(edge_points, edge_points[1:]):
            if column:
                if b.robust - a.robust > gap_limit:
                    continue
                limit = MAX_RES_STEP_COLUMN
            else:
                if a.taper == 0.0:
                    limit = ZERO_TAPER_RES_STEP
                else:
                    if b.taper / a.taper > MAX_TAPER_STEP:
                        continue
                    limit = MAX_RES_STEP
            if max(a.res, b.res) / min(a.res, b.res) > limit:
                continue
            ka = (a.weighting, a.robust, round(a.taper, 6))
            kb = (b.weighting, b.robust, round(b.taper, 6))
            skey = tuple(sorted((ka, kb), key=repr))
            if skey not in seg_seen:
                segments.append(Segment(a, b, column=column))
                seg_seen.add(skey)

    for leaf in leaves:
        r0, r1 = float(_leaf_attr(leaf, "r0")), float(_leaf_attr(leaf, "r1"))
        t0, t1 = float(_leaf_attr(leaf, "t0")), float(_leaf_attr(leaf, "t1"))
        tol = 5e-7
        # Every measured point on an edge participates, so a fine neighbor's
        # hanging node automatically divides the coarser edge into segments.
        for tp in (t0, t1):
            add_edge([p for p in usable if p.weighting == "briggs"
                      and abs(p.taper - tp) <= tol
                      and r0 - tol <= p.robust <= r1 + tol], column=True)
        for rb in (r0, r1):
            add_edge([p for p in usable if p.weighting == "briggs"
                      and abs(p.robust - rb) <= tol
                      and t0 - tol <= p.taper <= t1 + tol], column=False)

        corners = [by_key.get((round(r, 6), round(t, 6)))
                   for r, t in ((r0, t0), (r1, t0), (r0, t1), (r1, t1))]
        if not _leaf_attr(leaf, "cut", False) and all(corners):
            cells.append(Cell(*corners))
    return segments, cells


# --------------------------------------------------------------------------- #
# the engine


class Envelope:
    """Interpolated curve families for ONE subarray's samples."""

    def __init__(self, samples: Sequence, leaves: Optional[Sequence] = None):
        self.points = build_points(samples)
        # Per-table (per-subarray) robust-gap tolerance: this ONE subarray's
        # samples dictate its own campaign's robust step (see
        # derive_robust_gap_limit), so a mono table's 0.4 step and a denser
        # MFS table's 0.2 step each get the right tolerance.
        self.gap_limit = derive_robust_gap_limit(self.points)
        if leaves is None:
            self.segments = build_segments(self.points, self.gap_limit)
            self.cells = build_cells(self.points, self.gap_limit)
        else:
            self.segments, self.cells = build_leaf_families(
                self.points, leaves, self.gap_limit)

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
        out.extend(self._cell_candidates(lo, hi, cap=skirt_max))
        return out

    def _cell_candidates(self, lo, hi, cap=None, skirt_kink=None,
                         slope=TRADE_SLOPE) -> List[Choice]:
        """Interior (bilinear-cell) candidates over [lo, hi], evaluated on the
        res=lo and res=hi loci.  `cap` filters by the skirt feasibility ceiling
        (None = point-source, keep all); `skirt_kink` additionally requests the
        trade-kink crossings and penalized-branch minimum.  See the Cell class.
        Over a +-margin band the cheapest interior can sit at a resolution
        INSIDE the band (codex guard), so the band is scanned at CELL_BAND_SCAN
        log-spaced resolutions and the per-resolution-exact cell candidates are
        unioned; margin=0 (the report) stays a single exact evaluation.  The
        scan min converges monotonically to the true band min and is validated
        against a 2-D band oracle in the tests."""
        out = []
        if lo == hi:
            thetas = (lo,)
        else:
            xlo, xhi = math.log(lo), math.log(hi)
            thetas = [math.exp(xlo + (xhi - xlo) * i / CELL_BAND_SCAN)
                      for i in range(CELL_BAND_SCAN + 1)]
        for cell in self.cells:
            if not cell.brackets(lo, hi):
                continue
            for theta in thetas:
                for c in cell.interior_candidates(theta, cap, skirt_kink,
                                                  slope):
                    if cap is not None and (c.skirt is None
                                            or c.skirt > cap + 1e-12):
                        continue
                    out.append(c)
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
              mode="threshold", trade_slope=TRADE_SLOPE, trade_max=None,
              max_res=None) -> Optional[Choice]:
        """Cheapest way to reach resolution `theta` within +-margin.

        `max_res` (the heterogeneous beam cap, 9 Jul 2026): samples measured
        beyond the cap are carried as interpolation ANCHORS (they extend row
        coverage up to the cap) but must never be OFFERED -- the beam-margin
        window is intersected with [.., max_res].  A window entirely beyond
        the cap returns None (the caller states the cap-specific reason).

        Point-source (skirt_max=None): minimum eta.

        Imaging (skirt_max = s0 given), mode="threshold" (DEFAULT, bmason
        8 Jul 2026): resolution is the hard requirement, skirt is a quality
        target.
          * STRICT -- if any beam in the window has skirt <= s0, return the
            cheapest (min-eta) of those.  It MEETS the criterion (relaxed
            False).
          * RELAXED -- otherwise return the beam with the BEST ACHIEVABLE
            skirt in the window (min-skirt; ties broken by eta), flagged
            relaxed=True with best_skirt set.  No skirt or eta limit is
            imposed -- we report the best PSF we can find at that resolution
            whatever the eta (which is reported; the caller judges).  This is
            distinct from the point-source curve, which returns the min-eta /
            worst-PSF beam.
          relax=False makes the threshold hard (strict only, else None).

        mode="legacy_trade": the retired 1-for-1 eta-skirt trade
        (J = eta + trade_slope*max(0, skirt - s0) over skirt <= trade_max),
        kept for diagnostics/comparison only.

        Returns None when the families give no answer in the interval.
        """
        lo, hi = theta * (1 - margin), theta * (1 + margin)
        if max_res is not None:
            if lo > max_res:
                return None            # whole window beyond the beam cap
            hi = min(hi, max_res)
        return self.solve_interval(lo, hi, skirt_max=skirt_max, relax=relax,
                                   mode=mode, trade_slope=trade_slope,
                                   trade_max=trade_max)

    def solve_interval(self, lo, hi, skirt_max=None, relax=True,
                       mode="threshold", trade_slope=TRADE_SLOPE,
                       trade_max=None) -> Optional[Choice]:
        """solve() over an explicit (possibly cap-clipped, asymmetric)
        resolution interval [lo, hi]; see solve() for the policy."""
        if skirt_max is None:
            cands = self._candidates(lo, hi, None)
            return min(cands, key=lambda c: c.eta) if cands else None
        if mode == "legacy_trade" and relax:
            return self._solve_trade(lo, hi, skirt_max, trade_slope, trade_max)

        # strict: the cheapest beam that meets skirt <= s0
        strict = self._candidates(lo, hi, skirt_max)
        if strict:
            return min(strict, key=lambda c: c.eta)     # meets the criterion
        if not relax:
            return None                                 # hard threshold

        # relaxed: the best achievable skirt in the window (no eta gate)
        with_skirt = [c for c in self._candidates(lo, hi, None)
                      if c.skirt is not None]
        if not with_skirt:
            return None                                 # genuine coverage gap
        best = min(c.skirt for c in with_skirt)
        pool = [c for c in with_skirt if c.skirt <= best + SKIRT_TIE_TOL]
        choice = min(pool, key=lambda c: c.eta)         # min-skirt, tie by eta
        choice.relaxed, choice.best_skirt = True, best
        return choice

    def _solve_trade(self, lo, hi, skirt_max, trade_slope, trade_max):
        """Retired 1-for-1 eta-skirt trade (mode='legacy_trade'); see solve."""
        if trade_max is None:
            trade_max = skirt_max + TRADE_SPAN
        cands = self._candidates(lo, hi, trade_max)
        for seg in self.segments:
            for r in seg.skirt_crossings(skirt_max):
                if lo <= r <= hi:
                    cands.append(seg.at(r))
            cands.extend(self._trade_stationary(seg, lo, hi, skirt_max,
                                                trade_max, trade_slope))
        cands.extend(self._cell_candidates(lo, hi, cap=trade_max,
                                           skirt_kink=skirt_max,
                                           slope=trade_slope))
        if cands:
            def J(c):
                return c.eta + trade_slope * max(0.0, c.skirt - skirt_max)
            choice = min(cands, key=J)
            choice.traded = choice.skirt > skirt_max + 1e-12
            return choice
        with_skirt = [c for c in self._candidates(lo, hi)
                      if c.skirt is not None]
        if not with_skirt:
            return None
        best = min(c.skirt for c in with_skirt)
        pool = self._candidates(lo, hi, best * RELAX_FACTOR)
        if not pool:
            pool = [min(with_skirt, key=lambda c: c.skirt)]
        choice = min(pool, key=lambda c: c.eta)
        choice.relaxed, choice.best_skirt = True, best
        return choice

    def curve(self, skirt_max=None, relax=True, grid_dex=0.01,
              margin=0.0, mode="threshold", max_res=None) -> List[Choice]:
        """The full curve on a log grid of target resolutions (gaps where the
        families give no answer).  margin=0 evaluates the pure envelope.

        `max_res` clips the emitted curve at the heterogeneous beam cap:
        capped-anchor samples extend coverage past the cap, but the offered
        curve must end exactly there, so the grid is truncated and an exact
        endpoint at max_res is appended if the log grid missed it."""
        cov = self.coverage()
        if cov is None:
            return []
        cov_hi = cov[1] if max_res is None else min(cov[1], max_res)
        if cov_hi < cov[0]:
            return []
        lo, hi = (math.log10(cov[0]), math.log10(cov_hi))
        out, x = [], lo
        last_x = None
        while x <= hi + 1e-12:
            c = self.solve(10 ** x, margin=margin, skirt_max=skirt_max,
                           relax=relax, mode=mode, max_res=max_res)
            if c is not None:
                out.append(c)
            last_x = x
            x += grid_dex
        if last_x is not None and last_x < hi - 1e-12:
            c = self.solve(cov_hi, margin=margin, skirt_max=skirt_max,
                           relax=relax, mode=mode, max_res=max_res)
            if c is not None:
                out.append(c)
        return out

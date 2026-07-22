"""
MFS-2 adaptive sampler core (task 2b, phase 1 -- CASA-free planning library + CLI).

One-screen algorithm summary
----------------------------
The per-(subarray, combo) results CSV is the source of truth (`sweep.FIELDS`
schema, keyed by `sweep.point_key`).  This module derives -- deterministically,
with NO pickled state -- a 2:1-balanced quadtree over the normalized weighting
input plane and decides where to measure NEXT.  It plans; it does not measure
(the CASA driver is task 2e).

  * Coordinates:  u = (robust + 2)/4,  v = log10(t/t_min)/log10(t_max/t_min),
    with t_min = 0.3*res(robust=-2), t_max = 20*res(natural).  The taper=0
    seam column and the natural row are 1-D families glued to the edge and
    stay OUT of the quadtree (they keep the existing envelope.build_segments
    machinery; natural-as-robust-2.0 is a PROPOSAL convention only).

  * Seed:  fresh maps get the pinned 56-point seed (a 6-robust x 7-taper
    briggs grid = 30 seed leaves, plus the seam column and natural row).
    Retrofit maps take the coarsest dyadic grid whose vertices are exact hits
    (every-other of ROBUST_LIST x every-other of the canonical tapers); its
    first bisection lands on the skipped lattice points, so the certification
    warm start is nearly free.

  * Lifecycle (residual owned by the PARENT):  a refined leaf's 5-point
    stencil (center + 4 edge midpoints) is compared against the parent's
    bilinear prediction from its 4 corners; the tolerance-scaled L-infinity
    residual E_T decides whether the 4 children are CERTIFIED (E_T<1, no
    further tests) or ACTIVATED.  Restart reconstructs this exactly from the
    table by testing which stencils are complete.

  * Retirement is two-way:  by residual (E_T<1) OR by dominance (the leaf's
    optimistic eta cannot beat the per-contour envelope minimum by more than
    tau_eta).  Most of a real map retires by dominance, cheaply.

  * Features (recomputed, never stored):  the classifier labels leaves/edges
    {smooth, step, ridge, unresolved}; cut edges carry a bracketed crossing
    (localized with the ported E1 secant / E2 progressive log-midpoint logic)
    and a freeze test (the two rim-side limiting envelopes agree within
    tolerance).

  * The wave planner ranks active leaves by the loss
    L_T = w_goal*min(E_T,E_max)*sqrt(A_T) + lambda*A_T and admits WHOLE
    stencils (+ 2:1 balance closures) under the plan/audit caps, tie-broken by
    lexicographic point_key -- never a partial stencil.

Every rule and constant is pinned by MFS2_ADAPTIVE_SAMPLER_SPEC.md (the build
contract); read it for the derivations.  This file is meant to be read by an
astronomer: units and contracts are in the docstrings.

CLI (phase 1: --plan-only is the ONLY execution path):

    casapy adaptive.py <subarray> [--plan-only] [--budget N] [--waves N]
                       [--warm-start | --fresh]

Combo routing follows NGVLA_REV / NGVLA_SIM_MODE (via config) exactly as the
rest of curvegen; the map is read READ-ONLY.
"""

import argparse
import csv
import hashlib
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from config import (ROBUST_LIST, TAPER_LO_X, TAPER_HI_X, BEAM_CAP_ARCSEC,
                    RESULTS_DIR, REV, SIM_MODE, SUBARRAYS, grid_rows)
from sweep import point_key
from make_report import build_curve, sample_from_row
from sa_select.envelope import ETA_CAP
# reused verbatim from the refinement escalation ladder (shared semantics; see
# the attribution notes at each call site).  These are pure, stateless helpers.
from refine import progressive_log_midpoints, GAP_RATIO, RIM_DEX, SKIRT_MAX


# --------------------------------------------------------------------------- #
# Constants -- ALL manifest-pinned (spec "Constants", findings #2/#10/#11).

SPEC_VERSION = "MFS2-adaptive-sampler v2 (21 Jul 2026)"
CLASSIFIER_VERSION = "adaptive-classify-1"
LOSS_VERSION = "adaptive-loss-1"

# model vector m = (ln res, eta, skirt); tolerances tau, deadband kappa*sigma
TAU = (math.log(1.05), 0.1, 0.02)                 # (ln res, eta, skirt)
KAPPA = 2.0
SIGMA_DEFAULT = (0.005, 0.02, 0.005)              # (ln res, eta, skirt) jitter
TAU_ETA = TAU[1]

LAMBDA = 0.05                    # exploration floor (unit-free; inputs normalized)
E_MAX = 4.0                     # caps a step's residual in the loss
RETIRE_E = 1.0                  # residual retirement / certification threshold
DOMINANCE_MARGIN = 1.0          # (optimistic_eta - envelope_eta)/tau_eta > 1

W_GOAL_ON = 3.0                 # on/adjacent a deliverable locus or skirt band
W_GOAL_DEFAULT = 1.0
W_GOAL_DOMINATED = 0.25         # dominated cells after coverage (loss only)

B_MAX = 16                     # wave batch (stencils); shrinks to fit the cap
B_MIN = 8

SKIRT_BAND = (0.05, 0.20)       # skirt binding band (make_report.SKIRT_SETPOINTS)

# seed design (finding #2)
SEED_ROBUSTS = [round(ROBUST_LIST[i], 2) for i in range(0, len(ROBUST_LIST), 2)]
#   -> [-2.0, -1.2, -0.4, 0.4, 1.2, 2.0] (every-other of ROBUST_LIST)
N_SEED_TAPERS = 7               # fresh seed: 7 positive log-uniform taper levels
SEED_TOTAL_FRESH = 56           # pinned (spec seed table)
SEED_LEAVES_FRESH = 30          # 5 x 6

# budgets (evaluations; finding #2).  Fresh counts TOTAL incl. seed; retrofit
# counts NEW evals only (seed cost 0).
PLAN_FRESH, AUDIT_FRESH = 110, 140
PLAN_RETRO, AUDIT_RETRO = 40, 80

# step localization / freeze (finding #9): freeze when the crossed-axis bracket
# is localized to within one resolution bin (the d ln res <= ln 1.05 leg of the
# limiting-envelope test) AND the two rim-side envelopes agree in eta/skirt.
FREEZE_TAPER_RATIO = 1.05        # t_hi/t_lo bracket freeze (log-res one bin)
FREEZE_ROBUST_WIDTH = 0.10       # robust-axis bracket freeze width
LOCALIZE_K = 4                   # progressive log-midpoint levels per proposal

STENCIL_SIZE = 5


# scheduling states (finding #8, orthogonal to feature class)
UNTESTED = "untested"
ACTIVE = "active"
CONVERGED = "converged"          # retired-by-residual (certified)
DOMINATED = "dominated-retired"
FROZEN = "frozen"
BUDGET_STOPPED = "budget-stopped"

# feature classes (finding #8)
SMOOTH = "smooth"
STEP = "step"
RIDGE = "ridge"
UNRESOLVED = "unresolved"


def manifest():
    """The pinned inputs that make "same table -> same next wave" hold across
    software changes (finding #11).  Hashed into the CLI header for provenance."""
    return dict(
        spec=SPEC_VERSION, classifier=CLASSIFIER_VERSION, loss=LOSS_VERSION,
        tau=TAU, kappa=KAPPA, sigma=SIGMA_DEFAULT, lam=LAMBDA, e_max=E_MAX,
        retire_e=RETIRE_E, dominance=DOMINANCE_MARGIN,
        w_goal=(W_GOAL_ON, W_GOAL_DEFAULT, W_GOAL_DOMINATED),
        seed_robusts=SEED_ROBUSTS, n_seed_tapers=N_SEED_TAPERS,
        taper_lo_x=TAPER_LO_X, taper_hi_x=TAPER_HI_X,
        skirt_band=SKIRT_BAND, eta_cap=ETA_CAP, gap_ratio=GAP_RATIO,
        plan=(PLAN_FRESH, PLAN_RETRO), audit=(AUDIT_FRESH, AUDIT_RETRO),
        tie_break="lexicographic point_key")


def manifest_hash():
    return hashlib.sha256(repr(sorted(manifest().items())).encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# Coordinates and canonicalization (spec "Coordinates and the seam").

def robust_to_u(robust):
    """Normalized robust coordinate u in [0,1]."""
    return (float(robust) + 2.0) / 4.0


def u_to_robust(u):
    return 4.0 * float(u) - 2.0


def taper_to_v(taper, t_min, t_max):
    """Normalized taper coordinate v in [0,1] (log-uniform between t_min,t_max)."""
    return math.log10(float(taper) / t_min) / math.log10(t_max / t_min)


def v_to_taper(v, t_min, t_max):
    return t_min * (t_max / t_min) ** float(v)


def canon_rt(robust, taper):
    """(robust, taper) rounded to point_key precision, with -0.0 folded to 0.0
    exactly as sweep.point_key does, so a proposal round-trips to the same key."""
    r = round(float(robust), 2)
    t = round(float(taper), 3)
    if r == 0.0:
        r = 0.0
    if t == 0.0:
        t = 0.0
    return r + 0.0, t + 0.0


def key_rt(robust, taper):
    return point_key("briggs", float(robust), float(taper))


KEY_NAT = point_key("natural", 2.0, 0.0)
KEY_FINE = point_key("briggs", -2.0, 0.0)


def _mid_robust(r0, r1):
    """Midpoint on the u (robust) axis -- arithmetic mean (u is linear in r)."""
    return round((r0 + r1) / 2.0, 6)


def _mid_taper(t0, t1):
    """Midpoint on the v (taper) axis -- geometric mean (v is linear in log t).
    For an every-other log-uniform seed this lands exactly on the skipped
    canonical taper, so retrofit's first bisection is warm."""
    return math.sqrt(t0 * t1)


# --------------------------------------------------------------------------- #
# Point-table view (spec "Point table = source of truth"; finding #11).

class MVec:
    """The measured model vector m = (ln res, eta, skirt) of one point, plus
    the res-censoring flag for capped rows.  skirt may be None (unmeasured)."""

    __slots__ = ("lnres", "eta", "skirt", "capped", "res_mas")

    def __init__(self, lnres, eta, skirt, capped, res_mas):
        self.lnres, self.eta, self.skirt = lnres, eta, skirt
        self.capped, self.res_mas = capped, res_mas

    def __getitem__(self, k):
        return (self.lnres, self.eta, self.skirt)[k]


class PointTable:
    """The effective-row view of one (subarray, combo) results table.

    Effective-row rule (finding #11): the LAST `ok`|`capped` row per canonical
    point_key.  `failed` (and `skipped`) rows count only as "attempted" -- they
    are not effective evidence but they DO occupy the key (not re-proposed
    within a run).  Capped rows are res-censored: usable for eta/skirt residuals
    but their ln-res residual is skipped beyond the cap.

    Construct from a list of raw row dicts (sweep.FIELDS subset) in append
    order.  `PointTable.from_csv` reads the combo's results CSV read-only.
    """

    def __init__(self, rows, subarray=None, beam_cap_mas=None):
        self.subarray = subarray
        self.beam_cap_mas = beam_cap_mas
        self._all = set()          # every key present at any status (attempted)
        self._eff = {}             # key -> effective (last ok|capped) row
        self._n_failed = 0
        self._n_skipped = 0
        self._n_capped = 0
        for r in rows:
            try:
                key = point_key(r["weighting"], r["robust"], r["taper_mas"])
            except (KeyError, TypeError, ValueError):
                continue
            self._all.add(key)
            status = (r.get("status") or "").strip()
            if status in ("ok", "capped"):
                self._eff[key] = r        # last wins
        for r in self._eff.values():
            if (r.get("status") or "").strip() == "capped":
                self._n_capped += 1
        # attempted-but-not-effective tally (informational)
        for r in rows:
            status = (r.get("status") or "").strip()
            if status == "failed":
                self._n_failed += 1
            elif status == "skipped":
                self._n_skipped += 1
        # anchors + coordinate scale
        self._sigma_nat = None
        self.res_nat = self.res_fine = None
        self.t_min = self.t_max = None
        nat = self._eff.get(KEY_NAT)
        fine = self._eff.get(KEY_FINE)
        if nat is not None:
            try:
                self._sigma_nat = float(nat["sigma_dirty"])
                self.res_nat = float(nat["res_geo_arcsec"]) * 1e3
            except (TypeError, ValueError):
                pass
        if fine is not None:
            try:
                self.res_fine = float(fine["res_geo_arcsec"]) * 1e3
            except (TypeError, ValueError):
                pass
        if self.res_fine and self.res_nat:
            self.t_min = TAPER_LO_X * self.res_fine
            self.t_max = TAPER_HI_X * self.res_nat

    # -- construction -------------------------------------------------------- #
    @classmethod
    def from_csv(cls, path, subarray=None, beam_cap_mas=None):
        rows = []
        if os.path.isfile(path):
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
        return cls(rows, subarray=subarray, beam_cap_mas=beam_cap_mas)

    # -- membership ---------------------------------------------------------- #
    def hit(self, key):
        """True iff the key has an effective (ok|capped) row."""
        return key in self._eff

    def present(self, key):
        """True iff the key was attempted at any status (occupies the key)."""
        return key in self._all

    def hit_rt(self, robust, taper):
        return key_rt(robust, taper) in self._eff

    def row(self, key):
        return self._eff.get(key)

    @property
    def has_anchors(self):
        return (self._sigma_nat and self.res_fine and self.res_nat
                and self.t_min and self.t_max)

    @property
    def sigma_nat(self):
        return self._sigma_nat

    @property
    def n_effective(self):
        return len(self._eff)

    @property
    def n_attempted(self):
        return len(self._all)

    @property
    def n_failed(self):
        return self._n_failed

    @property
    def n_skipped(self):
        return self._n_skipped

    @property
    def n_capped(self):
        return self._n_capped

    # -- model vectors ------------------------------------------------------- #
    def mvec(self, key):
        """The MVec of an effective row (None if the key is not a hit)."""
        r = self._eff.get(key)
        if r is None:
            return None
        try:
            res_mas = float(r["res_geo_arcsec"]) * 1e3
            eta = float(r["sigma_dirty"]) / self._sigma_nat
        except (TypeError, ValueError, ZeroDivisionError):
            return None
        if not (res_mas > 0 and math.isfinite(eta)):
            return None
        skirt = None
        s = r.get("skirt")
        if s not in (None, ""):
            try:
                skirt = float(s)
            except (TypeError, ValueError):
                skirt = None
        capped = (r.get("status") or "").strip() == "capped"
        return MVec(math.log(res_mas), eta, skirt, capped, res_mas)

    def mvec_rt(self, robust, taper):
        return self.mvec(key_rt(robust, taper))

    # -- display-trimmed samples (shared contract with make_report/refine) --- #
    def display_samples(self):
        """ok+capped rows -> sample dicts (via make_report.sample_from_row),
        with the display-only `capped` flag popped -- exactly refine.samples_from
        so build_curve sees the curve the report would draw."""
        out = []
        for key, r in self._eff.items():
            mv = self.mvec(key)
            if mv is None:
                continue
            weighting = r["weighting"]
            robust = None if weighting == "natural" else float(r["robust"])
            s = sample_from_row(res_mas=mv.res_mas, eta=mv.eta, skirt=mv.skirt,
                                weighting=weighting, robust=robust,
                                taper_mas=float(r["taper_mas"]),
                                capped=mv.capped)
            if s is not None:
                s.pop("capped", None)
                out.append(s)
        return out

    # -- measured lattice geometry (retrofit seed derivation) ---------------- #
    def briggs_robusts(self):
        """Sorted distinct briggs robusts with at least one positive-taper hit."""
        rs = set()
        for r in self._eff.values():
            if r["weighting"] != "briggs":
                continue
            try:
                if float(r["taper_mas"]) > 0:
                    rs.add(round(float(r["robust"]), 2))
            except (TypeError, ValueError):
                continue
        return sorted(rs)

    def positive_tapers(self):
        """Sorted distinct positive taper levels present as briggs hits."""
        ts = set()
        for r in self._eff.values():
            if r["weighting"] != "briggs":
                continue
            try:
                t = round(float(r["taper_mas"]), 3)
            except (TypeError, ValueError):
                continue
            if t > 0:
                ts.add(t)
        return sorted(ts)


# --------------------------------------------------------------------------- #
# Bilinear prediction over a leaf's four corners (parent residual model).

def _bilinear(f00, f10, f01, f11, s, u):
    """F(s,u) = F00 + (F10-F00)s + (F01-F00)u + (F00-F10-F01+F11) s u.
    s runs along robust (the u-axis corner index), u along taper (v-axis)."""
    return f00 + (f10 - f00) * s + (f01 - f00) * u \
        + (f00 - f10 - f01 + f11) * s * u


# --------------------------------------------------------------------------- #
# Quadtree leaf.

class Leaf:
    """One rectangle in (robust, taper) with four measured corners.  Bounds are
    kept in parameter space (robust r0<r1, taper t0<t1); midpoints are computed
    drift-free (robust arithmetic mean, taper geometric mean).  A leaf is either
    an internal (refined) node with 4 children, or a terminal leaf whose
    scheduling state the certifier assigns."""

    __slots__ = ("r0", "r1", "t0", "t1", "depth", "children", "refined",
                 "E_T", "parent_E", "certified", "state", "feature", "cut",
                 "goal", "loss", "step_owner")

    def __init__(self, r0, r1, t0, t1, depth, parent_E=None, certified=False):
        self.r0, self.r1 = r0, r1
        self.t0, self.t1 = t0, t1
        self.depth = depth
        self.children = None
        self.refined = False
        self.E_T = None
        self.parent_E = parent_E
        self.certified = certified
        self.state = None
        self.feature = SMOOTH
        self.cut = None
        self.goal = False
        self.loss = 0.0
        self.step_owner = None      # nearest refined ancestor classified STEP

    # -- geometry ------------------------------------------------------------ #
    def corners(self):
        """(robust, taper) of p00, p10, p01, p11 (SW, SE, NW, NE)."""
        return ((self.r0, self.t0), (self.r1, self.t0),
                (self.r0, self.t1), (self.r1, self.t1))

    def stencil(self):
        """The 5 probe (robust, taper, s, u) with normalized cell coords (s,u):
        center then bottom/top/left/right edge midpoints."""
        rm, tm = _mid_robust(self.r0, self.r1), _mid_taper(self.t0, self.t1)
        return [(rm, tm, 0.5, 0.5),
                (rm, self.t0, 0.5, 0.0),
                (rm, self.t1, 0.5, 1.0),
                (self.r0, tm, 0.0, 0.5),
                (self.r1, tm, 1.0, 0.5)]

    def area(self, t_min, t_max):
        """A_T in the normalized (u,v) plane."""
        du = (self.r1 - self.r0) / 4.0
        dv = taper_to_v(self.t1, t_min, t_max) - taper_to_v(self.t0, t_min, t_max)
        return du * dv

    def make_children(self, child_E, certified):
        rm, tm = _mid_robust(self.r0, self.r1), _mid_taper(self.t0, self.t1)
        d = self.depth + 1
        self.children = [
            Leaf(self.r0, rm, self.t0, tm, d, child_E, certified),
            Leaf(rm, self.r1, self.t0, tm, d, child_E, certified),
            Leaf(self.r0, rm, tm, self.t1, d, child_E, certified),
            Leaf(rm, self.r1, tm, self.t1, d, child_E, certified),
        ]
        return self.children

    def sort_key(self):
        """Lexicographic tie-break key: the leaf's SW-corner point_key."""
        return key_rt(*canon_rt(self.r0, self.t0))


# --------------------------------------------------------------------------- #
# The quadtree over one point table.

class QuadTree:
    """Deterministic reconstruction of the 2:1-balanced quadtree from the point
    table (no pickled state).  Fresh mode builds the pinned seed; retrofit mode
    takes the coarsest all-hit dyadic grid.  `mode` may be forced, else it is
    auto-detected (empty -> fresh, populated -> retrofit)."""

    def __init__(self, table, mode=None):
        self.table = table
        self.mode = mode or self.detect_mode(table)
        self.seed_robusts, self.seed_tapers = self._seed_nodes()
        self.seed_leaves = self._build_seed_leaves()
        self._reconstruct()

    @staticmethod
    def detect_mode(table):
        # empty (no effective evidence) -> fresh seed; populated -> warm start
        return "fresh" if table.n_effective == 0 else "retrofit"

    # -- seed node axes ------------------------------------------------------ #
    def _seed_nodes(self):
        t = self.table
        if self.mode == "fresh":
            if not t.has_anchors:
                return SEED_ROBUSTS, []          # need the two anchors first
            tapers = [round(v_to_taper(k / (N_SEED_TAPERS - 1), t.t_min, t.t_max), 3)
                      for k in range(N_SEED_TAPERS)]
            return list(SEED_ROBUSTS), tapers
        # retrofit: every-other of ROBUST_LIST, every-other of the CANONICAL
        # sweep taper grid (config.grid_rows -- NOT the union of measured
        # tapers, which includes non-dyadic refine rows: those are auxiliary
        # evidence only, finding #5).  The coarsest all-hit dyadic grid; its
        # first bisection lands on the skipped canonical tapers -> usually warm.
        robusts = list(SEED_ROBUSTS)
        rows = grid_rows(t.res_fine, t.res_nat, self.table.subarray)
        canonical = [round(float(tp), 3) for tp in rows[0][2] if tp > 0]
        seed_t = canonical[::2]
        if canonical and canonical[-1] not in seed_t:
            seed_t.append(canonical[-1])         # force-include the coarsest rim
        return robusts, seed_t

    def _build_seed_leaves(self):
        leaves = []
        rs, ts = self.seed_robusts, self.seed_tapers
        for i in range(len(rs) - 1):
            for j in range(len(ts) - 1):
                leaves.append(Leaf(rs[i], rs[i + 1], ts[j], ts[j + 1], 0))
        return leaves

    @property
    def n_seed_leaves(self):
        return len(self.seed_leaves)

    # -- the 56-point fresh seed (spec seed table) --------------------------- #
    def seed_points(self):
        """The full seed as (weighting, robust, taper) triples.  For a fresh map
        with anchors this is exactly 56 (42 briggs grid + 6 seam + 8 natural);
        for retrofit it is the every-other grid + seam + natural (cost 0)."""
        rs, ts = self.seed_robusts, self.seed_tapers
        pts = []
        for r in rs:                                   # briggs grid
            for t in ts:
                pts.append(("briggs",) + canon_rt(r, t))
        for r in rs:                                   # untapered seam column
            pts.append(("briggs",) + canon_rt(r, 0.0))
        pts.append(("natural", 2.0, 0.0))              # natural row
        for t in ts:
            pts.append(("natural", 2.0, canon_rt(0.0, t)[1]))
        return pts

    def missing_seed_points(self):
        """Seed vertices not yet present in the table -> the wave-0 proposals.
        Empty for a complete (retrofit) lattice."""
        if self.mode == "fresh" and not self.table.has_anchors:
            # cannot place the taper grid until the two anchors are measured
            return [s for s in (("natural", 2.0, 0.0), ("briggs", -2.0, 0.0))
                    if not self.table.present(point_key(*s))]
        out = []
        for (w, r, t) in self.seed_points():
            if not self.table.present(point_key(w, r, t)):
                out.append((w, r, t))
        return out

    # -- reconstruction ------------------------------------------------------ #
    def _reconstruct(self):
        for leaf in self.seed_leaves:
            self._reconstruct_leaf(leaf)

    def _reconstruct_leaf(self, leaf):
        t = self.table
        corner_keys = [key_rt(*rt) for rt in leaf.corners()]
        if not all(t.hit(k) for k in corner_keys):
            leaf.refined = False               # incomplete: corners not all in
            return
        stencil = leaf.stencil()
        if not all(t.hit(key_rt(rp, tp)) for (rp, tp, _s, _u) in stencil):
            leaf.refined = False               # terminal (untested)
            return
        leaf.E_T = self._residual(leaf)
        leaf.refined = True
        child_cert = leaf.E_T < RETIRE_E
        for c in leaf.make_children(leaf.E_T, child_cert):
            self._reconstruct_leaf(c)

    def _residual(self, leaf):
        """E_T owned by this PARENT: L-infinity over its 5 stencil probes of the
        per-component tolerance-scaled deadbanded error vs the bilinear corner
        prediction (spec cell lifecycle step 2).  Capped probes are res-censored
        (ln-res component skipped)."""
        t = self.table
        cm = [t.mvec(key_rt(*rt)) for rt in leaf.corners()]  # p00,p10,p01,p11
        if any(m is None for m in cm):
            return E_MAX                        # cannot predict -> maximal doubt
        E = 0.0
        for (rp, tp, s, u) in leaf.stencil():
            mv = t.mvec(key_rt(rp, tp))
            if mv is None:
                return E_MAX
            for k in range(3):
                if k == 0 and mv.capped:
                    continue                    # res-censored beyond the cap
                meas = mv[k]
                c00, c10, c01, c11 = (cm[0][k], cm[1][k], cm[2][k], cm[3][k])
                if meas is None or None in (c00, c10, c01, c11):
                    continue                    # skirt unmeasured somewhere
                pred = _bilinear(c00, c10, c01, c11, s, u)
                r = (abs(meas - pred) - KAPPA * SIGMA_DEFAULT[k])
                if r > 0:
                    E = max(E, r / TAU[k])
        return E

    # -- traversal ----------------------------------------------------------- #
    def terminal_leaves(self):
        out = []

        def walk(leaf):
            if leaf.refined and leaf.children:
                for c in leaf.children:
                    walk(c)
            else:
                out.append(leaf)
        for leaf in self.seed_leaves:
            walk(leaf)
        return out

    def all_leaves(self):
        """Every node (internal + terminal) -- for neighbor/balance queries."""
        out = []

        def walk(leaf):
            out.append(leaf)
            if leaf.children:
                for c in leaf.children:
                    walk(c)
        for leaf in self.seed_leaves:
            walk(leaf)
        return out


# --------------------------------------------------------------------------- #
# A cheap piecewise-log-linear view of a build_curve() result, for dominance.

class _Envelope:
    """eta(res) view of a build_curve output (res in mas), gap-aware.  eta_at
    returns None outside the covered range OR inside an interior gap (a jump
    wider than GAP_RATIO between consecutive curve points).  This distinguishes
    the two "no envelope" cases the dominance rule must treat differently: the
    expensive tail beyond `coverage_max` (retire) vs a genuine interior gap
    (keep sampling)."""

    def __init__(self, curve):
        pts = sorted(((p["res"], p["eta"]) for p in curve), key=lambda pr: pr[0])
        self.xs = [math.log(r) for r, _ in pts]
        self.es = [e for _, e in pts]
        self.coverage_min = min((r for r, _ in pts), default=None)
        self.coverage_max = max((r for r, _ in pts), default=None)

    def eta_at(self, res):
        if not self.xs:
            return None
        x = math.log(res)
        if x < self.xs[0] - 1e-9 or x > self.xs[-1] + 1e-9:
            return None
        for k in range(len(self.xs) - 1):
            if self.xs[k] - 1e-12 <= x <= self.xs[k + 1] + 1e-12:
                x0, x1 = self.xs[k], self.xs[k + 1]
                if (x1 - x0) > math.log(GAP_RATIO):
                    return None                # inside an interior gap
                if x1 == x0:
                    return min(self.es[k], self.es[k + 1])
                w = (x - x0) / (x1 - x0)
                return self.es[k] + w * (self.es[k + 1] - self.es[k])
        return self.es[-1]

    def max_over_covered(self, lo, hi, n=6):
        """Max envelope eta over the COVERED part of [lo, hi] (skips gaps);
        None only if nothing in the interval is covered."""
        vals = []
        xlo, xhi = math.log(lo), math.log(hi)
        for i in range(n + 1):
            e = self.eta_at(math.exp(xlo + (xhi - xlo) * (i / n if n else 0)))
            if e is not None:
                vals.append(e)
        return max(vals) if vals else None

    def min_over(self, lo, hi, n=6):
        vals = []
        xlo, xhi = math.log(lo), math.log(hi)
        for i in range(n + 1):
            e = self.eta_at(math.exp(xlo + (xhi - xlo) * (i / n if n else 0)))
            if e is not None:
                vals.append(e)
        return min(vals) if vals else None

    def has_gap_in(self, lo, hi, n=6):
        """True iff some sampled point in [lo,hi] falls in an interior gap
        (covered range but no local curve)."""
        if self.coverage_min is None:
            return False
        xlo, xhi = math.log(lo), math.log(hi)
        for i in range(n + 1):
            r = math.exp(xlo + (xhi - xlo) * (i / n if n else 0))
            if self.coverage_min <= r <= self.coverage_max and self.eta_at(r) is None:
                return True
        return False


# --------------------------------------------------------------------------- #
# A classified cut / feature (recomputed, never stored).

class Cut:
    """A discontinuity localized on a leaf edge: the crossed axis ('taper' or
    'robust'), the bracketed crossing interval (lo,hi) in that axis's PARAMETER
    units, the fine/coarse resolutions across it, and the freeze flag."""

    __slots__ = ("axis", "fixed", "lo", "hi", "res_fine", "res_coarse",
                 "delta", "frozen")

    def __init__(self, axis, fixed, lo, hi, res_fine, res_coarse, delta, frozen):
        self.axis, self.fixed = axis, fixed
        self.lo, self.hi = lo, hi
        self.res_fine, self.res_coarse = res_fine, res_coarse
        self.delta, self.frozen = delta, frozen

    def mid_res_mas(self):
        return math.sqrt(self.res_fine * self.res_coarse)


# --------------------------------------------------------------------------- #
# Wave plan (the output of the planner).

class WavePlan:
    """The next wave: `proposals` is a deterministic, lexicographically sorted
    list of (weighting, robust, taper) triples to measure; `kind` is 'seed'
    (wave-0 completion) or 'refine'."""

    def __init__(self, kind, proposals, n_units, plan_room, audit_room):
        self.kind = kind
        self.proposals = proposals
        self.n_units = n_units          # stencils / localization units admitted
        self.plan_room = plan_room
        self.audit_room = audit_room

    @property
    def n_new(self):
        return len(self.proposals)


# --------------------------------------------------------------------------- #
# The sampler: certify, classify, rank, plan.

class Sampler:
    """Ties a point table to its reconstructed quadtree and plans the next wave.
    Read-only: nothing here measures or mutates the table (that is task 2e)."""

    def __init__(self, subarray, table=None, mode=None, audit_budget=None,
                 beam_cap_mas=None):
        self.subarray = subarray
        if table is None:
            path = results_csv_path(subarray)
            cap = beam_cap_mas
            if cap is None and subarray in BEAM_CAP_ARCSEC:
                cap = BEAM_CAP_ARCSEC[subarray] * 1e3
            table = PointTable.from_csv(path, subarray=subarray,
                                        beam_cap_mas=cap)
        self.table = table
        self.tree = QuadTree(table, mode=mode)
        self.mode = self.tree.mode
        if self.mode == "fresh":
            self.plan_cap, self.audit_cap = PLAN_FRESH, AUDIT_FRESH
        else:
            self.plan_cap, self.audit_cap = PLAN_RETRO, AUDIT_RETRO
        if audit_budget is not None:
            self.audit_cap = int(audit_budget)
        # point-source envelope (cap-clipped) for dominance / goal detection
        self._env = None
        if table.has_anchors:
            samples = table.display_samples()
            curve = build_curve(samples, None, max_res=table.beam_cap_mas)
            self._env = _Envelope(curve) if curve else None
        self.certify()

    # -- corner helpers ------------------------------------------------------ #
    def _corner_mvecs(self, leaf):
        return [self.table.mvec(key_rt(*rt)) for rt in leaf.corners()]

    def _leaf_res_range(self, leaf, cm):
        rr = [m.res_mas for m in cm if m is not None]
        return (min(rr), max(rr)) if rr else None

    def _leaf_min_eta(self, cm):
        es = [m.eta for m in cm if m is not None]
        return min(es) if es else None

    # -- goal + dominance ---------------------------------------------------- #
    def _is_goal(self, leaf, cm):
        """A cell on/adjacent to a deliverable locus: the skirt binding band, or
        the point-source min-eta locus (its min-corner eta within tau_eta of the
        envelope over its res range)."""
        for m in cm:
            if m is not None and m.skirt is not None \
                    and SKIRT_BAND[0] <= m.skirt <= SKIRT_BAND[1]:
                return True
        if self._env is None:
            return False
        rng = self._leaf_res_range(leaf, cm)
        min_eta = self._leaf_min_eta(cm)
        if rng is None or min_eta is None:
            return False
        env_min = self._env.min_over(rng[0], rng[1])
        return env_min is not None and (min_eta - env_min) <= TAU_ETA

    def _is_dominated(self, leaf, cm):
        """Optimistic-eta dominance (finding #8): the leaf cannot improve the
        per-contour envelope minimum by more than tau_eta across its whole res
        range.  Three retirement paths, plus one exemption:

          * optimistic eta beyond ETA_CAP  -> retire (never a deliverable);
          * res range entirely coarser than the offered envelope (the expensive
            tapered tail the display trims)          -> retire;
          * covered range and margin > 1 everywhere  -> retire;
          * a genuine INTERIOR gap in the leaf's range -> keep active (the long
            gaps / cliffs are exactly what the sampler must fill).
        """
        min_eta = self._leaf_min_eta(cm)
        rng = self._leaf_res_range(leaf, cm)
        if rng is None or min_eta is None:
            return False
        E = leaf.E_T if leaf.refined else (leaf.parent_E or 0.0)
        optimistic = min_eta - E * TAU_ETA
        if optimistic > ETA_CAP:
            return True                     # too expensive to ever be offered
        if self._env is None or self._env.coverage_max is None:
            return False
        if self._env.has_gap_in(rng[0], rng[1]):
            return False                    # interior gap -> keep sampling
        if rng[0] > self._env.coverage_max * (1.0 + 1e-9):
            return True                     # entirely in the expensive tail
        env_max = self._env.max_over_covered(rng[0], rng[1])
        if env_max is None:
            return rng[0] > self._env.coverage_max * (1.0 + 1e-9)
        return (optimistic - env_max) / TAU_ETA > DOMINANCE_MARGIN

    # -- classification (adapted from refine._classify_scan semantics) ------- #
    def _detect_cut(self, leaf):
        """The strongest resolution discontinuity crossing a leaf edge, using
        ALL measured points inside the leaf's param box (non-dyadic legacy rows
        are auxiliary evidence).  Returns a Cut or None.  Semantics ported from
        refine: rim tolerance RIM_DEX, GAP_RATIO resolution jump."""
        t = self.table
        best = None

        def consider(axis, fixed, seq):
            nonlocal best
            for (p0, r0), (p1, r1) in zip(seq, seq[1:]):
                if max(r0, r1) / min(r0, r1) <= GAP_RATIO:
                    continue
                lo, hi = (p0, p1) if p0 < p1 else (p1, p0)
                fine, coarse = (min(r0, r1), max(r0, r1))
                sev = coarse / fine
                if best is None or sev > best[0]:
                    if axis == "taper":
                        frozen = hi / lo <= FREEZE_TAPER_RATIO
                        delta = math.log(hi / lo)
                    else:
                        frozen = (hi - lo) <= FREEZE_ROBUST_WIDTH
                        delta = hi - lo
                    best = (sev, Cut(axis, fixed, lo, hi, fine, coarse, delta,
                                     frozen))

        # taper direction at each robust rim
        for fr in (leaf.r0, leaf.r1):
            seq = []
            for m_taper in self._tapers_in(fr, leaf.t0, leaf.t1):
                mv = t.mvec_rt(fr, m_taper)
                if mv is not None:
                    seq.append((m_taper, mv.res_mas))
            consider("taper", fr, sorted(seq))
        # robust direction at each taper rim
        for ft in (leaf.t0, leaf.t1):
            seq = []
            for m_rob in self._robusts_in(ft, leaf.r0, leaf.r1):
                mv = t.mvec_rt(m_rob, ft)
                if mv is not None:
                    seq.append((m_rob, mv.res_mas))
            consider("robust", ft, sorted(seq))
        return best[1] if best else None

    def _tapers_in(self, robust, t0, t1):
        out = set([t0, t1])
        for r in self.table._eff.values():
            if r["weighting"] != "briggs":
                continue
            try:
                if round(float(r["robust"]), 2) != round(robust, 2):
                    continue
                tp = round(float(r["taper_mas"]), 3)
            except (TypeError, ValueError):
                continue
            if t0 <= tp <= t1 and tp > 0:
                out.add(tp)
        return sorted(out)

    def _robusts_in(self, taper, r0, r1):
        out = set([r0, r1])
        tk = round(taper, 3)
        for r in self.table._eff.values():
            if r["weighting"] != "briggs":
                continue
            try:
                if round(float(r["taper_mas"]), 3) != tk:
                    continue
                rb = round(float(r["robust"]), 2)
            except (TypeError, ValueError):
                continue
            if r0 <= rb <= r1:
                out.add(rb)
        return sorted(out)

    def _classify_cell(self, cell, cm):
        """Classify a REFINED cell (the level at which residual evidence exists)
        from its 4 corners + 5 stencil probes.  Ported refine._classify_scan
        semantics (rim tolerance RIM_DEX, display-eligibility, chord test):

          smooth  -- residual within tolerance (E_T < RETIRE_E);
          step    -- a resolution discontinuity with NO display-eligible interior
                     probe across it (a sampled/confirmed cliff);
          ridge   -- eligible interior probes sit above the rim chord (high
                     penalty, no interior dip);
          unresolved -- residual over tolerance but the cell is fillable (an
                     interior probe dips below the chord) or otherwise ambiguous.
        """
        if cell.E_T is not None and cell.E_T < RETIRE_E:
            cell.feature = SMOOTH
            return
        cut = self._detect_cut(cell)
        if cut is not None:
            cell.cut = cut
            # confirmed step unless a measured point lands STRICTLY inside the
            # crossing bracket AND inside the resolution gap (i.e. genuinely
            # fills it -- refine's "undersampled" vs "confirmed").  A probe on
            # either branch (near a rim) does NOT fill the gap.
            if self._bracket_filled(cell, cut):
                cell.feature = UNRESOLVED
            else:
                cell.feature = STEP
            return
        # no resolution discontinuity, but residual over tolerance: a ridge if
        # the interior sits above the rim chord, else simply under-sampled
        interior = self._interior_evidence(cell, cm)
        if interior and not any(dips for (_res, dips) in interior):
            cell.feature = RIDGE
        else:
            cell.feature = UNRESOLVED

    def _bracket_filled(self, cell, cut):
        """True iff a measured point sits STRICTLY inside the cut bracket (on the
        crossed axis) with a resolution well inside the gap -- i.e. the
        discontinuity is actually fillable at this density, not a confirmed
        cliff.  Points on either branch (near a rim resolution) do not count."""
        lo_r, hi_r = math.log(min(cut.res_fine, cut.res_coarse)), \
            math.log(max(cut.res_fine, cut.res_coarse))
        if cut.axis == "taper":
            rims = (cell.r0, cell.r1)
            for fr in rims:
                for tp in self._tapers_in(fr, cut.lo, cut.hi):
                    if not (cut.lo + 1e-9 < tp < cut.hi - 1e-9):
                        continue
                    mv = self.table.mvec_rt(fr, tp)
                    if mv is not None and lo_r + RIM_DEX < mv.lnres < hi_r - RIM_DEX:
                        return True
        else:
            for ft in (cell.t0, cell.t1):
                for rb in self._robusts_in(ft, cut.lo, cut.hi):
                    if not (cut.lo + 1e-9 < rb < cut.hi - 1e-9):
                        continue
                    mv = self.table.mvec_rt(rb, ft)
                    if mv is not None and lo_r + RIM_DEX < mv.lnres < hi_r - RIM_DEX:
                        return True
        return False

    def _interior_evidence(self, leaf, cm):
        """For a refined leaf: eligible interior stencil probes and whether each
        dips below the rim chord (fine->coarse in log res).  Uses the shared
        display-trim contract (sample_from_row)."""
        rng = self._leaf_res_range(leaf, cm)
        if rng is None:
            return []
        res_fine, res_coarse = rng
        fine_eta = min((m.eta for m in cm if m is not None
                        and abs(m.res_mas - res_fine) < 1e-9), default=None)
        coarse_eta = min((m.eta for m in cm if m is not None
                          and abs(m.res_mas - res_coarse) < 1e-9), default=None)
        out = []
        for (rp, tp, _s, _u) in leaf.stencil():
            mv = self.table.mvec_rt(rp, tp)
            if mv is None:
                continue
            s = sample_from_row(res_mas=mv.res_mas, eta=mv.eta, skirt=mv.skirt,
                                weighting="briggs", robust=rp, taper_mas=tp,
                                capped=mv.capped)
            if s is None:
                continue
            res = s["res"]
            if abs(math.log(res / res_fine)) <= RIM_DEX \
                    or abs(math.log(res / res_coarse)) <= RIM_DEX:
                continue                       # on a rim
            if not (res_fine < res < res_coarse):
                continue
            dips = False
            if fine_eta is not None and coarse_eta is not None and res_coarse > res_fine:
                w = math.log(res / res_fine) / math.log(res_coarse / res_fine)
                chord = fine_eta + w * (coarse_eta - fine_eta)
                dips = s["eta"] < chord - 1e-9
            out.append((res, dips))
        return out

    # -- certification pass -------------------------------------------------- #
    def certify(self):
        """Classify refined cells (where residual evidence lives), propagate
        step ownership to their descendants, then assign each terminal leaf a
        scheduling state (spec cell lifecycle + two-way retirement)."""
        self.step_cells = []
        for cell in self.tree.all_leaves():
            if not cell.refined:
                continue
            cm = self._corner_mvecs(cell)
            if any(m is None for m in cm):
                cell.feature = UNRESOLVED
                continue
            self._classify_cell(cell, cm)
            if cell.feature == STEP and cell.cut is not None and not cell.cut.frozen:
                cell.goal = True                # a discontinuity front is a locus
                cell.loss = self._loss(cell, cm)
                self.step_cells.append(cell)
                self._mark_step_owner(cell, cell)

        for leaf in self.tree.terminal_leaves():
            cm = self._corner_mvecs(leaf)
            if any(m is None for m in cm):
                leaf.state = UNTESTED           # corners not all measured yet
                leaf.feature = UNRESOLVED
                leaf.goal = False
                leaf.loss = 0.0
                continue
            if leaf.certified:                  # parent E_T < RETIRE_E
                leaf.state = CONVERGED
                leaf.feature = SMOOTH
                continue
            # feature inherited from the nearest refined ancestor's class
            if leaf.step_owner is not None:
                leaf.feature = STEP
            leaf.goal = self._is_goal(leaf, cm)
            leaf.loss = self._loss(leaf, cm)
            if leaf.step_owner is not None and leaf.step_owner.cut is not None \
                    and leaf.step_owner.cut.frozen:
                leaf.state = FROZEN
            elif self._is_dominated(leaf, cm) and not leaf.goal \
                    and leaf.step_owner is None:
                leaf.state = DOMINATED
            else:
                leaf.state = ACTIVE

    def _mark_step_owner(self, cell, owner):
        if cell.children:
            for c in cell.children:
                c.step_owner = owner
                self._mark_step_owner(c, owner)

    def _loss(self, leaf, cm):
        E = leaf.E_T if leaf.refined else (leaf.parent_E or 0.0)
        w = W_GOAL_ON if leaf.goal else W_GOAL_DEFAULT
        A = leaf.area(self.table.t_min, self.table.t_max)
        return w * min(E, E_MAX) * math.sqrt(max(A, 0.0)) + LAMBDA * A

    # -- state / feature tallies (CLI) --------------------------------------- #
    def state_counts(self):
        counts = {UNTESTED: 0, ACTIVE: 0, CONVERGED: 0, DOMINATED: 0,
                  FROZEN: 0, BUDGET_STOPPED: 0}
        for leaf in self.tree.terminal_leaves():
            counts[leaf.state] = counts.get(leaf.state, 0) + 1
        return counts

    def feature_cells(self):
        """Refined cells flagged step/ridge/unresolved (where residual evidence
        lives), sorted by resolution -- the annotations the CLI reports."""
        out = []
        for cell in self.tree.all_leaves():
            if not cell.refined or cell.feature not in (STEP, RIDGE, UNRESOLVED):
                continue
            cm = self._corner_mvecs(cell)
            rng = self._leaf_res_range(cell, cm)
            if rng is None:
                continue
            out.append((rng, cell))
        out.sort(key=lambda rl: rl[0][0])
        return [cell for _r, cell in out]

    # -- proposal generation ------------------------------------------------- #
    def _stencil_new(self, leaf):
        """New (weighting, robust, taper) stencil points not already present."""
        pts = []
        for (rp, tp, _s, _u) in leaf.stencil():
            trip = ("briggs",) + canon_rt(rp, tp)
            if not self.table.present(point_key(*trip)):
                pts.append(trip)
        return pts

    def _localize_new(self, leaf):
        """Cut-localization probes (ported E2 progressive log-midpoint / E1
        secant along the crossed axis), completed at both rims (E0 cell rule)."""
        cut = leaf.cut
        pts = []
        if cut is None:
            return pts
        if cut.axis == "taper":
            levels = progressive_log_midpoints(cut.lo, cut.hi, LOCALIZE_K)
            for tp in levels:
                for rr in (leaf.r0, leaf.r1):
                    trip = ("briggs",) + canon_rt(rr, tp)
                    if not self.table.present(point_key(*trip)):
                        pts.append(trip)
        else:
            mid = _mid_robust(cut.lo, cut.hi)
            for tp in (leaf.t0, leaf.t1):
                trip = ("briggs",) + canon_rt(mid, tp)
                if not self.table.present(point_key(*trip)):
                    pts.append(trip)
        return pts

    # -- 2:1 balance closure ------------------------------------------------- #
    def _edge_adjacent(self, a, b):
        """True iff leaves a,b share a portion of an edge in (u, log-taper)."""
        au0, au1 = robust_to_u(a.r0), robust_to_u(a.r1)
        bu0, bu1 = robust_to_u(b.r0), robust_to_u(b.r1)
        av0, av1 = math.log(a.t0), math.log(a.t1)
        bv0, bv1 = math.log(b.t0), math.log(b.t1)
        tol = 1e-9

        def touch(x1, y0, y1, x0b, x1b):
            return abs(x1 - x0b) < tol and min(y1, x1b) - max(y0, x0b) > tol
        # vertical shared edge (u touches, taper overlaps)
        u_touch = abs(au1 - bu0) < tol or abs(au0 - bu1) < tol
        v_overlap = min(av1, bv1) - max(av0, bv0) > tol
        if u_touch and v_overlap:
            return True
        # horizontal shared edge (taper touches, u overlaps)
        v_touch = abs(av1 - bv0) < tol or abs(av0 - bv1) < tol
        u_overlap = min(au1, bu1) - max(au0, bu0) > tol
        return v_touch and u_overlap

    def _balance_closure(self, leaf, terminals):
        """Coarser neighbors that must ALSO refine so refining `leaf` keeps the
        tree 2:1-balanced (conforming closure; finding #7).  Single-level per
        neighbor (deep cascades are bounded by the audit cap and are rare in
        phase 1 -- documented limitation)."""
        result, frontier = set(), [leaf]
        while frontier:
            cur = frontier.pop()
            for other in terminals:
                if other is cur or other is leaf or other in result:
                    continue
                if other.depth < cur.depth and self._edge_adjacent(cur, other):
                    result.add(other)
                    frontier.append(other)
        return result

    # -- the wave planner ---------------------------------------------------- #
    def plan_wave(self, batch=B_MAX, cap=None):
        """ask(B): the next wave of proposals under whole-cell, balance-aware
        admission (never a partial stencil), tie-broken by lexicographic
        point_key.  `cap` overrides the per-wave new-eval ceiling (default = the
        plan headroom, always clamped to the hard audit cap)."""
        used_evals = self.table.n_effective if self.mode == "fresh" else 0
        audit_room = max(0, self.audit_cap - used_evals)
        plan_room = max(0, self.plan_cap - used_evals)
        ceiling = plan_room if cap is None else int(cap)
        ceiling = min(ceiling, audit_room)          # hard audit cap never crossed

        missing = self.tree.missing_seed_points()
        if missing:
            missing = sorted(set(missing), key=lambda p: point_key(*p))
            admitted = missing[:ceiling]
            return WavePlan("seed", admitted, len(admitted), plan_room, audit_room)

        terminals = self.tree.terminal_leaves()
        units = []                                  # (loss, sort_key, [new points])

        def add_unit(loss, sort_key, pts):
            seen, uniq = set(), []
            for p in pts:
                k = point_key(*p)
                if k not in seen:
                    seen.add(k)
                    uniq.append(p)
            if uniq:
                units.append((loss, sort_key, uniq))

        # (a) step cells: one localization unit each (ported E1/E2 along the
        # crossed axis) -- their terminal children are NOT blindly stenciled.
        for cell in getattr(self, "step_cells", []):
            add_unit(cell.loss, cell.sort_key(), self._localize_new(cell))
        # (b) active terminal leaves NOT owned by a step cell: a subdivision
        # stencil each, plus any 2:1 balance closures.
        for leaf in terminals:
            if leaf.state != ACTIVE or leaf.step_owner is not None:
                continue
            pts = self._stencil_new(leaf)
            for cl in self._balance_closure(leaf, terminals):
                pts += self._stencil_new(cl)
            add_unit(leaf.loss, leaf.sort_key(), pts)
        units.sort(key=lambda u: (-u[0], u[1]))

        proposals, used, n_units = [], set(), 0
        for (_loss, _sk, pts) in units:
            new = [p for p in pts if point_key(*p) not in used]
            if not new:
                continue
            if len(proposals) + len(new) > ceiling:   # whole-or-nothing; B shrinks
                continue
            for p in new:
                used.add(point_key(*p))
            proposals.extend(new)
            n_units += 1
            if n_units >= batch:
                break
        proposals.sort(key=lambda p: point_key(*p))
        return WavePlan("refine", proposals, n_units, plan_room, audit_room)


# --------------------------------------------------------------------------- #
# CLI

def results_csv_path(subarray):
    """The combo's results CSV for `subarray` (RESULTS_DIR is env-routed by
    config; matches sweep.Sweep.results_path)."""
    fname = subarray.replace("+", "_").replace("-", "_") + ".csv"
    return os.path.join(RESULTS_DIR, fname)


def _fmt_trip(trip):
    w, r, t = trip
    if w == "natural":
        return "natural            taper=%.3f" % t
    return "briggs r=%+5.2f  taper=%.3f" % (r, t)


def plan_only_report(sampler, waves=1, out=sys.stdout):
    """Emit the plan-only summary + next wave (spec CLI contract)."""
    t = sampler.table
    p = lambda *a: print(*a, file=out)
    band = os.environ.get("NGVLA_BAND", "n/a")
    p("adaptive sampler -- plan-only  (%s)" % SPEC_VERSION)
    p("  manifest %s   combo %s/%s   band %s" % (manifest_hash(), REV, SIM_MODE, band))
    p("  subarray: %s" % sampler.subarray)
    p("  mode: %s (%s)   audit cap %d   plan cap %d"
      % (sampler.mode,
         "auto" if sampler.tree.mode == QuadTree.detect_mode(t) else "forced",
         sampler.audit_cap, sampler.plan_cap))
    p("  table: %d effective rows (%d capped); attempted %d (%d failed, %d skipped)"
      % (t.n_effective, t.n_capped, t.n_attempted, t.n_failed, t.n_skipped))
    if not t.has_anchors:
        p("  anchors: MISSING -- the two seed points define the taper grid")
    else:
        p("  anchors: res_fine %.4g mas, res_nat %.4g mas -> t_min %.4g, t_max %.4g mas"
          % (t.res_fine, t.res_nat, t.t_min, t.t_max))
    p("  seed grid: %d robusts x %d tapers -> %d seed cells; missing seed vertices %d"
      % (len(sampler.tree.seed_robusts), len(sampler.tree.seed_tapers),
         sampler.tree.n_seed_leaves, len(sampler.tree.missing_seed_points())))

    counts = sampler.state_counts()
    total = sum(counts.values())
    p("  leaves: %d total  (untested %d, active %d, converged %d, "
      "dominated-retired %d, frozen %d)"
      % (total, counts[UNTESTED], counts[ACTIVE], counts[CONVERGED],
         counts[DOMINATED], counts[FROZEN]))
    p("  certification: retired-by-residual %d, retired-by-dominance %d, active %d"
      % (counts[CONVERGED], counts[DOMINATED], counts[ACTIVE] + counts[UNTESTED]))

    feats = sampler.feature_cells()
    fc = {STEP: 0, RIDGE: 0, UNRESOLVED: 0}
    for cell in feats:
        fc[cell.feature] = fc.get(cell.feature, 0) + 1
    p("  features: step %d, ridge %d, unresolved %d"
      % (fc[STEP], fc[RIDGE], fc[UNRESOLVED]))
    for cell in feats[:14]:
        cm = sampler._corner_mvecs(cell)
        rng = sampler._leaf_res_range(cell, cm)
        if cell.cut is not None:
            c = cell.cut
            p("    %-10s res %.4g mas  cut on %s [%.4g, %.4g]  delta %.3g  E_T %.2f%s"
              % (cell.feature, c.mid_res_mas(), c.axis, c.lo, c.hi, c.delta,
                 cell.E_T or 0.0, "  FROZEN" if c.frozen else ""))
        else:
            p("    %-10s res %.4g-%.4g mas  E_T %.2f"
              % (cell.feature, rng[0], rng[1], cell.E_T or 0.0))
    if len(feats) > 14:
        p("    ... and %d more" % (len(feats) - 14))

    plan = sampler.plan_wave()
    p("  next wave (%s): %d units, %d new evals  [plan room %d, audit room %d]"
      % (plan.kind, plan.n_units, plan.n_new, plan.plan_room, plan.audit_room))
    for trip in plan.proposals[:40]:
        p("    %s" % _fmt_trip(trip))
    if plan.n_new > 40:
        p("    ... and %d more" % (plan.n_new - 40))
    if waves > 1:
        p("  (--waves %d: plan-only emits only the immediate next wave; the "
          "measuring driver (task 2e) advances the rest)" % waves)
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description="MFS-2 adaptive sampler (2b, "
                                 "phase 1: planning only).")
    ap.add_argument("subarray", choices=sorted(SUBARRAYS))
    ap.add_argument("--plan-only", action="store_true",
                    help="emit the next wave without measuring (the ONLY "
                         "execution path in phase 1)")
    ap.add_argument("--budget", type=int, default=None,
                    help="override the hard audit cap (evals; total for fresh, "
                         "new-only for retrofit)")
    ap.add_argument("--waves", type=int, default=1,
                    help="waves the driver would run (plan-only shows only the "
                         "next one)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--warm-start", dest="mode", action="store_const",
                   const="retrofit", help="force certification-first warm start")
    g.add_argument("--fresh", dest="mode", action="store_const", const="fresh",
                   help="force a fresh seed")
    args = ap.parse_args(argv)

    if not args.plan_only:
        print("measuring driver not built yet (task 2e)", file=sys.stderr)
        return 2

    sampler = Sampler(args.subarray, mode=args.mode, audit_budget=args.budget)
    plan_only_report(sampler, waves=args.waves)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
CASA-free tests for the MFS-2 adaptive sampler core (curvegen/adaptive.py).

No CASA / tclean here: synthetic point tables are built from analytic models in
the real sweep-result schema (keyed by sweep.point_key), exactly like the
FakeSweep pattern in tests/test_refine.py, so PointTable / QuadTree / Sampler
treat them as real maps.  The models reproduce the map classes the sampler must
handle -- a smooth plateau, a taper-onset cliff, a fillable gap, a hidden ridge
-- so the seed, lifecycle, retirement, classifier and wave planner can be
exercised end to end.

Run from the repository root:

    casapy -m unittest tests.test_adaptive
"""

import importlib
import io
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "curvegen"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_adaptive():
    try:
        return importlib.import_module("adaptive")
    except ImportError as e:                       # pragma: no cover
        raise unittest.SkipTest("curvegen/adaptive.py needs CASA here: %s" % e)


A = _load_adaptive()
from config import grid_rows, ROBUST_LIST            # noqa: E402
from adaptive_support import point_key                # noqa: E402


# --------------------------------------------------------------------------- #
# synthetic-table helpers (rows in the sweep.FIELDS schema)

def _row(subarray, weighting, robust, taper, res_mas, eta, skirt, status="ok"):
    return dict(subarray=subarray, weighting=weighting, robust=robust,
                taper_mas=taper,
                res_geo_arcsec=("" if res_mas is None else res_mas / 1e3),
                sigma_dirty=("" if eta is None else eta),   # sigma_nat forced 1
                skirt=("" if skirt is None else skirt),
                status=status)


def synth_rows(model, subarray="core", sigma_nat=1.0, status_fn=None):
    """A full CANONICAL lattice (natural row + 11 robusts x [0 + N tapers]) in
    the sweep schema, generated from `model(weighting, robust, taper) ->
    (res_mas, eta, skirt)`.  eta is stored as sigma_dirty with sigma_nat=1, so
    PointTable's eta = sigma_dirty/sigma_nat reproduces the model eta exactly.
    The taper grid is config.grid_rows so the retrofit seed's canonical tapers
    line up with the generated lattice."""
    res_nat = model("natural", 2.0, 0.0)[0]
    res_fine = model("briggs", -2.0, 0.0)[0]
    spec = grid_rows(res_fine, res_nat, subarray)
    rows = []
    for (w, r, tapers) in spec:
        for t in tapers:
            res, eta, skirt = model(w, r, t)
            st = "ok"
            if status_fn is not None:
                st = status_fn(w, r, t, res, eta, skirt) or "ok"
            rows.append(_row(subarray, w, r, t, res,
                             None if eta is None else eta * sigma_nat,
                             skirt, status=st))
    return rows


# analytic models --------------------------------------------------------- #

def model_plateau(w, r, t):
    """res depends on taper only (so a taper column shares its resolution); the
    positive-robust branch is cheap + smooth (-> the envelope), the negative
    branch is expensive AND curved (-> activated by residual, then dominated)."""
    rr = 2.0 if w == "natural" else r
    res = 1.0 * (1.0 + t) ** 0.5
    if rr >= 0:
        eta = 1.0 + 0.06 * t
    else:
        eta = 2.6 + 0.5 * t + 0.5 * math.sin(1.3 * t)     # curved + expensive
    return res, eta, 0.30


def model_cliff(w, r, t):
    """A taper-onset cliff: below t*=1.0 a fine branch (res ~1.0-1.4); at/after
    t* the resolution JUMPS to >=2.2 (ratio ~2), with no interior resolution."""
    rr = 2.0 if w == "natural" else r
    base = 1.0 + (rr + 2.0) / 4.0 * 0.3
    if t < 1.0:
        return base * (1.0 + 0.08 * t), 1.0 + 0.05 * t, 0.05
    return 2.2 * (1.0 + 0.08 * (t - 1.0)), 1.8 + 0.08 * (t - 1.0), 0.05


def model_gap(w, r, t):
    """A smooth, fillable map (no discontinuity): resolution grows smoothly with
    taper.  A refined cell here is under-sampled/fillable, never a step."""
    rr = 2.0 if w == "natural" else r
    res0 = 1.0 + (rr + 2.0) / 4.0 * 0.3
    return res0 * (1.0 + t) ** 0.85, 1.0 + 0.12 * t, 0.05


def model_smooth(w, r, t):
    """Everywhere smooth and cheap -> nearly all cells certify by residual."""
    rr = 2.0 if w == "natural" else r
    return (1.0 + (rr + 2.0) / 4.0 * 0.2) * (1.0 + t) ** 0.5, 1.0 + 0.05 * t, 0.05


def sampler(model, subarray="core", mode=None, **kw):
    rows = synth_rows(model, subarray, **kw)
    table = A.PointTable(rows, subarray=subarray)
    return A.Sampler(subarray, table=table, mode=mode)


# analytic models for the measuring driver (task 2e) ---------------------- #

def model_fillable_bump(w, r, t):
    """A genuine "fillable" defect for the driver's wave loop: model_gap's
    smooth taper law (no discontinuity -- refinable, never a step) plus a
    resolution-localized eta bump big enough to activate MORE seed leaves
    than one wave's batch (B_MAX=16) admits (~66 new evals total, comfortably
    under the retrofit audit cap of 80), so a retrofit warm start genuinely
    needs 2 measuring waves before the 3rd (check-only) wave finds nothing
    left -- the defect's SHAPE is what takes multiple waves here, not the
    budget (contrast model_bilinear_seed below)."""
    rr = 2.0 if w == "natural" else r
    res = (1.0 + (rr + 2.0) / 4.0 * 0.3) * (1.0 + t) ** 0.85
    bump = 0.45 * math.exp(-((res - 2.0) / 0.4) ** 2)
    return res, 1.0 + 0.12 * t + bump, 0.05


def model_bilinear_seed(w, r, t):
    """Exactly affine-bilinear in (u, ln t) -- since v (the taper coordinate)
    is itself affine in ln(t) for ANY t_min/t_max, this is then exactly
    bilinear in the sampler's normalized (u, v) too, so every seed leaf's
    residual E_T is ~0 (up to point_key rounding) and its children certify
    on the FIRST stencil round.  Used for a FRESH (empty-table) run: the
    30-leaf domain's combined stencils comfortably exceed one wave's
    plan/batch room, so the driver's own audit-cap tracking (not the
    defect's shape) is what has to shrink the wave and eventually halt."""
    u = 0.5 if w == "natural" else (r + 2.0) / 4.0
    lt = math.log(t) if t > 0 else math.log(1e-3)
    lnres = 0.5 + 0.1 * u + 0.15 * lt + 0.02 * u * lt
    eta = 1.0 + 0.05 * u + 0.03 * lt + 0.01 * u * lt
    return math.exp(lnres), max(eta, 1.0 + 1e-6), 0.05


class FakeSweep:
    """A drop-in stand-in for sweep.Sweep (same pattern as
    tests/test_refine.py's FakeSweep): run_point evaluates an analytic model
    instead of tclean, and rows use the real sweep schema keyed by
    point_key, so PointTable/Sampler/run_wave_loop treat it like the real
    thing.  `rows` seeds an existing table (a retrofit warm start); omit it
    for a fresh (empty) run.  `fail_keys` makes specific (already-canonical)
    point_key strings measure as status="failed" -- exactly once, since a
    present key is never re-run (matching sweep.Sweep.run_point)."""

    def __init__(self, subarray, model, rows=None, fail_keys=None):
        self.subarray = subarray
        self.model = model
        self.rows = {}
        self.calls = 0
        self.fail_keys = set(fail_keys or ())
        for row in (rows or []):
            key = point_key(row["weighting"], row["robust"], row["taper_mas"])
            self.rows[key] = row

    def run_point(self, weighting, robust, taper_mas):
        key = point_key(weighting, robust, taper_mas)
        if key in self.rows:
            return self.rows[key]
        self.calls += 1
        if key in self.fail_keys:
            row = dict(subarray=self.subarray, weighting=weighting,
                       robust=robust, taper_mas=taper_mas, res_geo_arcsec="",
                       sigma_dirty="", skirt="", status="failed")
        else:
            res_mas, eta, skirt = self.model(weighting, robust, taper_mas)
            row = dict(subarray=self.subarray, weighting=weighting,
                       robust=robust, taper_mas=taper_mas,
                       res_geo_arcsec=res_mas / 1e3, sigma_dirty=eta,
                       skirt=skirt, status="ok")
        self.rows[key] = row
        return row


# --------------------------------------------------------------------------- #
# 1. coordinates and the seam

class TestCoordinates(unittest.TestCase):

    def test_robust_u_roundtrip(self):
        for r in (-2.0, -1.2, 0.0, 0.4, 2.0):
            self.assertAlmostEqual(A.u_to_robust(A.robust_to_u(r)), r, places=9)
        self.assertEqual(A.robust_to_u(-2.0), 0.0)
        self.assertEqual(A.robust_to_u(2.0), 1.0)

    def test_taper_v_roundtrip(self):
        tmin, tmax = 0.1, 10.0
        for t in (0.1, 0.5, 1.0, 10.0):
            self.assertAlmostEqual(A.v_to_taper(A.taper_to_v(t, tmin, tmax),
                                                tmin, tmax), t, places=9)
        self.assertAlmostEqual(A.taper_to_v(tmin, tmin, tmax), 0.0)
        self.assertAlmostEqual(A.taper_to_v(tmax, tmin, tmax), 1.0)

    def test_canon_rt_folds_negative_zero(self):
        r, t = A.canon_rt(-0.0, -0.0)
        self.assertEqual((r, t), (0.0, 0.0))
        self.assertEqual(math.copysign(1.0, r), 1.0)     # +0.0, not -0.0
        self.assertEqual(A.key_rt(*A.canon_rt(-0.001, 1.2345)),
                         point_key("briggs", 0.0, 1.234))

    def test_taper_midpoint_is_geometric_mean(self):
        # v is linear in log taper, so the v-midpoint is the geometric mean
        self.assertAlmostEqual(A._mid_taper(1.0, 4.0), 2.0, places=9)


# --------------------------------------------------------------------------- #
# 2. fresh seed exactness (56 points / 30 leaves)

class TestFreshSeed(unittest.TestCase):

    def _anchor_table(self):
        # just the two anchors measured -> defines t_min/t_max for the taper grid
        rows = [_row("core", "natural", 2.0, 0.0, 1.30, 1.0, 0.05),
                _row("core", "briggs", -2.0, 0.0, 1.00, 1.02, 0.05)]
        return A.PointTable(rows, subarray="core")

    def test_seed_is_exactly_56_points(self):
        tree = A.QuadTree(self._anchor_table(), mode="fresh")
        pts = tree.seed_points()
        self.assertEqual(len(pts), A.SEED_TOTAL_FRESH)   # 56
        self.assertEqual(len(set(pts)), 56)

    def test_seed_block_breakdown(self):
        tree = A.QuadTree(self._anchor_table(), mode="fresh")
        pts = tree.seed_points()
        briggs_grid = [p for p in pts if p[0] == "briggs" and p[2] > 0]
        seam = [p for p in pts if p[0] == "briggs" and p[2] == 0]
        natural = [p for p in pts if p[0] == "natural"]
        self.assertEqual(len(briggs_grid), 42)           # 6 robusts x 7 tapers
        self.assertEqual(len(seam), 6)                   # untapered seam column
        self.assertEqual(len(natural), 8)                # taper 0 + 7 tapers

    def test_thirty_seed_leaves(self):
        tree = A.QuadTree(self._anchor_table(), mode="fresh")
        self.assertEqual(tree.n_seed_leaves, A.SEED_LEAVES_FRESH)  # 30

    def test_seed_robusts_are_every_other(self):
        self.assertEqual(A.SEED_ROBUSTS, [-2.0, -1.2, -0.4, 0.4, 1.2, 2.0])

    def test_empty_table_proposes_anchors_first(self):
        tree = A.QuadTree(A.PointTable([], subarray="core"), mode="fresh")
        missing = tree.missing_seed_points()
        self.assertEqual(set(missing),
                         {("natural", 2.0, 0.0), ("briggs", -2.0, 0.0)})


# --------------------------------------------------------------------------- #
# 3. seam handling (taper=0 / natural stay OUT of the quadtree)

class TestSeam(unittest.TestCase):

    def test_no_quadtree_node_at_taper_zero_or_natural(self):
        s = sampler(model_smooth)
        for leaf in s.tree.all_leaves():
            self.assertGreater(leaf.t0, 0.0)             # domain starts at t_min
            self.assertGreater(leaf.t1, 0.0)
        # seed taper nodes are all positive; natural is never a node robust
        self.assertTrue(all(t > 0 for t in s.tree.seed_tapers))

    def test_natural_as_robust_two_is_proposal_only(self):
        # proposals are all briggs (the natural row is a 1-D family, not refined)
        s = sampler(model_gap)
        plan = s.plan_wave()
        self.assertTrue(all(p[0] == "briggs" for p in plan.proposals))

    def test_point_validation_keeps_seam_and_natural_outside_assessment(self):
        s = sampler(model_smooth)
        self.assertEqual(s.point_validation_state("natural", 2.0, 1.0),
                         A.NOT_ASSESSED)
        self.assertEqual(s.point_validation_state("briggs", 0.0, 0.0),
                         A.NOT_ASSESSED)

    def test_point_validation_requires_residual_convergence(self):
        smooth = sampler(model_smooth)
        converged = next(leaf for leaf in smooth.tree.terminal_leaves()
                         if leaf.state == A.CONVERGED)
        self.assertEqual(smooth.point_validation_state(
            "briggs", (converged.r0 + converged.r1) / 2.0,
            A._mid_taper(converged.t0, converged.t1)),
            A.RESIDUAL_VALIDATED)

        unfinished = sampler(model_gap)
        active = next(leaf for leaf in unfinished.tree.terminal_leaves()
                      if leaf.state == A.ACTIVE)
        self.assertEqual(unfinished.point_validation_state(
            "briggs", (active.r0 + active.r1) / 2.0,
            A._mid_taper(active.t0, active.t1)),
            A.NOT_RESIDUAL_VALIDATED)


# --------------------------------------------------------------------------- #
# 4. retrofit auto-detection + dyadic seed derivation on a legacy lattice

class TestRetrofitSeed(unittest.TestCase):

    def test_mode_autodetects_retrofit_on_populated_table(self):
        s = sampler(model_smooth)
        self.assertEqual(s.mode, "retrofit")

    def test_mode_autodetects_fresh_on_empty_table(self):
        self.assertEqual(A.QuadTree.detect_mode(A.PointTable([])), "fresh")

    def test_seed_tapers_are_every_other_canonical(self):
        rows = synth_rows(model_smooth, "core")
        table = A.PointTable(rows, subarray="core")
        tree = A.QuadTree(table, mode="retrofit")
        canonical = [round(t, 3) for t in grid_rows(table.res_fine, table.res_nat,
                                                    "core")[0][2] if t > 0]
        expected = canonical[::2]
        if canonical[-1] not in expected:
            expected.append(canonical[-1])
        self.assertEqual(tree.seed_tapers, expected)
        self.assertEqual(tree.seed_robusts, A.SEED_ROBUSTS)

    def test_first_bisection_is_warm(self):
        # a seed cell's stencil midpoints land on the skipped canonical lattice
        # points, which ARE in the table -> the seed cell reconstructs as refined
        s = sampler(model_smooth)
        refined = [c for c in s.tree.all_leaves() if c.refined]
        self.assertGreater(len(refined), 0, "warm start did not refine any cell")

    def test_clean_lattice_has_no_missing_seed_vertices(self):
        s = sampler(model_smooth)
        self.assertEqual(len(s.tree.missing_seed_points()), 0)


# --------------------------------------------------------------------------- #
# 5. non-dyadic legacy rows are auxiliary evidence, never topology

class TestNonDyadicAuxiliary(unittest.TestCase):

    def test_scattered_rows_do_not_change_topology(self):
        base = synth_rows(model_smooth, "core")
        s0 = A.Sampler("core", table=A.PointTable(base, subarray="core"))
        n_seed0 = s0.tree.n_seed_leaves
        n_term0 = len(s0.tree.terminal_leaves())
        # inject non-canonical (non-dyadic) rows at odd tapers/robusts
        extra = [_row("core", "briggs", -0.37, 0.531, 1.234, 1.5, 0.05),
                 _row("core", "briggs", 0.13, 2.717, 1.789, 1.9, 0.05)]
        s1 = A.Sampler("core", table=A.PointTable(base + extra, subarray="core"))
        self.assertEqual(s1.tree.n_seed_leaves, n_seed0)   # seed grid unchanged
        self.assertEqual(len(s1.tree.terminal_leaves()), n_term0)
        # the seed taper/robust axes are the canonical every-other set, untouched
        self.assertEqual(s1.tree.seed_tapers, s0.tree.seed_tapers)
        self.assertEqual(s1.tree.seed_robusts, s0.tree.seed_robusts)


# --------------------------------------------------------------------------- #
# 6. effective-row rule + capped/failed/retried handling + res censoring

class TestEffectiveRows(unittest.TestCase):

    def test_last_ok_or_capped_wins(self):
        rows = [_row("core", "briggs", 0.0, 1.0, 1.0, 2.0, 0.1, "ok"),
                _row("core", "briggs", 0.0, 1.0, 1.0, 3.0, 0.1, "ok")]  # retried
        t = A.PointTable(rows)
        self.assertEqual(float(t.row(point_key("briggs", 0.0, 1.0))["sigma_dirty"]),
                         3.0)                              # the LAST ok row

    def test_failed_only_key_is_attempted_not_hit(self):
        rows = [_row("core", "briggs", 0.0, 1.0, None, None, None, "failed")]
        t = A.PointTable(rows)
        k = point_key("briggs", 0.0, 1.0)
        self.assertTrue(t.present(k))                      # attempted (occupies)
        self.assertFalse(t.hit(k))                         # not effective evidence
        self.assertEqual(t.n_failed, 1)

    def test_ok_supersedes_earlier_failed_across_rows(self):
        rows = [_row("core", "briggs", 0.0, 1.0, None, None, None, "failed"),
                _row("core", "briggs", 0.0, 1.0, 1.0, 2.0, 0.1, "ok")]
        t = A.PointTable(rows)
        self.assertTrue(t.hit(point_key("briggs", 0.0, 1.0)))

    def test_capped_is_a_hit_and_flagged(self):
        rows = [_row("core", "natural", 2.0, 0.0, 1.0, 1.0, 0.1, "ok"),
                _row("core", "briggs", 0.0, 5.0, 9.0, 2.0, 0.1, "capped")]
        t = A.PointTable(rows)
        mv = t.mvec_rt(0.0, 5.0)
        self.assertIsNotNone(mv)
        self.assertTrue(mv.capped)

    def test_capped_probe_res_is_censored_in_residual(self):
        # a leaf whose centre stencil probe is CAPPED with a wild resolution must
        # NOT manufacture a res residual (only eta/skirt count) -- compare a map
        # where that probe is 'ok' (res counts) vs 'capped' (res censored)
        def cap_status(w, r, t, res, eta, skirt):
            return None
        rows = synth_rows(model_smooth, "core")
        # pick a seed cell centre (odd robust, a canonical mid taper) and corrupt
        # its resolution wildly, once as ok and once as capped
        target = None
        s0 = sampler(model_smooth)
        for cell in s0.tree.all_leaves():
            if cell.refined:
                rm, tm = A._mid_robust(cell.r0, cell.r1), A._mid_taper(cell.t0, cell.t1)
                target = (rm, tm, cell.r0, cell.r1, cell.t0, cell.t1)
                break
        self.assertIsNotNone(target)
        rm, tm, r0, r1, t0, t1 = target
        key = point_key("briggs", *A.canon_rt(rm, tm))

        def corrupt(rows, status):
            out = []
            for row in rows:
                if point_key(row["weighting"], row["robust"], row["taper_mas"]) == key:
                    row = dict(row, res_geo_arcsec=50.0 / 1e3, status=status)  # wild res
                out.append(row)
            return out

        s_ok = A.Sampler("core", table=A.PointTable(corrupt(rows, "ok"), subarray="core"))
        s_cap = A.Sampler("core", table=A.PointTable(corrupt(rows, "capped"), subarray="core"))

        def cell_ET(s):
            for c in s.tree.all_leaves():
                if c.refined and abs(c.r0 - r0) < 1e-9 and abs(c.r1 - r1) < 1e-9 \
                        and abs(c.t0 - t0) < 1e-9 and abs(c.t1 - t1) < 1e-9:
                    return c.E_T
            return None
        e_ok, e_cap = cell_ET(s_ok), cell_ET(s_cap)
        self.assertIsNotNone(e_ok)
        self.assertIsNotNone(e_cap)
        # the wild resolution blows up E_T when 'ok', but is censored when 'capped'
        self.assertGreater(e_ok, e_cap + 1.0)


# --------------------------------------------------------------------------- #
# 7. restart determinism (same table -> byte-equal next wave)

class TestRestartDeterminism(unittest.TestCase):

    def test_same_table_same_wave(self):
        rows = synth_rows(model_gap, "core")
        p1 = A.Sampler("core", table=A.PointTable(rows, subarray="core")).plan_wave()
        p2 = A.Sampler("core", table=A.PointTable(list(rows), subarray="core")).plan_wave()
        self.assertEqual(p1.proposals, p2.proposals)      # identical, in order
        self.assertEqual(repr(p1.proposals), repr(p2.proposals))   # byte-equal

    def test_proposals_are_lexicographically_sorted(self):
        p = sampler(model_gap).plan_wave()
        keys = [point_key(*t) for t in p.proposals]
        self.assertEqual(keys, sorted(keys))


# --------------------------------------------------------------------------- #
# 8. budget admission (whole stencil or nothing; audit cap; B shrink)

class TestBudgetAdmission(unittest.TestCase):

    def test_audit_cap_never_crossed(self):
        s = sampler(model_gap)
        for cap in (0, 3, 6, 12, 25):
            plan = s.plan_wave(batch=A.B_MAX, cap=cap)
            self.assertLessEqual(plan.n_new, cap,
                                 "wave of %d exceeded cap %d" % (plan.n_new, cap))

    def test_whole_stencil_or_nothing(self):
        # with a cap smaller than any single admissible unit, admit nothing
        s = sampler(model_gap)
        # find the smallest unit size actually offered
        full = s.plan_wave(batch=A.B_MAX, cap=999)
        self.assertGreater(full.n_new, 0)
        tiny = s.plan_wave(batch=A.B_MAX, cap=1)
        # a stencil is >= 2 new points here, so cap=1 buys a whole unit or none
        self.assertIn(tiny.n_new, (0,) if full.n_new else (0,))
        self.assertLessEqual(tiny.n_new, 1)

    def test_batch_shrink(self):
        s = sampler(model_gap)
        big = s.plan_wave(batch=A.B_MAX, cap=999)
        small = s.plan_wave(batch=2, cap=999)
        self.assertLessEqual(small.n_units, 2)
        self.assertLessEqual(small.n_new, big.n_new)

    def test_no_duplicate_proposals(self):
        p = sampler(model_gap).plan_wave()
        keys = [point_key(*t) for t in p.proposals]
        self.assertEqual(len(keys), len(set(keys)))

    def test_wave_within_plan_cap_by_default(self):
        # default (cap=None) never exceeds the plan headroom
        s = sampler(model_gap)
        self.assertLessEqual(s.plan_wave().n_new, s.plan_cap)


# --------------------------------------------------------------------------- #
# 9. classifier: step vs fillable, and freeze via bracket localization

class TestClassifier(unittest.TestCase):

    def test_cliff_classified_as_step_with_bracket(self):
        s = sampler(model_cliff)
        steps = [c for c in s.tree.all_leaves()
                 if c.refined and c.feature == A.STEP and c.cut is not None]
        self.assertGreater(len(steps), 0, "taper-onset cliff not flagged as step")
        cut = steps[0].cut
        self.assertEqual(cut.axis, "taper")
        self.assertLess(cut.lo, cut.hi)
        self.assertGreater(cut.res_coarse / cut.res_fine, A.GAP_RATIO)

    def test_fillable_map_is_not_a_step(self):
        s = sampler(model_gap)
        steps = [c for c in s.tree.all_leaves()
                 if c.refined and c.feature == A.STEP]
        self.assertEqual(len(steps), 0, "a smooth/fillable map was called a step")

    def test_step_freezes_when_bracket_localized(self):
        # localize the cliff by measuring probes inside the bracket until the
        # crossed-axis bracket narrows below the freeze ratio (the d ln res <=
        # ln 1.05 leg of the limiting-envelope test)
        rows = synth_rows(model_cliff, "core")
        frozen = False
        for _round in range(8):
            s = A.Sampler("core", table=A.PointTable(rows, subarray="core"))
            cuts = [c.cut for c in s.tree.all_leaves()
                    if c.refined and c.feature == A.STEP and c.cut is not None]
            if any(c.frozen for c in
                   (cc for cell in s.tree.all_leaves()
                    if cell.cut is not None for cc in [cell.cut])):
                frozen = True
                break
            if not cuts:
                break
            cut = cuts[0]
            # add one progressive-log-midpoint probe at both robust rims
            mids = A.progressive_log_midpoints(cut.lo, cut.hi, 1)
            if not mids:
                break
            tp = mids[0]
            for rr in A.SEED_ROBUSTS:
                res, eta, skirt = model_cliff("briggs", rr, tp)
                rows.append(_row("core", "briggs", rr, tp, res, eta, skirt))
        self.assertTrue(frozen, "cut never froze as the bracket was localized")


# --------------------------------------------------------------------------- #
# 10. dominance retirement on a plateau map

class TestDominance(unittest.TestCase):

    def test_most_of_the_domain_retires(self):
        s = sampler(model_plateau)
        counts = s.state_counts()
        total = sum(counts.values())
        retired = counts[A.CONVERGED] + counts[A.DOMINATED]
        self.assertGreater(retired, 0.6 * total,
                           "expected most of the plateau to retire")

    def test_expensive_negative_robust_cells_are_dominated(self):
        s = sampler(model_plateau)
        self.assertGreater(s.state_counts()[A.DOMINATED], 0,
                           "no cell retired by dominance")
        # a coarse, negative-robust leaf (far above the envelope) is dominated
        dominated = [l for l in s.tree.terminal_leaves()
                     if l.state == A.DOMINATED]
        self.assertTrue(any(l.r0 < 0 for l in dominated))

    def test_interior_gap_is_not_dominated(self):
        # a leaf straddling a genuine curve gap stays active (long-style)
        s = sampler(model_cliff)
        # the step region must remain in play (active or a step cell), never
        # silently dominance-retired
        active_or_step = [l for l in s.tree.terminal_leaves()
                          if l.state in (A.ACTIVE, A.FROZEN)
                          or l.step_owner is not None]
        self.assertGreater(len(active_or_step), 0)


# --------------------------------------------------------------------------- #
# 11. loss and the exploration floor

class TestLossAndExploration(unittest.TestCase):

    def test_loss_formula(self):
        s = sampler(model_gap)
        # build a leaf with known E_T and area and check the pinned formula
        leaf = A.Leaf(-2.0, -1.2, 1.0, 2.0, 1)
        leaf.refined = True
        leaf.E_T = 2.0
        leaf.goal = False
        A_T = leaf.area(s.table.t_min, s.table.t_max)
        expected = (A.W_GOAL_DEFAULT * min(2.0, A.E_MAX) * math.sqrt(A_T)
                    + A.LAMBDA * A_T)
        self.assertAlmostEqual(s._loss(leaf, [None] * 4), expected, places=9)

    def test_e_max_caps_the_residual(self):
        s = sampler(model_gap)
        leaf = A.Leaf(-2.0, -1.2, 1.0, 2.0, 1)
        leaf.refined = True
        leaf.E_T = 99.0                                   # huge step
        leaf.goal = False
        A_T = leaf.area(s.table.t_min, s.table.t_max)
        expected = (A.W_GOAL_DEFAULT * A.E_MAX * math.sqrt(A_T) + A.LAMBDA * A_T)
        self.assertAlmostEqual(s._loss(leaf, [None] * 4), expected, places=9)

    def test_exploration_floor_positive_for_every_active_leaf(self):
        # lambda*A_T keeps every active cell's loss > 0, so no region is ignored
        s = sampler(model_gap)
        active = [l for l in s.tree.terminal_leaves() if l.state == A.ACTIVE]
        self.assertTrue(active)
        for leaf in active:
            self.assertGreater(leaf.loss, 0.0)

    def test_hidden_ridge_eventually_probed(self):
        # a resolution-localized eta ridge -> the cells covering it are activated
        # (high residual) and rank high, so the next wave probes inside the ridge
        def model_ridge(w, r, t):
            rr = 2.0 if w == "natural" else r
            res = (1.0 + (rr + 2.0) / 4.0 * 0.3) * (1.0 + t) ** 0.6
            bump = 0.9 * math.exp(-((res - 2.0) / 0.25) ** 2)   # ridge near 2 mas
            return res, 1.0 + 0.05 * t + bump, 0.05
        s = sampler(model_ridge)
        plan = s.plan_wave(cap=999)
        # some proposal lands at a resolution within the ridge (1.6 .. 2.4 mas)
        near = 0
        for (w, r, t) in plan.proposals:
            res = model_ridge(w, r, t)[0]
            if 1.5 < res < 2.5:
                near += 1
        self.assertGreater(near, 0, "the hidden ridge was never probed")


# --------------------------------------------------------------------------- #
# 12. conforming closure / 2:1 balance geometry

class TestBalanceClosure(unittest.TestCase):

    def test_edge_adjacent_detection(self):
        s = sampler(model_smooth)
        a = A.Leaf(-2.0, -1.2, 1.0, 2.0, 0)
        b = A.Leaf(-1.2, -0.4, 1.0, 2.0, 0)              # shares the u=-1.2 edge
        c = A.Leaf(0.4, 1.2, 1.0, 2.0, 0)               # disjoint in robust
        self.assertTrue(s._edge_adjacent(a, b))
        self.assertFalse(s._edge_adjacent(a, c))

    def test_closure_pulls_in_coarser_neighbor(self):
        # a synthetic tree: one deep leaf next to a shallow neighbor -> closure
        s = sampler(model_smooth)
        deep = A.Leaf(-1.2, -0.8, 1.0, 1.4, 2)
        coarse = A.Leaf(-0.8, -0.4, 1.0, 2.0, 0)         # 2 levels coarser, adjacent
        far = A.Leaf(1.2, 2.0, 1.0, 2.0, 0)
        closure = s._balance_closure(deep, [deep, coarse, far])
        self.assertIn(coarse, closure)
        self.assertNotIn(far, closure)


# --------------------------------------------------------------------------- #
# 13. CLI contract

class TestCLI(unittest.TestCase):

    def test_measuring_mode_runs_via_wave_loop(self):
        # main() without --plan-only now runs the REAL measuring driver (task
        # 2e) -- the old "not built yet" exit-2 placeholder is gone.  Patch
        # A.Sweep so the CLI wiring is exercised with NO real CASA/tclean
        # work: run_wave_loop's default (sweep=None) branch does
        # `sweep = Sweep(subarray)`, looking up the MODULE-level name at call
        # time, so patching A.Sweep here is enough -- this must NEVER call
        # main() in measuring mode without this patch (it would try to image
        # for real).
        rows = synth_rows(model_gap, "core")

        class _StubSweep(FakeSweep):
            def __init__(self, subarray):
                super().__init__(subarray, model_gap, list(rows))

        old_sweep, old_stdout = A.Sweep, sys.stdout
        A.Sweep = _StubSweep
        buf = io.StringIO()
        sys.stdout = buf
        try:
            rc = A.main(["core", "--budget", "60"])
        finally:
            sys.stdout = old_stdout
            A.Sweep = old_sweep
        self.assertEqual(rc, 0)
        text = buf.getvalue()
        self.assertIn("adaptive: +", text)
        self.assertIn("stopped:", text)

    def test_plan_only_report_runs(self):
        # drive the report on a synthetic sampler (no real CSV / CASA needed)
        s = sampler(model_gap)
        buf = io.StringIO()
        plan = A.plan_only_report(s, out=buf)
        text = buf.getvalue()
        self.assertIn("adaptive sampler -- plan-only", text)
        self.assertIn("mode: retrofit", text)
        self.assertIn("next wave", text)
        self.assertEqual(plan.kind, "refine")

    def test_manifest_hash_is_stable(self):
        self.assertEqual(A.manifest_hash(), A.manifest_hash())
        self.assertEqual(len(A.manifest_hash()), 12)


# --------------------------------------------------------------------------- #
# 14. the measuring driver (task 2e): wave loop, budget stop, resumability,
# failed-point handling.  Every case below injects a FakeSweep explicitly --
# run_wave_loop's default (sweep=None) opens a REAL sweep.Sweep and measures
# for real, so it must never be exercised here without one.

class TestMeasuringDriver(unittest.TestCase):

    def test_multiwave_convergence_stops_no_proposals(self):
        # a genuinely "fillable" defect (model_gap's smooth taper law, no
        # discontinuity, plus a resolution-localized bump too big for one
        # wave's batch) needs more than one measuring wave, but settles
        # within the spec's "<=3 waves" budget-arithmetic guidance and stops
        # because there is nothing left to propose -- not because budget ran
        # out.
        base = synth_rows(model_fillable_bump, "core")
        sweep = FakeSweep("core", model_fillable_bump, list(base))
        buf = io.StringIO()
        result = A.run_wave_loop("core", sweep=sweep, mode="retrofit", out=buf)

        self.assertEqual(result["stopped"], "no proposals (converged/classified)")
        self.assertGreater(result["n_waves"], 1, "not exercising multiple waves")
        self.assertLessEqual(result["n_waves"], 3)
        self.assertEqual(result["n_failed"], 0)
        self.assertEqual(result["n_new"], sweep.calls)
        # every measured point is a real new row beyond the warm-start base
        self.assertEqual(len(sweep.rows), len(base) + result["n_new"])
        text = buf.getvalue()
        self.assertIn("wave 1:", text)
        self.assertIn("wave 2:", text)
        self.assertNotIn("wave %d:" % (result["n_waves"] + 1), text)
        self.assertIn("adaptive: +%d points total, stopped: no proposals "
                      "(converged/classified)" % result["n_new"], text)
        # the tail reuses plan_only_report's own format on the final table
        self.assertIn("adaptive sampler -- plan-only", text)
        self.assertIn("next wave (refine): 0 units, 0 new evals", text)

    def test_audit_cap_reached_shrinks_wave_then_halts(self):
        # a FRESH (empty-table) run whose defect is exactly bilinear, so every
        # activated leaf certifies on its first stencil -- the 30-leaf domain
        # simply needs more evals than the fresh audit cap (140) allows, so
        # the driver's own tracked room (not the defect) is what shrinks a
        # wave and then halts, WITHOUT ever exceeding the cap.
        sweep = FakeSweep("core", model_bilinear_seed)
        buf = io.StringIO()
        result = A.run_wave_loop("core", sweep=sweep, mode="fresh", out=buf)

        self.assertEqual(result["stopped"], "audit cap reached")
        self.assertLessEqual(result["n_new"], A.AUDIT_FRESH)       # never crossed
        self.assertGreaterEqual(result["n_new"], A.AUDIT_FRESH - A.B_MAX * 5)
        self.assertGreaterEqual(result["n_waves"], 3, "cap reached too abruptly "
                                "to show a real shrink-then-halt sequence")
        counts = result["sampler"].state_counts()
        self.assertGreater(counts[A.ACTIVE], 0, "real work should remain -- "
                           "this must NOT look converged")
        self.assertIn("adaptive: +%d points total, stopped: audit cap reached"
                      % result["n_new"], buf.getvalue())

    def test_restart_matches_continuous_run(self):
        # kill the process after exactly one measured wave, then resume from
        # only what a fresh process would see (the rows so far) -- the
        # SECOND run must reach the identical final table a single
        # uninterrupted run would have, proposing exactly what the
        # continuous run's later wave(s) proposed (spec finding #11:
        # "same table -> same next wave").
        base = synth_rows(model_fillable_bump, "core")

        sweep_cont = FakeSweep("core", model_fillable_bump, list(base))
        A.run_wave_loop("core", sweep=sweep_cont, mode="retrofit",
                        out=io.StringIO())
        cont_rows = {k: dict(v) for k, v in sweep_cont.rows.items()}

        sweep_a = FakeSweep("core", model_fillable_bump, list(base))
        result_a = A.run_wave_loop("core", sweep=sweep_a, mode="retrofit",
                                   waves=1, out=io.StringIO())
        self.assertEqual(result_a["n_waves"], 1)
        self.assertLess(len(sweep_a.rows), len(cont_rows),
                        "killed after wave 1 should be short of the final table")

        # "restart": a fresh process/FakeSweep pre-loaded with exactly the
        # rows the killed run had written (no other state survives).
        resumed_rows = [dict(v) for v in sweep_a.rows.values()]
        sweep_b = FakeSweep("core", model_fillable_bump, resumed_rows)
        A.run_wave_loop("core", sweep=sweep_b, mode="retrofit",
                        out=io.StringIO())

        self.assertEqual(set(sweep_b.rows), set(cont_rows))
        for key, row in cont_rows.items():
            self.assertEqual(sweep_b.rows[key], row)

    def test_failed_point_counted_not_retried_no_crash(self):
        # target a point the very first wave will genuinely propose (so the
        # failure lands inside real, exercised work, not an untouched
        # corner), force it to fail, and confirm: it is tallied, it is never
        # re-attempted (present() excludes it from every later _stencil_new),
        # and the ONE leaf it strands does not stop the rest of the map
        # (model_gap otherwise dominance/certifies quickly) from converging.
        base = synth_rows(model_gap, "core")
        dry_sweep = FakeSweep("core", model_gap, list(base))
        dry_sampler = A._rebuild_sampler("core", dry_sweep, "retrofit", None, None)
        dry_plan = dry_sampler.plan_wave()
        self.assertGreater(dry_plan.n_new, 0)
        poison = dry_plan.proposals[0]
        poison_key = point_key(*poison)

        sweep = FakeSweep("core", model_gap, list(base), fail_keys={poison_key})
        buf = io.StringIO()
        result = A.run_wave_loop("core", sweep=sweep, mode="retrofit", out=buf)

        self.assertGreaterEqual(result["n_failed"], 1)
        self.assertEqual(sweep.rows[poison_key]["status"], "failed")
        self.assertEqual(result["stopped"], "no proposals (converged/classified)")

        # a second, independent pass over the SAME sweep must not re-attempt
        # the failed point (or anything else -- the map already converged)
        calls_before = sweep.calls
        A.run_wave_loop("core", sweep=sweep, mode="retrofit", out=io.StringIO())
        self.assertEqual(sweep.calls, calls_before)
        self.assertEqual(sweep.rows[poison_key]["status"], "failed")


if __name__ == "__main__":
    unittest.main()

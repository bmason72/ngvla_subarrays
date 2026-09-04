"""
Tests for the display-only curve-smoothing layer in curvegen/make_report.py
(the astronomer's "more reliably smooth connecting interpolations" request,
21 Jul 2026): a bounded, structure-preserving PCHIP smoother applied AFTER
build_curve, producing a parallel eta array that report_template.html draws
for a curve's connecting line only -- markers/tooltips/dots/gap-breaks keep
reading the raw points, and build_curve/sample_from_row are untouched.

make_report.py has no CASA dependency (config.py + sa_select.envelope only
need numpy), so this imports it directly, same as tests/test_envelope.py.
Run from the repository root:

    python3 -m unittest tests.test_report_smoothing
"""

import os
import sys
import unittest

import numpy as np

CURVEGEN = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "curvegen")
sys.path.insert(0, CURVEGEN)

import make_report as mr  # noqa: E402


def curve(res, eta):
    """A minimal build_curve()-shaped point list (only the two fields the
    smoother reads)."""
    return [dict(res=r, eta=e) for r, e in zip(res, eta)]


class TestPchipCore(unittest.TestCase):
    """_pchip_slopes / _pchip_eval: the shape-preserving Fritsch-Carlson
    cubic underneath the smoother, tested on its own terms (arbitrary
    monotone x, y -- not necessarily log-resolution/eta)."""

    def test_exact_at_knots(self):
        xk = np.array([0.0, 1.0, 2.5, 4.0])
        yk = np.array([1.0, 1.4, 1.1, 2.0])
        d = mr._pchip_slopes(xk, yk)
        got = mr._pchip_eval(xk, yk, d, xk)
        np.testing.assert_allclose(got, yk, atol=1e-10)

    def test_two_knots_is_a_straight_line(self):
        xk = np.array([0.0, 3.0])
        yk = np.array([1.0, 2.5])
        d = mr._pchip_slopes(xk, yk)
        xf = np.linspace(0.0, 3.0, 7)
        got = mr._pchip_eval(xk, yk, d, xf)
        np.testing.assert_allclose(got, 1.0 + xf * 0.5, atol=1e-10)

    def test_monotone_data_gives_monotone_no_overshoot(self):
        xk = np.array([0.0, 0.5, 1.3, 2.0, 3.5])
        yk = np.array([1.0, 1.2, 1.9, 2.4, 2.5])       # strictly increasing
        d = mr._pchip_slopes(xk, yk)
        xf = np.linspace(xk[0], xk[-1], 400)
        yf = mr._pchip_eval(xk, yk, d, xf)
        self.assertTrue(np.all(np.diff(yf) >= -1e-9), "not monotone")
        idx = np.clip(np.searchsorted(xk, xf, side="right") - 1,
                       0, len(xk) - 2)
        lo = np.minimum(yk[idx], yk[idx + 1])
        hi = np.maximum(yk[idx], yk[idx + 1])
        self.assertTrue(np.all(yf >= lo - 1e-9), "undershoot below a knot pair")
        self.assertTrue(np.all(yf <= hi + 1e-9), "overshoot beyond a knot pair")


class TestSegmentation(unittest.TestCase):
    """_segment_breaks: splits on the template's own >1.055 gap rule and on a
    genuine >0.20 eta step; a real cliff must stay a sharp step, unsoftened."""

    def test_splits_on_resolution_gap(self):
        res = np.array([1.00, 1.01, 1.30, 1.31])       # 1.30/1.01 ~= 1.287
        eta = np.array([1.00, 1.01, 1.02, 1.03])
        self.assertEqual(mr._segment_breaks(res, eta), [(0, 1), (2, 3)])

    def test_no_split_just_under_the_gap_ratio(self):
        res = np.array([1.00, 1.01, 1.054 * 1.01])     # ratio just < 1.055
        eta = np.array([1.00, 1.01, 1.02])
        self.assertEqual(mr._segment_breaks(res, eta), [(0, 2)])

    def test_splits_on_eta_step(self):
        res = np.array([1.00, 1.01, 1.02, 1.03])
        eta = np.array([1.00, 1.02, 1.30, 1.31])       # |1.30-1.02| = 0.28
        self.assertEqual(mr._segment_breaks(res, eta), [(0, 1), (2, 3)])

    def test_cliff_stays_a_sharp_step_in_smooth_array(self):
        # two independently-smoothable >=4-point runs either side of one real
        # 0.25 step; the raw resolution grid has no gap across the step, so
        # the template still draws a connecting line there -- it must stay
        # as sharp in the smooth array as it is in the raw one.
        res = 1.0 * 1.01 ** np.arange(12)
        eta = np.array([1.00, 1.05, 0.98, 1.03,          # left run, wiggly
                        1.28, 1.33, 1.26, 1.31,           # +0.25 step, wiggly
                        1.29, 1.34, 1.27, 1.32])
        smooth, _stats = mr.smooth_curve(curve(res, eta))
        self.assertAlmostEqual(smooth[3], eta[3], places=6)
        self.assertAlmostEqual(smooth[4], eta[4], places=6)
        self.assertGreater(smooth[4] - smooth[3], 0.20)


class TestBounds(unittest.TestCase):
    """smooth_curve's iterative bound enforcement: max|smooth-raw| <= 0.03,
    the tighter 0.02 "optimistic" (smooth understating raw) bound, worst-point
    insertion terminates, and short segments pass through raw untouched."""

    def test_wiggly_curve_stays_within_bounds_and_is_smoother(self):
        n = 60
        res = 1.0 * 1.01 ** np.arange(n)               # gap-free log grid
        x = np.log10(res)
        baseline = 1.0 + 0.4 * (x - x[0]) / (x[-1] - x[0])
        rng = np.random.default_rng(42)
        wiggle = rng.uniform(-0.09, 0.09, n)
        wiggle[[0, -1]] = 0.0
        eta = baseline + wiggle
        smooth, stats = mr.smooth_curve(curve(res, eta))

        self.assertLessEqual(stats["max_abs"], mr.SMOOTH_MAX_ABS + 1e-9)
        self.assertLessEqual(stats["max_optimistic"],
                             mr.SMOOTH_MAX_OPTIMISTIC + 1e-9)
        diff = np.asarray(smooth) - eta
        self.assertLessEqual(np.max(np.abs(diff)), mr.SMOOTH_MAX_ABS + 1e-9)
        self.assertLessEqual(np.max(np.maximum(0.0, -diff)),
                             mr.SMOOTH_MAX_OPTIMISTIC + 1e-9)

        # it should visibly de-zigzag: far fewer direction reversals than raw
        raw_dd, smooth_dd = np.diff(eta), np.diff(smooth)
        raw_reversals = int(np.sum(raw_dd[:-1] * raw_dd[1:] < 0))
        smooth_reversals = int(np.sum(smooth_dd[:-1] * smooth_dd[1:] < 0))
        self.assertLess(smooth_reversals, raw_reversals)

    def test_worst_point_insertion_terminates_on_adversarial_input(self):
        # alternating +/-0.09 offsets: the worst case for knot insertion
        # (every interior point is its own local extremum) -- must still
        # converge to a bounded fit rather than looping or raising.
        n = 30
        res = 1.0 * 1.02 ** np.arange(n)
        eta = 2.0 + 0.09 * (-1.0) ** np.arange(n)
        smooth, stats = mr.smooth_curve(curve(res, eta))
        self.assertEqual(len(smooth), n)
        self.assertLessEqual(stats["max_abs"], mr.SMOOTH_MAX_ABS + 1e-9)
        self.assertLessEqual(stats["max_optimistic"],
                             mr.SMOOTH_MAX_OPTIMISTIC + 1e-9)

    def test_short_segments_pass_through_raw(self):
        # big gaps isolate a length-1, a length-3, and a length-1 segment --
        # all under SMOOTH_MIN_SEGMENT (4), so every point must stay raw.
        res = np.array([1.0, 10.0, 10.2, 10.4, 100.0])
        eta = np.array([1.0, 1.5, 1.6, 1.4, 3.0])
        smooth, stats = mr.smooth_curve(curve(res, eta))
        np.testing.assert_allclose(smooth, eta, atol=1e-9)
        self.assertEqual(stats["max_abs"], 0.0)

    def test_fit_segment_falls_back_to_raw_if_it_cannot_converge(self):
        # a duplicate x whose y is far enough from its neighbors to force it
        # in as a knot defeats the chord/slope math (division by zero): the
        # segment-level fallback must hand back the untouched raw values
        # rather than propagating NaN/inf into the payload.  (Real curves
        # never hit this -- build_curve's grid is strictly increasing -- but
        # the fallback is load-bearing enough to test directly.)
        x = np.array([0.0, 0.0, 1.0, 2.0])
        y = np.array([1.0, 1.9, 1.3, 1.1])
        smooth, ok = mr._fit_segment(x, y)
        self.assertFalse(ok)
        np.testing.assert_allclose(smooth, y)


class TestMaterialExtremaPreserved(unittest.TestCase):
    """A local bump/dip with prominence above SMOOTH_EXTREMUM_PROMINENCE is
    real structure -- refine's job to remove, never the display smoother's --
    so it must survive in the smooth array essentially unchanged."""

    def test_prominent_bump_survives(self):
        n = 10
        res = 1.0 * 1.015 ** np.arange(n)
        x = np.log10(res)
        eta = 1.0 + 0.5 * (x - x[0]) / (x[-1] - x[0])   # a straight ramp
        bump_idx = 5
        eta = eta.copy()
        eta[bump_idx] += 0.08                            # prominence 0.08 > 0.05
        smooth, _stats = mr.smooth_curve(curve(res, eta))
        self.assertAlmostEqual(smooth[bump_idx], eta[bump_idx], places=6)

    def test_prominent_dip_survives(self):
        n = 10
        res = 1.0 * 1.015 ** np.arange(n)
        x = np.log10(res)
        eta = 2.0 - 0.5 * (x - x[0]) / (x[-1] - x[0])   # a straight decline
        dip_idx = 4
        eta = eta.copy()
        eta[dip_idx] -= 0.08
        smooth, _stats = mr.smooth_curve(curve(res, eta))
        self.assertAlmostEqual(smooth[dip_idx], eta[dip_idx], places=6)


class TestPayloadWiring(unittest.TestCase):
    """build_payload's new imaging_smooth/pointsource_smooth keys: aligned
    1:1 with every curve (incl. every skirt setpoint), and no existing key
    disturbed.  Runs the real default (revF/track) payload build once."""

    @classmethod
    def setUpClass(cls):
        cls.data = mr.build_payload()

    def test_existing_keys_unchanged(self):
        # the exact key set build_payload returned before this feature
        # (git history, curvegen/make_report.py pre-smoothing) plus exactly
        # the two new parallel-array keys -- nothing renamed or dropped.
        before = {"order", "las", "caps", "samples", "skirt_setpoints",
                  "s0_default", "imaging", "pointsource", "counts",
                  "heatmaps", "profile", "sens", "qa", "combo"}
        self.assertTrue(before <= set(self.data.keys()))
        self.assertEqual(set(self.data.keys()) - before,
                         {"imaging_smooth", "pointsource_smooth",
                          "psf_exported", "validation_counts",
                          "psf_metrics", "confusion_model"})

    def test_validation_counts_partition_displayed_samples(self):
        for name, points in self.data["samples"].items():
            counts = self.data["validation_counts"][name]
            self.assertEqual(sum(counts.values()), len(points))
            self.assertEqual(
                sum(p["validation"] == "residual-validated" for p in points),
                counts["residual_validated"])

    def test_smooth_arrays_aligned_for_every_curve(self):
        imaging, imaging_smooth = self.data["imaging"], self.data["imaging_smooth"]
        self.assertEqual(set(imaging.keys()), set(imaging_smooth.keys()))
        for s0 in self.data["skirt_setpoints"]:
            self.assertIn(s0, imaging_smooth)
            for name, pts in imaging[s0].items():
                self.assertIn(name, imaging_smooth[s0])
                self.assertEqual(len(imaging_smooth[s0][name]), len(pts))
                for v in imaging_smooth[s0][name]:
                    self.assertTrue(np.isfinite(v))

        pointsource, ps_smooth = self.data["pointsource"], self.data["pointsource_smooth"]
        self.assertEqual(set(pointsource.keys()), set(ps_smooth.keys()))
        for name, pts in pointsource.items():
            self.assertEqual(len(ps_smooth[name]), len(pts))

    def test_points_dicts_untouched(self):
        # the point dicts themselves gained no "smooth" key -- the payload
        # attaches the smoothed arrays in a PARALLEL dict, not inline.
        s0 = self.data["s0_default"]
        for pts in self.data["imaging"][s0].values():
            for p in pts:
                self.assertNotIn("smooth", p)

    def test_every_curve_is_within_the_hard_bounds(self):
        # the real contract, not just the (much looser) 0.06 loud-warning
        # threshold: every imaging curve (every skirt setpoint) and every
        # pointsource curve must sit within SMOOTH_MAX_ABS / _OPTIMISTIC.
        tol = 1e-9
        checked = 0
        for s0, curves in self.data["imaging"].items():
            for name, pts in curves.items():
                if not pts:
                    continue
                smooth = self.data["imaging_smooth"][s0][name]
                diff = np.array([sm - p["eta"] for sm, p in zip(smooth, pts)])
                self.assertLessEqual(np.max(np.abs(diff)),
                                     mr.SMOOTH_MAX_ABS + tol,
                                     "imaging[%s]/%s exceeded the hard abs bound"
                                     % (s0, name))
                self.assertLessEqual(np.max(np.maximum(0.0, -diff)),
                                     mr.SMOOTH_MAX_OPTIMISTIC + tol,
                                     "imaging[%s]/%s exceeded the hard optimistic bound"
                                     % (s0, name))
                checked += 1
        for name, pts in self.data["pointsource"].items():
            if not pts:
                continue
            smooth = self.data["pointsource_smooth"][name]
            diff = np.array([sm - p["eta"] for sm, p in zip(smooth, pts)])
            self.assertLessEqual(np.max(np.abs(diff)), mr.SMOOTH_MAX_ABS + tol,
                                 "pointsource/%s exceeded the hard abs bound" % name)
            self.assertLessEqual(np.max(np.maximum(0.0, -diff)),
                                 mr.SMOOTH_MAX_OPTIMISTIC + tol,
                                 "pointsource/%s exceeded the hard optimistic bound"
                                 % name)
            checked += 1
        self.assertGreater(checked, 0)          # the assertions above actually ran


def _run_with_poisoned_segment_fit(poison):
    """smooth_curve() on a tiny, otherwise-clean curve, but with
    make_report._fit_segment monkeypatched so its ONE segment "succeeds"
    (ok=True) with a value poisoned by `poison(raw_eta) -> poisoned_eta`.
    Exercises smooth_curve's OWN aggregate hard-bound check -- the guard that
    must still catch a bad result even if a segment fitter is (hypothetically,
    via future drift/a bug) wrong about its own success."""
    n = 8
    res = 1.0 * 1.01 ** np.arange(n)
    eta = 1.0 + 0.01 * np.arange(n, dtype=float)
    points = curve(res, eta)
    original = mr._fit_segment
    mr._fit_segment = lambda x, y: (poison(y), True)
    try:
        smooth, stats = mr.smooth_curve(points, label="poisoned")
    finally:
        mr._fit_segment = original
    return smooth, stats, eta


class TestHardenedFallbackGuard(unittest.TestCase):
    """The final aggregate guard in smooth_curve: even a segment fitter that
    reports ok=True must not be trusted blindly -- non-finite output, or any
    output past the advertised 0.03/0.02 contract, forces a whole-curve
    fallback to raw (with stats reset to a clean 0.0/0.0), and only the truly
    extreme (>0.06) case additionally gets the loud stderr warning."""

    def test_non_finite_result_falls_back_to_raw(self):
        def poison(y):
            bad = y.copy()
            bad[len(bad) // 2] = float("nan")
            return bad
        smooth, stats, eta = _run_with_poisoned_segment_fit(poison)
        np.testing.assert_allclose(smooth, eta)
        self.assertEqual(stats, dict(max_abs=0.0, max_optimistic=0.0))

    def test_infinite_result_falls_back_to_raw(self):
        def poison(y):
            bad = y.copy()
            bad[0] = float("inf")
            return bad
        smooth, stats, eta = _run_with_poisoned_segment_fit(poison)
        np.testing.assert_allclose(smooth, eta)
        self.assertEqual(stats, dict(max_abs=0.0, max_optimistic=0.0))

    def test_moderate_abs_violation_below_the_old_warn_threshold_falls_back(self):
        # +0.045: past the hard 0.03 bound, but under the old-and-still-loud
        # 0.06 threshold -- exactly the silent-drift gap this guard closes.
        def poison(y):
            bad = y.copy()
            bad[len(bad) // 2] += 0.045
            return bad
        smooth, stats, eta = _run_with_poisoned_segment_fit(poison)
        np.testing.assert_allclose(smooth, eta)
        self.assertEqual(stats, dict(max_abs=0.0, max_optimistic=0.0))

    def test_moderate_optimistic_violation_falls_back(self):
        # -0.025: smooth sits below raw (understating eta) by more than the
        # tighter 0.02 optimistic bound, while the general abs deviation
        # (0.025) still satisfies the looser 0.03 bound -- isolates the
        # optimistic-specific check.
        def poison(y):
            bad = y.copy()
            bad[len(bad) // 2] -= 0.025
            return bad
        smooth, stats, eta = _run_with_poisoned_segment_fit(poison)
        np.testing.assert_allclose(smooth, eta)
        self.assertEqual(stats, dict(max_abs=0.0, max_optimistic=0.0))

    def test_within_bounds_result_is_not_rejected(self):
        # a sanity check on the guard itself: a genuinely valid (if
        # deliberately non-raw) result must be accepted, not just any
        # "poisoned" one rejected.
        def poison(y):
            bad = y.copy()
            bad[len(bad) // 2] += 0.01
            return bad
        smooth, stats, eta = _run_with_poisoned_segment_fit(poison)
        self.assertAlmostEqual(smooth[len(smooth) // 2],
                               eta[len(eta) // 2] + 0.01, places=9)
        self.assertAlmostEqual(stats["max_abs"], 0.01, places=9)


if __name__ == "__main__":
    unittest.main()

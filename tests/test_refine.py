"""
CASA-free tests for the curve-refinement escalation ladder (curvegen/refine.py).

The measurement is mocked by a FakeSweep whose run_point computes (res, eta,
skirt) from an analytic model and records rows in the real sweep schema (reuse
point_key), so refine() runs end to end without CASA.  The models reproduce the
diagnosed defect classes:

  * a taper-onset cliff  -> E2 must classify a sampled resolution discontinuity
                            WITHOUT exhausting the budget;
  * a fillable sawtooth  -> E2 must fill it (final worst step <= max_step);
  * a homogeneous 2x gap -> E3 gap chasing + E2 must fill it;
  * a resolution bump    -> E4 must target it and respect the 25% budget cap.

Plus unit tests for the secant math and its rejection rules, the progressive
log-midpoint ordering, the shared display-trim contract, and budget/restart
accounting.

Run from the repository root:

    python3 -m unittest tests.test_refine
"""

import importlib
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "curvegen"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_refine():
    try:
        return importlib.import_module("refine")
    except ImportError as e:                     # pragma: no cover
        raise unittest.SkipTest("curvegen/refine.py needs CASA here: %s" % e)


refine = _load_refine()
from make_report import build_curve, sample_from_row          # noqa: E402
from sweep import point_key                                    # noqa: E402

ROBUSTS = [round(-2.0 + 0.4 * i, 2) for i in range(11)]        # -2 .. +2


class FakeSweep:
    """A drop-in stand-in for sweep.Sweep whose run_point evaluates an analytic
    model instead of tclean.  Rows use the real sweep schema and are keyed by
    point_key, so refine.samples_from and build_curve treat it like the real
    thing.  The base lattice (natural + briggs robusts x base tapers) is seeded
    at construction, reproducing a coarse post-sweep grid with a defect."""

    def __init__(self, subarray, model, base_tapers):
        self.subarray = subarray
        self.model = model
        self.rows = {}
        self.calls = 0
        self.run_point("natural", 2.0, 0.0)
        for t in base_tapers:
            if t > 0:
                self.run_point("natural", 2.0, t)
        for r in ROBUSTS:
            for t in base_tapers:
                self.run_point("briggs", r, t)

    def run_point(self, weighting, robust, taper_mas):
        key = point_key(weighting, robust, taper_mas)
        if key in self.rows:
            return self.rows[key]
        self.calls += 1
        out = self.model(weighting, robust, taper_mas)
        if out is None:
            row = dict(subarray=self.subarray, weighting=weighting,
                       robust=robust, taper_mas=taper_mas, res_geo_arcsec="",
                       sigma_dirty="", skirt="", status="failed")
        else:
            res_mas, eta, skirt = out
            row = dict(subarray=self.subarray, weighting=weighting,
                       robust=robust, taper_mas=taper_mas,
                       res_geo_arcsec=res_mas / 1e3, sigma_dirty=eta,
                       skirt=skirt, status="ok")
        self.rows[key] = row
        return row

    def inject(self, weighting, robust, taper_mas, sigma, skirt, status,
               res_mas=1000.0):
        """Record a raw row directly (for the contract and classification
        tests).  res_mas defaults to 1000 (res_geo_arcsec 1.0)."""
        self.rows[point_key(weighting, robust, taper_mas)] = dict(
            subarray=self.subarray, weighting=weighting, robust=robust,
            taper_mas=taper_mas, res_geo_arcsec=res_mas / 1e3, sigma_dirty=sigma,
            skirt=skirt, status=status)

    def measured(self, weighting, robust, taper_mas):
        row = self.rows.get(point_key(weighting, robust, taper_mas))
        return row if row and row["status"] == "ok" else None


# --------------------------------------------------------------------------- #
# analytic defect models (validated against build_curve)

def model_cliff(w, r, t):
    """Taper-onset cliff: the untapered branch runs res 2.0..3.0 at eta ~1;
    ANY taper snaps res to >=4.0 at eta ~2.6, so there is NO interior
    resolution between 3.0 and 4.0 (an in-band jump, ratio 1.33)."""
    rr = 2.0 if w == "natural" else r
    if t < 1e-9:
        return 2.0 + (rr + 2.0) / 4.0 * 1.00, 1.0 + 0.02 * (2.0 - rr) / 4.0, 0.05
    return max(4.0, 4.0 * (t / 2.0) ** 0.4), 2.58 * max(1.0, (t / 2.0) ** 0.2), 0.05


def model_gap(w, r, t):
    """A single ~2x resolution hole between the untapered beam and the first
    base taper, with a genuinely fillable smooth interior."""
    rr = 2.0 if w == "natural" else r
    res0 = 1.0 + (rr + 2.0) / 4.0 * 0.4
    return res0 * (1.0 + t) ** 0.9, 1.0 + 0.12 * t, 0.05


def model_sawtooth(w, r, t):
    """A coarse taper grid leaves several fillable holes (a sawtooth in the
    winner curve); interior tapers close them."""
    rr = 2.0 if w == "natural" else r
    res0 = 1.0 + (rr + 2.0) / 4.0 * 0.3
    return res0 * (1.0 + t) ** 0.8, 1.0 + 0.12 * t, 0.05


def model_bump(w, r, t):
    """A resolution-localized eta penalty (a PSF-quality dip near res 2.2) that
    no (robust, taper) combination can escape -> a genuine bump in the curve."""
    rr = 2.0 if w == "natural" else r
    res = (1.0 + (rr + 2.0) / 4.0 * 0.5) * (1.0 + t) ** 0.7
    return res, 1.0 + 0.05 * t + 0.6 * math.exp(-((res - 2.2) / 0.35) ** 2), 0.05


def curve_stats(sweep, s_max=None, max_step=0.25):
    """(worst in-band eta step, worst adjacent res ratio, n curve points)."""
    curve = build_curve(refine.samples_from(sweep), s_max)
    worst = max((abs(b["eta"] - a["eta"]) for a, b in zip(curve, curve[1:])
                 if b["res"] / a["res"] <= refine.GAP_RATIO), default=0.0)
    ratio = max((b["res"] / a["res"] for a, b in zip(curve, curve[1:])),
                default=1.0)
    return worst, ratio, len(curve)


# --------------------------------------------------------------------------- #
# 1-4: end-to-end refine() convergence / classification

class TestEndToEnd(unittest.TestCase):

    def test_cliff_classified_without_exhausting_budget(self):
        sweep = FakeSweep("core", model_cliff, [0.0, 2.0, 4.0, 8.0])
        before = sweep.calls
        counts = refine.refine("core", sweep=sweep, rounds=4, budget=60)
        new_points = sweep.calls - before
        self.assertGreaterEqual(counts["confirmed"], 1,
                                "cliff not classified as a discontinuity")
        # the interval is classified after a single stage, so the budget is
        # nowhere near exhausted (a handful of probes, not 60)
        self.assertLess(new_points, 60)
        self.assertLessEqual(new_points, 16)

    def test_sawtooth_filled_below_max_step(self):
        sweep = FakeSweep("core", model_sawtooth, [0.0, 2.0, 5.0])
        w0, g0, _ = curve_stats(sweep)
        self.assertGreater(g0, refine.GAP_RATIO)        # starts holey
        refine.refine("core", sweep=sweep, rounds=6, budget=120)
        w1, g1, _ = curve_stats(sweep)
        self.assertLessEqual(w1, 0.25, "worst in-band step not filled")
        self.assertLessEqual(g1, refine.GAP_RATIO, "a hole survived")

    def test_homogeneous_gap_filled(self):
        sweep = FakeSweep("core", model_gap, [0.0, 1.16, 4.0, 12.0])
        _, g0, _ = curve_stats(sweep)
        self.assertGreater(g0, refine.GAP_RATIO)        # a real hole exists
        # "core" is not in BEAM_CAP_ARCSEC -> homogeneous -> E3 (E2-only)
        self.assertNotIn("core", refine.BEAM_CAP_ARCSEC)
        refine.refine("core", sweep=sweep, rounds=6, budget=120)
        _, g1, _ = curve_stats(sweep)
        self.assertLessEqual(g1, refine.GAP_RATIO, "homogeneous gap not filled")

    def test_bump_targeted_and_capped(self):
        budget = 40
        sweep = FakeSweep("core", model_bump,
                          [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0])
        curve = build_curve(refine.samples_from(sweep), None)
        self.assertTrue(refine.find_bumps(curve, "ptsrc", refine.DEFAULT_BUMP_MIN),
                        "bump not detected on the base curve")
        before = sweep.calls
        counts = refine.refine("core", sweep=sweep, rounds=4, budget=budget)
        new_points = sweep.calls - before
        self.assertGreater(counts["bumps"], 0, "E4 did not target the bump")
        cap = int(round(refine.BUMP_BUDGET_FRACTION * budget))
        self.assertLessEqual(new_points, cap,
                             "bumps exceeded the %d-point (25%%) cap" % cap)


# --------------------------------------------------------------------------- #
# 5: secant math and rejection rules

class TestSecant(unittest.TestCase):

    def test_taper_slice_log_space(self):
        # taper is log-linear in log(res): taper 1@res2, taper 2@res4; res_t=3
        val = refine.secant_on_slice("taper", [(1.0, 2.0), (2.0, 4.0)],
                                     3.0, (1.0, 2.0))
        self.assertAlmostEqual(val, 1.5, places=3)

    def test_robust_slice_linear(self):
        # robust is linear in log(res): robust -2@res2, robust 0@res4; res_t=3
        val = refine.secant_on_slice("robust", [(-2.0, 2.0), (0.0, 4.0)],
                                     3.0, (-2.0, 0.0))
        self.assertAlmostEqual(val, -0.83, places=2)

    def test_reject_duplicate_resolutions(self):
        self.assertIsNone(refine.secant_on_slice(
            "taper", [(1.0, 2.0), (2.0, 2.0)], 2.0, (1.0, 2.0)))

    def test_reject_non_monotone(self):
        self.assertIsNone(refine.secant_on_slice(
            "taper", [(1.0, 2.0), (2.0, 4.0), (3.0, 3.0)], 3.0, (1.0, 3.0)))

    def test_reject_out_of_bracket(self):
        # secant lands at taper ~1.5 but the endpoint bracket is (1.0, 1.2)
        self.assertIsNone(refine.secant_on_slice(
            "taper", [(1.0, 2.0), (2.0, 4.0)], 3.0, (1.0, 1.2)))

    def test_target_skips_cliff(self):
        a = dict(res=3.0, eta=1.0, weighting="briggs", robust=0.0, taper=0.0)
        b = dict(res=4.0, eta=2.0, weighting="briggs", robust=0.0, taper=2.0)
        self.assertIsNone(refine.secant_target(a, b, []))

    def test_target_skips_weighting_change(self):
        a = dict(res=3.0, eta=1.0, weighting="natural", robust=None, taper=1.0)
        b = dict(res=4.0, eta=2.0, weighting="briggs", robust=0.0, taper=1.0)
        self.assertIsNone(refine.secant_target(a, b, []))

    def test_target_taper_slice_hit(self):
        a = dict(res=2.0, eta=1.0, weighting="briggs", robust=0.0, taper=1.0)
        b = dict(res=4.0, eta=2.0, weighting="briggs", robust=0.0, taper=2.0)
        samples = [dict(res=2.0, eta=1.0, skirt=0.05, weighting="briggs",
                        robust=0.0, taper=1.0),
                   dict(res=4.0, eta=2.0, skirt=0.05, weighting="briggs",
                        robust=0.0, taper=2.0)]
        key = refine.secant_target(a, b, samples)
        self.assertIsNotNone(key)
        w, r, t = key
        self.assertEqual((w, r), ("briggs", 0.0))       # fixed axis = robust 0
        self.assertTrue(1.0 < t < 2.0)                  # inside the taper bracket


# --------------------------------------------------------------------------- #
# 6: progressive log-midpoint ordering

class TestProgressiveMidpoints(unittest.TestCase):

    def test_midpoint_first_and_bfs(self):
        pts = refine.progressive_log_midpoints(1.0, 16.0, 4)
        self.assertEqual(len(pts), 4)
        self.assertAlmostEqual(pts[0], 4.0, places=3)    # bracket midpoint first
        self.assertIn(2.0, pts)                          # then the sub-midpoints
        self.assertIn(8.0, pts)

    def test_deterministic(self):
        self.assertEqual(refine.progressive_log_midpoints(0.1, 5.0, 8),
                         refine.progressive_log_midpoints(0.1, 5.0, 8))

    def test_unique_interior_and_rounded(self):
        pts = refine.progressive_log_midpoints(0.5, 20.0, 8)
        self.assertEqual(len(pts), len(set(pts)))        # unique
        for t in pts:
            self.assertTrue(0.5 < t < 20.0)              # strictly interior
            self.assertEqual(t, round(t, 3))             # point_key precision

    def test_k_counts_unique_after_rounding(self):
        # a bracket so tight that 3-dp rounding collapses most candidates
        pts = refine.progressive_log_midpoints(1.000, 1.004, 8)
        self.assertEqual(len(pts), len(set(pts)))
        self.assertLess(len(pts), 8)                     # fewer than K survive


# --------------------------------------------------------------------------- #
# 7: shared display-trim contract (sample_from_row + samples_from parity)

class TestContract(unittest.TestCase):

    def test_eta_trim_boundaries(self):
        base = dict(skirt=0.05, weighting="briggs", robust=0.0, taper_mas=1.0,
                    capped=False)
        self.assertIsNotNone(sample_from_row(res_mas=1.0, eta=4.9, **base))
        self.assertIsNotNone(sample_from_row(res_mas=1.0, eta=5.0, **base))
        self.assertIsNone(sample_from_row(res_mas=1.0, eta=5.001, **base))

    def test_nan_eta_dropped(self):
        self.assertIsNone(sample_from_row(
            res_mas=1.0, eta=float("nan"), skirt=0.05, weighting="briggs",
            robust=0.0, taper_mas=1.0, capped=False))

    def test_keys_and_capped_flag(self):
        s = sample_from_row(res_mas=2.0, eta=1.5, skirt=0.1, weighting="briggs",
                            robust=-0.4, taper_mas=3.0, capped=True)
        self.assertEqual(set(s), {"res", "eta", "skirt", "weighting", "robust",
                                  "taper", "capped"})
        self.assertEqual((s["res"], s["eta"], s["taper"], s["capped"]),
                         (2.0, 1.5, 3.0, True))

    def test_samples_from_status_and_eta_selection(self):
        sweep = FakeSweep("core", lambda *a: None, [])   # only natural seeded
        # overwrite the natural seed with a clean reference (sigma_nat = 1.0)
        sweep.inject("natural", 2.0, 0.0, sigma=1.0, skirt=0.05, status="ok")
        sweep.inject("briggs", 0.0, 1.0, sigma=1.5, skirt=0.05, status="ok")
        sweep.inject("briggs", 0.0, 2.0, sigma=2.0, skirt=0.05, status="capped")
        sweep.inject("briggs", 0.0, 4.0, sigma=6.0, skirt=0.05, status="ok")
        sweep.inject("briggs", -0.4, 1.0, sigma=1.2, skirt=0.05, status="failed")
        sweep.inject("briggs", -0.4, 2.0, sigma=1.3, skirt=0.05, status="skipped")
        sweep.inject("briggs", 0.4, 1.0, sigma=5.0, skirt=0.05, status="ok")
        samples = refine.samples_from(sweep)
        etas = sorted(round(s["eta"], 3) for s in samples)
        # natural(1.0) + ok(1.5) + capped-anchor(2.0) + ok-at-cap(5.0);
        # dropped: eta 6.0 (>cap), failed, skipped
        self.assertEqual(etas, [1.0, 1.5, 2.0, 5.0])
        self.assertTrue(all("capped" not in s for s in samples))  # historical shape


# --------------------------------------------------------------------------- #
# 8: budget accounting and restart safety

class TestBudgetAndRestart(unittest.TestCase):

    def test_budget_is_respected(self):
        sweep = FakeSweep("core", model_gap, [0.0, 1.16, 4.0, 12.0])
        before = sweep.calls
        refine.refine("core", sweep=sweep, rounds=8, budget=24)
        self.assertLessEqual(sweep.calls - before, 24)

    def test_one_stage_then_classify(self):
        # a cliff classifies after the FIRST stage (<= 2 traces x stage_size),
        # never scanning the whole K x 2 point budget for the interval
        sweep = FakeSweep("core", model_cliff, [0.0, 2.0, 4.0, 8.0])
        before = sweep.calls
        refine.refine("core", sweep=sweep, rounds=4, budget=200)
        stage = max(1, refine.DEFAULT_SCAN_POINTS // 2)
        self.assertLessEqual(sweep.calls - before, 2 * stage)

    def test_restart_proposes_nothing_new(self):
        sweep = FakeSweep("core", model_cliff, [0.0, 2.0, 4.0, 8.0])
        refine.refine("core", sweep=sweep, rounds=4, budget=60)
        settled = sweep.calls
        refine.refine("core", sweep=sweep, rounds=4, budget=60)   # rerun
        self.assertEqual(sweep.calls, settled,
                         "re-running refine measured new points after settling")


# --------------------------------------------------------------------------- #
# FIX 1: E2 classification honours the display-trim contract + skirt setpoint

class TestClassifyContract(unittest.TestCase):
    """A probe classifies an interval only if the report would draw it: eta must
    pass the display trim and, on the imaging curve, skirt <= skirt_max.  An
    ineligible measurement must still COMPLETE its scan level."""

    FINE = dict(res=2.0, eta=1.0)
    COARSE = dict(res=4.0, eta=3.0)                  # chord at res 3.0 ~ 2.17

    def _classify(self, sigma, skirt, skirt_max):
        sweep = FakeSweep("core", lambda *a: None, [])
        sweep.inject("natural", 2.0, 0.0, 1.0, 0.05, "ok")    # sigma_nat = 1.0
        taper = 1.5
        sweep.inject("briggs", 0.0, taper, sigma, skirt, "ok", res_mas=3.0)
        cls = refine._classify_scan(sweep, [("briggs", 0.0)], [taper],
                                    self.FINE, self.COARSE, skirt_max)
        completed = refine._measured_row(sweep, ("briggs", 0.0), taper) is not None
        return cls, completed

    def test_nan_eta_probe_not_evidence_but_completes(self):
        cls, completed = self._classify(float("nan"), 0.05, None)
        self.assertEqual(cls, "confirmed")           # no eligible interior probe
        self.assertTrue(completed)                    # level still sampled

    def test_eta_over_cap_probe_not_evidence_but_completes(self):
        cls, completed = self._classify(6.0, 0.05, None)
        self.assertEqual(cls, "confirmed")
        self.assertTrue(completed)

    def test_imaging_skirt_over_setpoint_not_evidence(self):
        # the SAME interior probe: rejected as imaging evidence (skirt 0.20 >
        # 0.10) but accepted for the point-source curve (no skirt gate)
        cls_img, done_img = self._classify(1.5, 0.20, 0.10)
        cls_ps, done_ps = self._classify(1.5, 0.20, None)
        self.assertEqual(cls_img, "confirmed")
        self.assertEqual(cls_ps, "undersampled")     # 1.5 dips below the chord
        self.assertTrue(done_img and done_ps)

    def test_eligible_interior_is_evidence(self):
        cls, _ = self._classify(1.5, 0.05, 0.10)     # eta<5, skirt<=0.10
        self.assertEqual(cls, "undersampled")


# --------------------------------------------------------------------------- #
# FIX 2: E2 pairs are admitted atomically at budget edges

class TestPairAtomicity(unittest.TestCase):

    def _plan(self, room):
        sweep = FakeSweep("core", model_gap, [0.0, 1.16, 4.0, 12.0])
        samples = refine.samples_from(sweep)
        curves = {label: build_curve(samples, s_max)
                  for label, s_max in refine.CURVE_SPECS}
        ctx = dict(subarray="core", logged=set(),
                   counts=dict(e1=0, e2_scans=0, e2_pts=0, bumps=0,
                               confirmed=0, high_penalty=0))
        return refine.plan_round(sweep, samples, curves, homogeneous=True,
                                 max_step=0.25, scan_points=8,
                                 bump_min_floor=0.05, room=room, bump_room=0,
                                 ctx=ctx)

    def test_single_slot_cannot_split_a_pair(self):
        # every E2 pair here has two unmeasured traces; one slot buys none
        self.assertEqual(len(self._plan(1).points), 0)

    def test_two_slots_admit_the_whole_pair(self):
        pts = self._plan(2).points
        self.assertEqual(len(pts), 2)                 # atomic: 0 or the full pair


# --------------------------------------------------------------------------- #
# FIX 4: CLI validators reject zero / out-of-range knobs

class TestArgValidators(unittest.TestCase):

    def test_positive_int_rejects_zero_and_negative(self):
        import argparse
        self.assertEqual(refine._positive_int("3"), 3)
        for bad in ("0", "-1"):
            with self.assertRaises(argparse.ArgumentTypeError):
                refine._positive_int(bad)

    def test_scan_points_range(self):
        import argparse
        self.assertEqual(refine._scan_points("64"), 64)
        for bad in ("0", "65"):
            with self.assertRaises(argparse.ArgumentTypeError):
                refine._scan_points(bad)

    def test_max_step_must_be_positive(self):
        import argparse
        self.assertEqual(refine._positive_float("0.25"), 0.25)
        for bad in ("0", "-0.1", "nan"):
            with self.assertRaises(argparse.ArgumentTypeError):
                refine._positive_float(bad)

    def test_bump_min_nonnegative(self):
        import argparse
        self.assertEqual(refine._nonneg_float("0"), 0.0)
        for bad in ("-0.01", "nan"):
            with self.assertRaises(argparse.ArgumentTypeError):
                refine._nonneg_float(bad)


if __name__ == "__main__":
    unittest.main()

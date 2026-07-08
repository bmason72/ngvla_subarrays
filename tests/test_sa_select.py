"""
Tests for sa_select.

Run with the CASA python (has numpy/scipy; stdlib unittest only, no pytest):

    /Applications/CASA.app/Contents/MacOS/python3 -m unittest discover -s tests -t .

from the repository root (so `import sa_select` resolves).

Sections:
  A. Validation against memo-121 bootstrap samples (the key suite) -- confirms
     the engine reproduces the memo-121 imaging/point-source choices it was
     bootstrapped from.
  B. Unit/behavior tests against a small synthetic CurveLibrary.
  C. Sensitivity-module round trips.
  D. End-to-end smoke test (PF3(KSG1).1 replay).
"""

import csv
import os
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOTSTRAP_CSV = os.path.join(REPO_ROOT, "sa_select", "data", "bootstrap_curves.csv")

from sa_select import ObservingRequest, select_subarrays, CurveLibrary
from sa_select.schema import SubarrayInfo, CurveSample
from sa_select import heuristics
from sa_select import sensitivity as sens

REF_FREQ_GHZ = 30.0


def _res_at_freq(res30, freq_orig):
    """Undo the 30GHz reference scaling: the resolution this sample actually
    represents at the frequency it was measured at (res(f) = res_30 * 30/f)."""
    return res30 * REF_FREQ_GHZ / freq_orig


# =============================================================================
# A. Validation against memo-121 bootstrap samples
# =============================================================================

class TestMemo121Validation(unittest.TestCase):
    """Hand-picked rows from data/bootstrap_curves.csv, read directly from the
    CSV (independent of curves.py's own loader) and replayed through the
    engine. Each row was checked ahead of time (see PR discussion) to be the
    unique minimum-eta sample in its own beam window, so the round trip is
    exact and not just "some sample in the window matched".

    Rows are (subarray, resolution_arcsec_30ghz, freq_orig_ghz, eta, robust).
    """

    # briggs, skirt <= 0.10 -> imaging-qualifying; spans main / core+spiral / core
    # and a range of frequencies, per the CLAUDE.md validation ask.
    BRIGGS_ROWS = [
        ("main",        0.0133333, 80.0,  3.47, -1.81),  # MainCln:PF3(KSG1).1
        ("main",        0.32,      24.0,  1.70,  0.38),  # MainCln:AC1
        ("main",        0.383333, 115.0,  1.68,  0.52),  # MainCln:NGA8(KSG3.3.3)
        ("core+spiral", 0.466667,  70.0,  1.35,  0.55),  # EPPCln:AC4
        ("core+spiral", 2.7,       40.5,  3.11,  1.81),  # EPPCln:HiZ1(KSG3.3.1).1
        ("core+spiral", 0.103867,  16.4,  1.44, -0.67),  # EPPCln:HiZ7.1
        ("core",        1.09333,   16.4,  1.23,  0.70),  # EPPCln:HiZ1(KSG3.3.1).3
        ("core",        0.766667, 115.0,  1.01,  1.06),  # EPPCln:NGA9
    ]

    # natural samples (no robust); imaging=False so the skirt is not a constraint.
    NATURAL_ROWS = [
        ("main",        0.79844,   24.0, 1.95),  # MainCln:AC6
        ("core+spiral", 0.146745,  40.5, 1.00),  # EPPCln:AC5(KSG2).1
        ("core",        1.09333,   16.4, 1.18),  # EPPCln:HiZ1(KSG3.3.1).3
        ("main",        0.0546612, 16.4, 1.18),  # MainCln:AC5(KSG2).3
    ]

    @classmethod
    def setUpClass(cls):
        cls.library = CurveLibrary()  # the real, shipped bootstrap data

    def test_bootstrap_csv_is_readable_sanity_check(self):
        # Make sure the hand-picked rows really are in the shipped CSV, so the
        # table above can't silently drift from the data file.
        with open(BOOTSTRAP_CSV, newline="") as f:
            rows = list(csv.DictReader(f))
        found = {(r["subarray"], float(r["resolution_arcsec_30ghz"]),
                  float(r["freq_orig_ghz"])) for r in rows}
        for sub, res30, freq, _eta, _robust in self.BRIGGS_ROWS:
            self.assertIn((sub, res30, freq), found)
        for sub, res30, freq, _eta in self.NATURAL_ROWS:
            self.assertIn((sub, res30, freq), found)

    def test_briggs_imaging_samples_reproduced(self):
        """An imaging request built from a memo-121 briggs/sculpted sample
        should come back feasible on the *same* subarray, with the *same*
        robust value and eta matching to within 1%.  memo 121 used the hard
        skirt <= 0.10 criterion, so replay with skirt_relax=False (the
        tool's default now applies the 1-for-1 eta-skirt trade, which can
        legitimately find cheaper beams at slightly larger skirt)."""
        for sub, res30, freq_orig, eta_expect, robust_expect in self.BRIGGS_ROWS:
            with self.subTest(subarray=sub, freq=freq_orig, res30=res30):
                req = ObservingRequest(
                    resolution=_res_at_freq(res30, freq_orig),
                    frequency=freq_orig,
                    imaging=True,
                    skirt_relax=False,
                )
                result = select_subarrays(req, library=self.library)
                cand = next(c for c in result if c.subarray.name == sub)
                self.assertTrue(cand.feasible, msg=cand.reasons)
                self.assertAlmostEqual(cand.eta, eta_expect, delta=0.01 * eta_expect)
                self.assertEqual(cand.robust, robust_expect)
                self.assertEqual(cand.weighting, "briggs")

    def test_natural_point_source_samples_at_least_as_good(self):
        """Point-source queries built from a memo-121 *natural* sample must
        find that subarray feasible, but the engine picks the MINIMUM-eta
        qualifying sample in the beam window -- which may be a different,
        even-lower-eta sample that happens to land in the same window (this
        is a feature: with imaging=False there is no skirt constraint, so
        the search is over more samples than the single one we started
        from). The correct assertion is therefore an inequality, not an
        equality: eta_got <= eta_of_the_sample_we_targeted.
        """
        for sub, res30, freq_orig, eta_expect in self.NATURAL_ROWS:
            with self.subTest(subarray=sub, freq=freq_orig, res30=res30):
                req = ObservingRequest(
                    resolution=_res_at_freq(res30, freq_orig),
                    frequency=freq_orig,
                    imaging=False,
                )
                result = select_subarrays(req, library=self.library)
                cand = next(c for c in result if c.subarray.name == sub)
                self.assertTrue(cand.feasible, msg=cand.reasons)
                self.assertLessEqual(cand.eta, eta_expect * 1.0001)  # tiny float slop


# =============================================================================
# B. Unit/behavior tests on a small synthetic CurveLibrary
# =============================================================================

def _write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


class SyntheticLibraryTestCase(unittest.TestCase):
    """Base class that builds a tiny, hand-crafted CurveLibrary in a tempdir
    (same columns as schema.py documents) so each behavior can be pinned down
    exactly, without depending on the messy bootstrap data."""

    SUBARRAY_HEADER = ["name", "components", "n_ant", "b_min_m", "b_max_m",
                       "las_coeff", "calc_name", "las_coeff_note"]
    SAMPLE_HEADER = ["subarray", "resolution_arcsec_30ghz", "eta", "skirt",
                     "weighting", "robust", "taper_arcsec_30ghz",
                     "freq_orig_ghz", "source", "note"]

    def make_library(self, subarray_rows, sample_rows):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        sub_path = os.path.join(d, "subarrays.csv")
        samp_path = os.path.join(d, "bootstrap_curves.csv")
        _write_csv(sub_path, self.SUBARRAY_HEADER, subarray_rows)
        _write_csv(samp_path, self.SAMPLE_HEADER, sample_rows)
        return CurveLibrary(subarrays=sub_path, samples=samp_path)


class TestBeamWindowEdges(SyntheticLibraryTestCase):

    def setUp(self):
        # one subarray, one briggs sample at 1.5" (30 GHz ref), good skirt.
        self.lib = self.make_library(
            subarray_rows=[["testA", "testA", 10, 100.0, 1000.0, 0.85, "testA", ""]],
            sample_rows=[["testA", "1.5", "2.0", "0.05", "briggs", "0.5", "0.3",
                          "30.0", "edge_sample", ""]],
        )

    def test_just_inside_margin_passes(self):
        # query freq == ref freq (30) so res_ref == resolution; with
        # beam_margin=0.5, window = resolution*[0.5, 1.5]. Choosing
        # resolution=1.0 puts the 1.5" sample exactly on the upper edge,
        # which the inclusive (lo <= s.resolution <= hi) test must accept.
        sample, msg = self.lib.solve("testA", resolution=1.0, freq_ghz=30.0,
                                     beam_margin=0.5, skirt_threshold=0.10)
        self.assertIsNotNone(sample, msg)
        self.assertEqual(sample.resolution, 1.5)

    def test_just_outside_margin_fails(self):
        # nudge the requested resolution down 1%: hi drops to 1.485 < 1.5,
        # so the same sample now falls outside the window.
        sample, msg = self.lib.solve("testA", resolution=0.99, freq_ghz=30.0,
                                     beam_margin=0.5, skirt_threshold=0.10)
        self.assertIsNone(sample)
        self.assertIn("no tabulated solution", msg)


class TestSkirtThreshold(SyntheticLibraryTestCase):

    def setUp(self):
        self.lib = self.make_library(
            subarray_rows=[["testA", "testA", 10, 100.0, 1000.0, 0.85, "testA", ""]],
            sample_rows=[
                # skirt exactly at the default 0.10 threshold -> must qualify
                ["testA", "1.0", "2.0", "0.10", "briggs", "0.5", "0.2", "30.0", "at_thresh", ""],
                # skirt just above -> must be excluded from the imaging curve
                ["testA", "2.0", "1.9", "0.11", "briggs", "0.4", "0.4", "30.0", "above_thresh", ""],
            ],
        )

    def test_skirt_equal_to_threshold_qualifies(self):
        q = self.lib.qualifying_samples("testA", skirt_threshold=0.10)
        self.assertIn(1.0, [s.resolution for s in q])

    def test_skirt_above_threshold_excluded(self):
        q = self.lib.qualifying_samples("testA", skirt_threshold=0.10)
        self.assertNotIn(2.0, [s.resolution for s in q])

    def test_point_source_curve_ignores_skirt(self):
        # skirt_threshold=None (point-source) admits both samples.
        q = self.lib.qualifying_samples("testA", skirt_threshold=None)
        self.assertEqual({s.resolution for s in q}, {1.0, 2.0})


class TestMissingSkirt(SyntheticLibraryTestCase):

    def setUp(self):
        self.lib = self.make_library(
            subarray_rows=[["testA", "testA", 10, 100.0, 1000.0, 0.85, "testA", ""]],
            sample_rows=[
                # natural sample with no skirt measurement at all (empty field)
                ["testA", "1.0", "1.0", "", "natural", "", "", "30.0", "no_skirt", ""],
            ],
        )

    def test_excluded_from_imaging_curve(self):
        q = self.lib.qualifying_samples("testA", skirt_threshold=0.10)
        self.assertEqual(q, [])

    def test_usable_for_point_source_curve(self):
        q = self.lib.qualifying_samples("testA", skirt_threshold=None)
        self.assertEqual(len(q), 1)
        self.assertIsNone(q[0].skirt)


class TestLASExclusion(SyntheticLibraryTestCase):

    def setUp(self):
        # b_min_m=100, las_coeff=0.85 -> las_arcsec(freq) = 0.85*lambda/100*206264.8
        self.lib = self.make_library(
            subarray_rows=[["testA", "testA", 10, 100.0, 1000.0, 0.85, "testA", ""]],
            sample_rows=[["testA", "1.0", "1.0", "0.05", "briggs", "0.5", "0.2",
                          "30.0", "s", ""]],
        )

    def test_las_too_small_excludes_with_message(self):
        info = self.lib.subarrays["testA"]
        las_at_30ghz = info.las_arcsec(30.0)
        req = ObservingRequest(resolution=_res_at_freq(1.0, 30.0), frequency=30.0,
                               las=las_at_30ghz * 2, imaging=True)  # ask for more LAS than available
        result = select_subarrays(req, library=self.lib)
        cand = next(c for c in result if c.subarray.name == "testA")
        self.assertFalse(cand.feasible)
        self.assertTrue(any("LAS" in r for r in cand.reasons), cand.reasons)

    def test_las_sufficient_does_not_exclude(self):
        info = self.lib.subarrays["testA"]
        las_at_30ghz = info.las_arcsec(30.0)
        req = ObservingRequest(resolution=_res_at_freq(1.0, 30.0), frequency=30.0,
                               las=las_at_30ghz * 0.5, imaging=True)
        result = select_subarrays(req, library=self.lib)
        cand = next(c for c in result if c.subarray.name == "testA")
        self.assertTrue(cand.feasible, cand.reasons)


class TestFrequencyScaling(SyntheticLibraryTestCase):

    def setUp(self):
        self.lib = self.make_library(
            subarray_rows=[["testA", "testA", 10, 100.0, 1000.0, 0.85, "testA", ""]],
            sample_rows=[["testA", "1.0", "1.5", "0.05", "briggs", "0.5", "0.4",
                          "30.0", "s", ""]],
        )

    def test_resolution_and_taper_scale_by_30_over_f(self):
        sample = self.lib.samples["testA"][0]
        for freq in (15.0, 60.0, 100.0):
            scaled = self.lib.scale_sample(sample, freq)
            factor = 30.0 / freq
            self.assertAlmostEqual(scaled.resolution, sample.resolution * factor)
            self.assertAlmostEqual(scaled.taper, sample.taper * factor)
            self.assertEqual(scaled.eta, sample.eta)  # eta assumed invariant


class TestHeuristicPlumbing(SyntheticLibraryTestCase):

    def setUp(self):
        # two subarrays with different n_ant so antenna_hours vs
        # integration_time heuristics can disagree, and a custom heuristic
        # can be verified by picking the one the built-ins would NOT pick.
        self.lib = self.make_library(
            subarray_rows=[
                ["small", "small", 10, 100.0, 1000.0, 0.85, "small", ""],
                ["big", "big", 100, 100.0, 1000.0, 0.85, "big", ""],
            ],
            sample_rows=[
                ["small", "1.0", "1.0", "0.05", "briggs", "0.0", "0.1", "30.0", "s", ""],
                ["big", "1.0", "1.0", "0.05", "briggs", "0.0", "0.1", "30.0", "b", ""],
            ],
        )

    def _request(self, **kw):
        return ObservingRequest(resolution=_res_at_freq(1.0, 30.0), frequency=30.0,
                                imaging=True, **kw)

    def test_custom_heuristic_callable_is_honored(self):
        # At equal eta, both built-in heuristics prefer MORE antennas: per
        # heuristics.py's own derivation, antenna-hours ~ eta^2/(N-1), which
        # *decreases* with N (more collecting area shrinks the needed
        # integration time faster than it adds antennas). So the built-in
        # antenna_hours heuristic ranks "big" (n=100) ahead of "small" (n=10)
        # here. A custom heuristic that instead prefers fewer antennas is
        # deliberately the opposite choice, so honoring it is unambiguous.
        def rank_by_fewer_antennas(cands, request):
            return sorted(cands, key=lambda c: c.subarray.n_ant)

        req = self._request(optimize="antenna_hours")
        default_result = select_subarrays(req, library=self.lib)
        self.assertEqual(default_result.best.subarray.name, "big")

        custom_result = select_subarrays(req, library=self.lib,
                                         heuristic=rank_by_fewer_antennas)
        self.assertEqual(custom_result.best.subarray.name, "small")

    def test_unknown_heuristic_name_raises_value_error(self):
        with self.assertRaises(ValueError):
            heuristics.resolve("not_a_real_heuristic")

    def test_unknown_optimize_on_request_also_raises_value_error(self):
        # regression check for the resolve() bug fixed alongside this test
        # suite: request.optimize is looked up with heuristic=None (the
        # normal, no-override call path), which used to bypass the
        # try/except and raise a raw KeyError instead of ValueError.
        req = self._request(optimize="not_a_real_heuristic")
        with self.assertRaises(ValueError):
            select_subarrays(req, library=self.lib)


class TestObservingRequestValidation(unittest.TestCase):

    def test_bad_unit_raises(self):
        with self.assertRaises(ValueError):
            ObservingRequest(resolution=1.0, frequency=30.0, sensitivity_unit="mJy")

    def test_negative_resolution_raises(self):
        with self.assertRaises(ValueError):
            ObservingRequest(resolution=-1.0, frequency=30.0)

    def test_negative_frequency_raises(self):
        with self.assertRaises(ValueError):
            ObservingRequest(resolution=1.0, frequency=-30.0)

    def test_zero_resolution_raises(self):
        with self.assertRaises(ValueError):
            ObservingRequest(resolution=0.0, frequency=30.0)


# =============================================================================
# C. Sensitivity-module tests
# =============================================================================

class TestSensitivity(unittest.TestCase):

    def test_integration_time_round_trip(self):
        eta, x_hr = 1.35, 3.7
        goal = eta * sens.natural_rms("spiral", 15.0, t_obs_hr=x_hr)
        t_back = sens.integration_time("spiral", 15.0, eta, goal)
        self.assertAlmostEqual(t_back, x_hr, delta=1e-6 * x_hr)

    def test_tb_jy_round_trip(self):
        tb0, theta0, freq0 = 12.3, 0.05, 27.0
        s0 = sens.tb_to_jy(tb0, theta0, freq0)
        tb_back = sens.jy_to_tb(s0, theta0, freq0)
        self.assertAlmostEqual(tb_back, tb0, delta=1e-9 * tb0)

    def test_core_mid_natural_rms_matches_donor_scaling_exactly(self):
        import numpy as np
        r_main = sens.natural_rms("main", 30.0, t_obs_hr=1.0)
        r_coremid = sens.natural_rms("core+mid", 30.0, t_obs_hr=1.0)
        expected = r_main * np.sqrt(214 * 213 / (160 * 159))
        self.assertAlmostEqual(r_coremid, expected, delta=1e-9 * expected)

    def test_absurd_frequency_raises_value_error(self):
        with self.assertRaises(ValueError):
            sens.natural_rms("main", 300.0, t_obs_hr=1.0)


# =============================================================================
# D. End-to-end smoke test
# =============================================================================

class TestEndToEndSmoke(unittest.TestCase):
    """Replay PF3(KSG1).1 (main, 80 GHz, 13.3 mas, imaging) end to end,
    including the sensitivity-calculator hookup."""

    def test_pf3_ksg1_replay(self):
        req = ObservingRequest(resolution=0.005, frequency=80.0,
                               sensitivity=1e-6, imaging=True)
        result = select_subarrays(req)

        self.assertIsNotNone(result.best)
        best = result.best
        self.assertEqual(best.subarray.name, "main")
        self.assertAlmostEqual(best.robust, -1.81, places=2)
        self.assertAlmostEqual(best.eta, 3.47, places=2)
        self.assertIsNotNone(best.integration_time_hr)
        self.assertAlmostEqual(best.antenna_hours,
                               best.integration_time_hr * best.subarray.n_ant)


if __name__ == "__main__":
    unittest.main()


class TestSkirtRelaxation(SyntheticLibraryTestCase):
    """Angular resolution is the primary requirement (bmason, 6 Jul 2026):
    when no beam at the requested resolution reaches the skirt threshold,
    solve() relaxes to the best achievable skirt there and flags it, rather
    than excluding the subarray (memo 121's 'bottom out at ~16%' cases)."""

    def setUp(self):
        self.lib = self.make_library(
            subarray_rows=[["testA", "testA", 10, 100.0, 1000.0, 0.85, "testA", ""]],
            sample_rows=[
                # both fail the 0.10 threshold; the 0.16-skirt one is the
                # best achievable and cheaper than the 0.30 one
                ["testA", "1.0", "1.8", "0.16", "briggs", "-0.5", "0.5", "30.0", "best_achievable", ""],
                ["testA", "1.0", "1.2", "0.30", "natural", "", "0.6", "30.0", "cheap_but_messy", ""],
            ],
        )

    def test_relaxed_solution_returned_and_flagged(self):
        sample, msg = self.lib.solve("testA", resolution=1.0, freq_ghz=30.0,
                                     skirt_threshold=0.10, relax=True)
        self.assertIsNotNone(sample)
        self.assertEqual(sample.skirt, 0.16)     # best achievable (min-skirt)
        self.assertIn("relaxed", msg)
        self.assertNotIn("traded", msg)          # threshold policy, not a trade

    def test_strict_mode_still_excludes(self):
        sample, msg = self.lib.solve("testA", resolution=1.0, freq_ghz=30.0,
                                     skirt_threshold=0.10, relax=False)
        self.assertIsNone(sample)

    def test_selector_marks_relaxation_as_warning_not_exclusion(self):
        req = ObservingRequest(resolution=1.0, frequency=30.0, imaging=True)
        res = select_subarrays(req, library=self.lib)
        c = res.candidates[0]
        self.assertTrue(c.feasible)
        self.assertTrue(c.warnings and "relaxed" in c.warnings[0])
        req_strict = ObservingRequest(resolution=1.0, frequency=30.0,
                                      imaging=True, skirt_relax=False)
        res2 = select_subarrays(req_strict, library=self.lib)
        self.assertFalse(res2.candidates[0].feasible)

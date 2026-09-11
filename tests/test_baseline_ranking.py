"""Selector integration tests for physical-baseline ranking metrics."""

import csv
import os
import tempfile
import unittest
from unittest import mock

from sa_select import CurveLibrary, ObservingRequest, select_subarrays
from sa_select.baselines import DEFAULT_LAS_RATIO
from sa_select.schema import CurveSample, SubarrayInfo


def _info(name, n_ant):
    return SubarrayInfo(name, name, n_ant, 10.0, 1000.0, 0.8, "main")


def _sample(name):
    return CurveSample(name, 7.0, 1.0, "natural", skirt=0.05,
                       source="synthetic")


def _geometry(n_ant, lengths):
    return {"n_ant": n_ant, "lengths_m": lengths,
            "provenance": {"source": "synthetic"}}


class TestBaselineRanking(unittest.TestCase):
    def library(self, geometry):
        subs = {"main": _info("main", 3), "main+long": _info("main+long", 4)}
        samples = {name: [_sample(name)] for name in subs}
        return CurveLibrary.from_tables(subs, samples, geometry=geometry)

    def test_efficiency_and_performance_use_distinct_scores_and_keep_main(self):
        # At 30 GHz and 7 arcsec Bmax is about 300.5 m.  Main has a higher
        # fraction (2/3), while Main+Long has a higher useful count (3/6).
        lib = self.library({
            "main": _geometry(3, [100.0, 200.0, 600.0]),
            "main+long": _geometry(4, [100.0, 200.0, 300.0,
                                         400.0, 500.0, 600.0]),
        })
        req = ObservingRequest(7.0, 30.0, imaging=False, optimize="efficient")
        efficient = select_subarrays(req, library=lib)
        self.assertTrue(efficient.ranking_available)
        self.assertEqual([c.subarray.name for c in efficient.feasible],
                         ["main", "main+long"])
        self.assertEqual(efficient.best.baselines_in_range, 2)
        self.assertEqual(efficient.best.baselines_total, 3)
        self.assertAlmostEqual(efficient.best.baseline_efficiency, 2 / 3)

        performance = select_subarrays(
            ObservingRequest(7.0, 30.0, imaging=False, optimize="performance"),
            library=lib)
        # The higher count wins, even though its fraction is lower.  Full
        # arrays are ordinary members of the ranked result, never excluded.
        self.assertEqual([c.subarray.name for c in performance.feasible],
                         ["main+long", "main"])

    def test_ties_follow_documented_order(self):
        lib = self.library({
            "main": _geometry(3, [100.0, 200.0, 600.0]),
            "main+long": _geometry(4, [100.0, 200.0, 700.0,
                                         800.0, 900.0, 1000.0]),
        })
        # Each has two useful baselines.  Efficient ranks 2/3 before 2/6;
        # performance resolves the equal count by the same efficiency rule.
        for mode in ("efficient", "performance"):
            result = select_subarrays(
                ObservingRequest(7.0, 30.0, imaging=False, optimize=mode),
                library=lib)
            self.assertEqual(result.best.subarray.name, "main")

    def test_missing_geometry_disables_only_baseline_ranking(self):
        lib = self.library({"main": _geometry(3, [100.0, 200.0, 300.0])})
        result = select_subarrays(
            ObservingRequest(7.0, 30.0, imaging=False, optimize="efficient"),
            library=lib)
        self.assertFalse(result.ranking_available)
        self.assertIsNone(result.best)
        self.assertIn("BASELINE_RANKING_UNAVAILABLE",
                      [warning.code for warning in result.warnings])
        missing = next(c for c in result.feasible if c.subarray.name == "main+long")
        self.assertEqual(missing.baseline_status, "unavailable")

    def test_baseline_ranking_survives_implicit_cost_unavailability(self):
        lib = self.library({
            "main": _geometry(3, [100.0, 200.0, 300.0]),
            "main+long": _geometry(4, [100.0, 200.0, 300.0,
                                         400.0, 500.0, 600.0]),
        })
        from sa_select import sensitivity as sens
        with mock.patch.object(sens, "natural_rms", side_effect=RuntimeError("boom")):
            result = select_subarrays(
                ObservingRequest(7.0, 30.0, imaging=False, optimize="efficient"),
                library=lib)
        self.assertTrue(result.ranking_available)
        self.assertEqual(result.best.subarray.name, "main")
        self.assertTrue(all(c.cost_status == "unavailable" for c in result.feasible))

    def test_baseline_ranking_survives_per_candidate_implicit_cost_failure(self):
        lib = self.library({
            "main": _geometry(3, [100.0, 200.0, 600.0]),
            "main+long": _geometry(4, [100.0, 200.0, 300.0,
                                         400.0, 500.0, 600.0]),
        })
        from sa_select import sensitivity as sens
        with mock.patch.object(sens, "integration_time", side_effect=RuntimeError("boom")):
            result = select_subarrays(
                ObservingRequest(7.0, 30.0, imaging=False, optimize="performance"),
                library=lib)
        self.assertTrue(result.ranking_available)
        self.assertEqual(result.best.subarray.name, "main+long")
        self.assertTrue(all(c.cost_status == "failed" for c in result.feasible))

    def test_performance_and_time_can_disagree(self):
        subs = {"main": _info("main", 10), "main+long": _info("main+long", 4)}
        samples = {name: [_sample(name)] for name in subs}
        lib = CurveLibrary.from_tables(subs, samples, geometry={
            "main": _geometry(10, [100.0] * 2 + [600.0] * 43),
            "main+long": _geometry(4, [100.0, 200.0, 300.0,
                                         400.0, 500.0, 600.0]),
        })
        performance = select_subarrays(
            ObservingRequest(7.0, 30.0, imaging=False, optimize="performance"), lib)
        timed = select_subarrays(
            ObservingRequest(7.0, 30.0, imaging=False, optimize="integration_time"), lib)
        self.assertEqual(performance.best.subarray.name, "main+long")
        self.assertEqual(timed.best.subarray.name, "main")

    def test_strict_first_and_mixed_policy_apply_to_baseline_modes(self):
        subs = {"main": _info("main", 3), "main+long": _info("main+long", 4)}
        samples = {
            "main": [CurveSample("main", 7.0, 1.0, "natural", skirt=0.05)],
            "main+long": [CurveSample("main+long", 7.0, 1.0, "natural", skirt=0.20)],
        }
        lib = CurveLibrary.from_tables(subs, samples, geometry={
            "main": _geometry(3, [100.0, 200.0, 600.0]),
            "main+long": _geometry(4, [100.0, 200.0, 300.0,
                                         400.0, 500.0, 600.0]),
        })
        grouped = select_subarrays(ObservingRequest(7.0, 30.0, optimize="performance"), lib)
        mixed = select_subarrays(ObservingRequest(
            7.0, 30.0, optimize="performance", strict_first=False), lib)
        self.assertEqual(grouped.best.subarray.name, "main")
        self.assertEqual(mixed.best.subarray.name, "main+long")

    def test_override_and_explicit_cost_failure_preserve_existing_policy(self):
        lib = self.library({
            "main": _geometry(3, [100.0, 200.0, 600.0]),
            "main+long": _geometry(4, [100.0, 200.0, 300.0,
                                         400.0, 500.0, 600.0]),
        })
        custom = select_subarrays(
            ObservingRequest(7.0, 30.0, imaging=False, optimize="performance"), lib,
            heuristic=lambda cands, request: list(reversed(cands)))
        self.assertEqual(custom.best.subarray.name, "main+long")
        self.assertEqual(custom.ranking_heuristic, "custom")
        named = select_subarrays(
            ObservingRequest(7.0, 30.0, imaging=False, optimize="performance"), lib,
            heuristic="antenna_hours")
        self.assertEqual(named.ranking_heuristic, "antenna_hours")
        self.assertNotIn("B_in/B_all", named.table())
        from sa_select import sensitivity as sens
        with mock.patch.object(sens, "integration_time", side_effect=RuntimeError("boom")):
            failed = select_subarrays(ObservingRequest(
                7.0, 30.0, sensitivity=1e-6, imaging=False, optimize="performance"), lib)
        self.assertFalse(failed.feasible)

    def test_zero_and_inverted_bounds_are_distinct_from_missing_geometry(self):
        sub = _info("main", 3)
        lib = CurveLibrary.from_tables(
            {"main": sub}, {"main": [CurveSample("main", 10000.0, 1.0, "natural")]},
            geometry={"main": _geometry(3, [100.0, 200.0, 300.0])})
        zero = select_subarrays(ObservingRequest(
            10000.0, 30.0, imaging=False, optimize="efficient"), lib)
        self.assertTrue(zero.ranking_available)
        self.assertEqual(zero.best.baselines_in_range, 0)
        inverted = select_subarrays(ObservingRequest(
            10000.0, 30.0, las=0.001, imaging=False, optimize="antenna_hours"), lib)
        self.assertTrue(inverted.ranking_available)
        self.assertEqual(inverted.best.baseline_status, "failed")
        self.assertIn("inverted", inverted.best.baseline_error)

    def test_custom_sources_never_guess_geometry(self):
        lib = CurveLibrary.from_tables(
            {"main": _info("main", 3)}, {"main": [_sample("main")]})
        metric = select_subarrays(
            ObservingRequest(7.0, 30.0, imaging=False, optimize="efficient"), lib)
        self.assertFalse(metric.ranking_available)
        with tempfile.NamedTemporaryFile("w", newline="", delete=False) as handle:
            registry = handle.name
            csv.DictWriter(handle, fieldnames=["rev", "sim_mode", "band", "subarrays_csv", "samples_csv"]).writeheader()
            csv.DictWriter(handle, fieldnames=["rev", "sim_mode", "band", "subarrays_csv", "samples_csv"]).writerow(
                {"rev": "revF", "sim_mode": "track", "band": "",
                 "subarrays_csv": "subarrays.csv", "samples_csv": "revf_curves.csv"})
        self.addCleanup(lambda: os.unlink(registry))
        self.assertEqual(CurveLibrary.for_config("revF", registry_path=registry).geometry, {})

    def test_per_subarray_las_coefficient_controls_lower_bound(self):
        sub = _info("main", 3)
        sub.las_coeff = 0.4
        lib = CurveLibrary.from_tables(
            {"main": sub}, {"main": [_sample("main")]},
            geometry={"main": _geometry(3, [50.0, 100.0, 200.0])})
        # LAS=16.5 arcsec yields Bmin near 50 m for coeff=0.4; the inclusive
        # lower edge keeps all three baselines in this deliberately broad beam.
        result = select_subarrays(
            ObservingRequest(7.0, 30.0, las=16.5, imaging=False,
                             optimize="performance"), library=lib)
        candidate = result.best
        self.assertAlmostEqual(candidate.baseline_min_m,
                               0.4 * (0.299792458 / 30.0) * 206264.8 / 16.5)
        self.assertEqual(candidate.baselines_in_range, 3)

    def test_bmin_defaults_when_no_las_requested_and_uses_pi_las_when_given(self):
        lib = self.library({
            "main": _geometry(3, [100.0, 200.0, 600.0]),
            "main+long": _geometry(4, [100.0, 200.0, 300.0,
                                         400.0, 500.0, 600.0]),
        })
        no_las = select_subarrays(
            ObservingRequest(7.0, 30.0, imaging=False, optimize="efficient"),
            library=lib)
        candidate = next(c for c in no_las.feasible if c.subarray.name == "main")
        self.assertTrue(candidate.baseline_las_defaulted)
        self.assertAlmostEqual(candidate.baseline_las_arcsec, DEFAULT_LAS_RATIO * 7.0)
        # Bmin follows the defaulted LAS, not zero.
        expected_bmin = 0.8 * (0.299792458 / 30.0) * 206264.8 / (DEFAULT_LAS_RATIO * 7.0)
        self.assertAlmostEqual(candidate.baseline_min_m, expected_bmin)

        with_las = select_subarrays(
            ObservingRequest(7.0, 30.0, las=50.0, imaging=False, optimize="efficient"),
            library=lib)
        candidate = next(c for c in with_las.feasible if c.subarray.name == "main")
        self.assertFalse(candidate.baseline_las_defaulted)
        self.assertAlmostEqual(candidate.baseline_las_arcsec, 50.0)

    def test_defaulted_las_does_not_change_feasibility_or_cost(self):
        """Regression guard for decision 3: a defaulted LAS feeds Bmin only.

        It must never exclude a subarray (LAS feasibility stays keyed on a
        PI-supplied request.las) and must never change antenna_hours or
        integration_time -- those are driven by request.sensitivity/eta/N_ant,
        entirely independent of the baseline-metric LAS default.
        """
        lib = self.library({
            "main": _geometry(3, [100.0, 200.0, 600.0]),
            "main+long": _geometry(4, [100.0, 200.0, 300.0,
                                         400.0, 500.0, 600.0]),
        })
        req_no_las = ObservingRequest(7.0, 30.0, imaging=False, optimize="efficient")
        efficient = select_subarrays(req_no_las, library=lib)
        antenna_hours = select_subarrays(
            ObservingRequest(7.0, 30.0, imaging=False, optimize="antenna_hours"),
            library=lib)
        self.assertEqual({c.subarray.name for c in efficient.feasible},
                         {c.subarray.name for c in antenna_hours.feasible})
        by_name_a = {c.subarray.name: c for c in efficient.feasible}
        by_name_b = {c.subarray.name: c for c in antenna_hours.feasible}
        for name in by_name_a:
            ca, cb = by_name_a[name], by_name_b[name]
            self.assertEqual(ca.las, cb.las)
            self.assertEqual(ca.integration_time_hr, cb.integration_time_hr)
            self.assertEqual(ca.antenna_hours, cb.antenna_hours)
            self.assertTrue(ca.baseline_las_defaulted)

    def test_acceptance_core_spiral_mid_each_rank_first_under_efficient(self):
        """Acceptance criterion from docs/plans/baseline-window-plan.md: at
        each subarray's own natural (30 GHz) resolution, requesting that
        resolution with no LAS ranks it #1 under `efficient`, at the
        verified efficiencies recorded on DEFAULT_LAS_RATIO."""
        lib = CurveLibrary()
        for name, resolution, expected_eff in (
                ("core", 0.70937, 0.911),
                ("spiral", 0.07606, 0.948),
                ("mid", 0.00293, 0.845)):
            with self.subTest(name=name):
                result = select_subarrays(
                    ObservingRequest(resolution, 30.0, imaging=False,
                                     optimize="efficient"),
                    library=lib)
                self.assertTrue(result.ranking_available)
                self.assertEqual(result.best.subarray.name, name)
                self.assertAlmostEqual(result.best.baseline_efficiency,
                                       expected_eff, places=3)

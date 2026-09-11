import csv
from pathlib import Path
import unittest

from sa_select.baselines import DEFAULT_LAS_RATIO, baseline_metrics, load_baseline_geometry


ROOT = Path(__file__).resolve().parents[1]
_C_ARCSEC = 206264.8
_TEST_FREQUENCY_GHZ = 0.299792458  # wavelength = 1 m


def geometry(n_ant=3, lengths=(1.0, 2.0, 3.0)):
    return {
        "n_ant": n_ant,
        "lengths_m": list(lengths),
        "provenance": {"source": "test"},
    }


class TestBaselineMetrics(unittest.TestCase):

    def test_bounds_and_inclusive_pair_count(self):
        # The requested interval is [1.02, 2] m.
        result = baseline_metrics(
            geometry(),
            _TEST_FREQUENCY_GHZ,
            _C_ARCSEC * 1.02 / 2,
            _C_ARCSEC * 0.8 / 1.02,
            0.8,
        )
        self.assertAlmostEqual(result["baseline_min_m"], 1.02)
        self.assertAlmostEqual(result["baseline_max_m"], 2.0)
        self.assertEqual(result["baselines_in_range"], 1)
        self.assertEqual(result["baselines_total"], 3)
        self.assertAlmostEqual(result["baseline_efficiency"], 1 / 3)

    def test_no_las_and_invalid_inputs(self):
        resolution_arcsec = _C_ARCSEC * 1.02 / 2
        result = baseline_metrics(
            geometry(),
            _TEST_FREQUENCY_GHZ,
            resolution_arcsec,
            None,
            0.8,
        )
        # With no LAS requested, Bmin defaults to DEFAULT_LAS_RATIO x the
        # requested resolution rather than 0 (decision 2).
        expected_las = DEFAULT_LAS_RATIO * resolution_arcsec
        expected_bmin = 0.8 * (0.299792458 / _TEST_FREQUENCY_GHZ) * _C_ARCSEC / expected_las
        self.assertAlmostEqual(result["baseline_min_m"], expected_bmin)
        self.assertEqual(result["baselines_in_range"], 2)
        self.assertTrue(result["baseline_las_defaulted"])
        self.assertAlmostEqual(result["baseline_las_arcsec"], expected_las)

        # A PI-supplied LAS is used as-is and is not flagged as defaulted.
        supplied = baseline_metrics(
            geometry(), _TEST_FREQUENCY_GHZ, resolution_arcsec,
            _C_ARCSEC * 0.8 / 1.02, 0.8)
        self.assertFalse(supplied["baseline_las_defaulted"])
        self.assertAlmostEqual(supplied["baseline_las_arcsec"], _C_ARCSEC * 0.8 / 1.02)

        with self.assertRaisesRegex(ValueError, "inverted"):
            baseline_metrics(geometry(), 30, 1, 0.001, 0.8)
        with self.assertRaises(ValueError):
            baseline_metrics(
                {"n_ant": 2, "lengths_m": [2, 1], "provenance": {}},
                30,
                1,
                None,
                0.8,
            )

    def test_repeated_lengths_at_both_endpoints_are_inclusive(self):
        # The interval is exactly [2, 2] m, so both repeated endpoint pairs
        # must be counted.
        repeated = geometry(lengths=(2.0, 2.0, 9.0))
        result = baseline_metrics(
            repeated,
            _TEST_FREQUENCY_GHZ,
            _C_ARCSEC * 1.02 / 2,
            _C_ARCSEC * 0.8 / 2,
            0.8,
        )
        self.assertEqual(result["baselines_in_range"], 2)

    def test_zero_and_all_pair_counts(self):
        all_pairs = baseline_metrics(
            geometry(),
            _TEST_FREQUENCY_GHZ,
            _C_ARCSEC * 1.02 / 3,
            None,
            0.8,
        )
        self.assertEqual(all_pairs["baselines_in_range"], 3)

        # The valid interval [2.5, 2.9] m contains no pair in this fixture.
        no_pairs = baseline_metrics(
            geometry(),
            _TEST_FREQUENCY_GHZ,
            _C_ARCSEC * 1.02 / 2.9,
            _C_ARCSEC * 0.8 / 2.5,
            0.8,
        )
        self.assertEqual(no_pairs["baselines_in_range"], 0)

    def test_invalid_antenna_counts_are_rejected(self):
        invalid_counts = (True, 3.5, float("inf"), float("nan"), 1)
        for n_ant in invalid_counts:
            with self.subTest(n_ant=n_ant):
                with self.assertRaises(ValueError):
                    baseline_metrics(geometry(n_ant=n_ant), 30, 1, None, 0.8)

    def test_packaged_geometry_has_full_pair_distribution(self):
        revf = load_baseline_geometry("revF")
        self.assertIn("main", revf)
        self.assertIn("main+long", revf)
        # No uv-range cut is applied when the geometry is packaged (bmason,
        # 11 Sep 2026 -- see build_baseline_data.py and baselines.py module
        # docstrings): every subarray, gated or not, keeps its full
        # combinatorial pair distribution.
        main_long = revf["main+long"]
        self.assertEqual(
            len(main_long["lengths_m"]),
            main_long["n_ant"] * (main_long["n_ant"] - 1) // 2,
        )
        long = revf["long"]
        self.assertEqual(
            len(long["lengths_m"]),
            long["n_ant"] * (long["n_ant"] - 1) // 2,
        )
        self.assertEqual(long["lengths_m"], sorted(long["lengths_m"]))
        with self.assertRaisesRegex(ValueError, "no baseline geometry"):
            load_baseline_geometry("unknown")

    def test_no_uvrange_cut_is_applied_to_any_subarray(self):
        # config.MIN_UVRANGE_M (~178 m for Rev F) is used for curve
        # generation/imaging only; it is deliberately NOT applied here (this
        # decision was tried the other way on 11 Sep 2026 and reversed the
        # same day -- see docs/plans/baseline-window-plan.md decision 5/W3
        # and docs/worklog/baseline-ranking.md). Every packaged subarray
        # keeps its full n_ant*(n_ant-1)/2 pair distribution, and n_pairs
        # always equals len(lengths_m).
        revf = load_baseline_geometry("revF")
        for name, entry in revf.items():
            total = entry["n_ant"] * (entry["n_ant"] - 1) // 2
            self.assertEqual(entry["n_pairs"], total,
                             "%s does not keep its full pair distribution" % name)
            self.assertEqual(entry["n_pairs"], len(entry["lengths_m"]))

    def test_packaged_subarrays_keep_exact_full_pair_counts(self):
        # Pins the 11 Sep reversal for specific subarrays: these counts must
        # equal the full n_ant*(n_ant-1)/2 combinatorial count, not a
        # filtered count.
        revf = load_baseline_geometry("revF")
        expected = {
            "long": 435,
            "mid+long": 2850,
            "spiral+mid+long": 8385,
            "long+mid+spiral+core-outer": 17391,
            "core": 6441,
            "mid": 1035,
            "main": 22791,
            "spiral+mid": 4950,
            "main+long": 29646,
        }
        for name, n_pairs in expected.items():
            entry = revf[name]
            self.assertEqual(entry["n_pairs"], n_pairs)
            self.assertEqual(entry["n_pairs"],
                             entry["n_ant"] * (entry["n_ant"] - 1) // 2)

    def test_long_short_intrasite_pairs_are_present(self):
        # Pins the reversal's intent directly: LONG's spurious ~3-antenna
        # cluster short baselines (well below config.MIN_UVRANGE_M, ~178 m)
        # must be present in the packaged geometry so a request with a small
        # enough Bmin can credit them, per bmason's 11 Sep 2026 reasoning.
        revf = load_baseline_geometry("revF")
        for name in ("long", "mid+long", "spiral+mid+long",
                    "long+mid+spiral+core-outer"):
            entry = revf[name]
            self.assertTrue(
                any(length < 178.0 for length in entry["lengths_m"]),
                "%s is missing its short intra-site pairs" % name,
            )

    def test_all_packaged_revisions_match_registered_antenna_metadata(self):
        data_dir = ROOT / "sa_select" / "data"
        with (data_dir / "config_registry.csv").open(newline="") as handle:
            registry = list(csv.DictReader(handle))

        for revision in ("revC", "revD", "revF"):
            filename = next(
                row["subarrays_csv"]
                for row in registry
                if row["rev"] == revision
                and row["sim_mode"] == "track"
                and not row.get("band")
            )
            with (data_dir / filename).open(newline="") as handle:
                metadata = {
                    row["name"]: row for row in csv.DictReader(handle)
                }

            packaged = load_baseline_geometry(revision)
            self.assertEqual(set(packaged), set(metadata))
            for name, entry in packaged.items():
                n_ant = int(metadata[name]["n_ant"])
                self.assertEqual(entry["n_ant"], n_ant)
                # No uv-range cut is applied when packaging (see this
                # module's docstring), so every subarray keeps its full
                # combinatorial pair count; the <= bound below is a generic
                # sanity check, not an expectation of filtering.
                self.assertLessEqual(
                    len(entry["lengths_m"]), n_ant * (n_ant - 1) // 2
                )
                self.assertEqual(entry["n_pairs"], len(entry["lengths_m"]))
                self.assertEqual(entry["n_pairs"], n_ant * (n_ant - 1) // 2)
                # CSV extrema are rounded to centimetres; the packaged
                # distribution retains the full-precision configuration value.
                self.assertAlmostEqual(
                    max(entry["lengths_m"]),
                    float(metadata[name]["b_max_m"]),
                    places=2,
                )


if __name__ == "__main__":
    unittest.main()

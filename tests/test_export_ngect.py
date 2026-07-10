"""Tests for the ngECT PPoly export.

Run from the repository root:

    python3 -m unittest tests.test_export_ngect
"""

import json
import math
import os
import sys
import tempfile
import unittest

import numpy as np
from scipy.interpolate import PPoly

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sa_select import export_ngect
from sa_select.curves import CurveLibrary


class TestNgectExport(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out_path = os.path.join(cls.tmp.name, "ngect_subarray_data.json")
        cls.stats = export_ngect.export(output_path=cls.out_path)
        cls.lib = CurveLibrary()
        with open(cls.out_path) as handle:
            cls.data = json.load(handle)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_subarrays_and_legacy_fields_present(self):
        self.assertIn("_meta", self.data)
        for name in self.lib.names():
            with self.subTest(subarray=name):
                self.assertIn(name, self.data)
                entry = self.data[name]
                for key in ("b_min", "b_max", "N_ant", "theta_nat_30_GHz"):
                    self.assertIn(key, entry)
                self.assertEqual(entry["beam_convention"], "geometric_mean_fwhm_mas")
                cap = self.lib.subarrays[name].beam_cap_arcsec
                if cap is None:
                    self.assertNotIn("beam_cap_arcsec_30ghz", entry)
                else:
                    self.assertEqual(entry["beam_cap_arcsec_30ghz"], cap)
                self.assertIn(export_ngect.CURVE_POINT_SOURCE, entry["curves"])
                self.assertIn(export_ngect.CURVE_IMAGING, entry["curves"])

    def test_meta_documents_conventions(self):
        meta = self.data["_meta"]
        self.assertEqual(meta["generator"], "sa_select/export_ngect.py")
        self.assertEqual(meta["beam_cap_units"], "arcsec at 30 GHz")
        self.assertIn("geometric-mean FWHM", meta["eta_definition"])
        self.assertIn("quadrature-sum", meta["eta_definition"])
        self.assertIn("physical 3-D baseline", meta["eta_definition"])
        self.assertIn("projected-uv", meta["eta_definition"])
        self.assertIn("scipy PPoly [c, x]", meta["spline_convention"])

    def test_core_native_theta_uses_geometric_mean_convention(self):
        theta = self.data["core"]["theta_nat_30_GHz"]
        self.assertGreaterEqual(theta, 700.0)
        self.assertLessEqual(theta, 720.0)

    def test_native_theta_matches_loaded_natural_untapered_samples(self):
        for name in self.lib.names():
            with self.subTest(subarray=name):
                self.assertAlmostEqual(
                    self.data[name]["theta_nat_30_GHz"],
                    export_ngect.theta_nat_30_ghz_mas(self.lib, name),
                    places=9,
                )

    def test_splines_reproduce_export_dense_curves(self):
        worst = 0.0
        for name in self.lib.names():
            for curve_key in (export_ngect.CURVE_POINT_SOURCE, export_ngect.CURVE_IMAGING):
                with self.subTest(subarray=name, curve=curve_key):
                    curve = export_ngect.build_export_curve(self.lib, name, curve_key)
                    curve_json = self.data[name]["curves"][curve_key]
                    c, x = curve_json["spline_params"]
                    self.assertEqual(len(c), 4)
                    self.assertTrue(all(len(row) == len(x) - 1 for row in c))
                    self.assertEqual(curve_json["n_knots"], len(x))
                    self.assertTrue(all(math.isfinite(v) for v in x))
                    self.assertTrue(np.all(np.diff(np.asarray(x, dtype=float)) > 0))

                    domain = curve_json["domain_log10_theta_mas"]
                    self.assertEqual(domain, [x[0], x[-1]])
                    self.assertTrue(math.isfinite(domain[0]))
                    self.assertTrue(math.isfinite(domain[1]))
                    self.assertLess(domain[0], domain[1])

                    spline = PPoly(np.asarray(c, dtype=float), np.asarray(x, dtype=float))
                    fitted = spline(curve.log10_theta_mas)
                    rel = np.abs(fitted - curve.eta) / curve.eta
                    max_rel = float(np.max(rel))
                    worst = max(worst, max_rel)
                    self.assertLess(max_rel, 0.01)
                    self.assertGreaterEqual(float(np.min(fitted)), 0.99 * float(np.min(curve.eta)))
                    self.assertAlmostEqual(curve_json["eta_min"], float(np.min(curve.eta)))
                    self.assertAlmostEqual(curve_json["eta_max"], float(np.max(curve.eta)))
        self.assertAlmostEqual(self.stats.max_relative_error, worst)

    def test_current_no_strict_imaging_domains_are_marked_as_relaxed_fallbacks(self):
        fallback_names = {
            "mid+long",
            "spiral+mid+long",
            "main+long",
            "long+mid+spiral+core-outer",
        }
        for name in self.lib.names():
            with self.subTest(subarray=name):
                policy = self.data[name]["curves"][export_ngect.CURVE_IMAGING][
                    "selection_policy"
                ]
                if name in fallback_names:
                    self.assertEqual(policy, export_ngect.POLICY_RELAXED_FALLBACK)
                else:
                    self.assertEqual(policy, export_ngect.POLICY_STRICT)

    def test_dropped_spans_cover_relaxed_and_out_of_run_points(self):
        core_spiral = self.data["core+spiral"]["curves"][export_ngect.CURVE_IMAGING]
        self.assertTrue(core_spiral["dropped_spans_log10_theta_mas"])
        long_point = self.data["long"]["curves"][export_ngect.CURVE_POINT_SOURCE]
        self.assertTrue(long_point["dropped_spans_log10_theta_mas"])
        for span in (
            core_spiral["dropped_spans_log10_theta_mas"]
            + long_point["dropped_spans_log10_theta_mas"]
        ):
            self.assertEqual(len(span), 2)
            self.assertTrue(all(math.isfinite(v) for v in span))
            self.assertLessEqual(span[0], span[1])


if __name__ == "__main__":
    unittest.main()

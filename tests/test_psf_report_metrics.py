"""Focused tests for PSF metrics exposed by the report."""

import json
import os
import sys
import tempfile
import unittest

CURVEGEN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "curvegen")
sys.path.insert(0, CURVEGEN)

import make_report as mr  # noqa: E402


class TestReportPsfMetricSummary(unittest.TestCase):
    def test_summary_reads_jsonl_and_keeps_derived_squared_volume_metrics(self):
        # A unit-peak Gaussian sampled through its first zero crossing.  The
        # negative sample makes the profile's first-null detector unambiguous.
        record = {
            "key": "natural_2.00_0.000",
            "res_geo_arcsec": 1.0,
            "r_arcsec": [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5],
            "psf": [1.0, 0.96, 0.85, 0.68, 0.50, 0.18, 0.0, -0.1],
            "bmaj_arcsec": 1.0,
            "bmin_arcsec": 1.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "demo_array.jsonl")
            with open(path, "w") as handle:
                handle.write(json.dumps(record) + "\n")
            old_order = mr.ACTIVE_ORDER
            try:
                mr.ACTIVE_ORDER = ("demo-array",)
                summary = mr.build_psf_metric_summary(directory)
            finally:
                mr.ACTIVE_ORDER = old_order
        metrics = summary["demo-array"][0]
        self.assertEqual(len(metrics), 6)
        self.assertEqual(metrics[0], "natural_2.00_0.000")
        self.assertGreater(metrics[2], 0)  # restoring-beam geo-mean FWHM
        self.assertGreater(metrics[3], 0)  # integral(B^2) in sr
        self.assertGreater(metrics[4], 0)  # signed-volume/Gaussian ratio


class TestBrowserPsfContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(CURVEGEN, "report_template.html")) as handle:
            cls.html = handle.read()

    def test_psf_plot_uses_restoring_beam_reference(self):
        self.assertIn("restoring_fwhm_geo_arcsec", self.html)
        self.assertIn("restoring beam", self.html)
        self.assertNotIn("drawGaussian(Number(entry.gaussian_fit", self.html)
        self.assertNotIn("robust core Gaussian", self.html)
        self.assertNotIn("legacy capture ends", self.html)
        self.assertNotIn("reference_gaussian_fwhm_arcsec", self.html)
        self.assertNotIn("gaussian_fit_fwhm_arcsec", self.html)
        self.assertNotIn("double_measured_fwhm_arcsec", self.html)

    def test_psf_plot_uses_piecewise_radius_scale_and_svg_legend(self):
        self.assertIn("const rKnee = 3, rmax = 10", self.html)
        self.assertIn("0.5 * plotWidth * v / rKnee", self.html)
        self.assertIn("piecewise linear; scale changes at 3", self.html)
        self.assertIn("r=1 FWHM", self.html)
        self.assertIn("const legendRows = [", self.html)
        self.assertIn("legendX = W - M.r - legendWidth", self.html)
        self.assertNotIn("2× measured-FWHM Gaussian", self.html)

    def test_summary_and_confusion_are_separate(self):
        self.assertIn("psf_squared_volume_first_null_sr", self.html)
        self.assertIn("confusion_beam_sqrt_sr", self.html)
        self.assertIn("Confusion: ', fmtConfusion", self.html)
        self.assertIn("confusion as an independent feasibility", self.html)

    def test_confusion_floor_is_gated_only_for_fixed_window_mfs(self):
        self.assertIn("if (DATA.fixed_window)", self.html)
        self.assertIn("requested sensitivity is below the MFS confusion floor",
                      self.html)
        # The mono/spectral-cube path computes and displays confusion but does
        # not use it in the feasibility decision.
        self.assertIn("Mono/spectral-cube selection reports it but deliberately ignores",
                      self.html.replace("\\n", " ").replace("\n", " "))


if __name__ == "__main__":
    unittest.main()

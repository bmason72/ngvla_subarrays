"""Static contract checks for the dependency-free browser calculator."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "curvegen" / "report_template.html"


class TestReportCalculatorControls(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = TEMPLATE.read_text()

    def test_requested_controls_are_present(self):
        for element_id in ["calc-s0", "calc-beam-margin", "calc-sens-unit",
                           "calc-warning"]:
            with self.subTest(element_id=element_id):
                self.assertIn('id="%s"' % element_id, self.text)
        for value in ['value="0.02"', 'value="0.05"', 'value="0.10"',
                      'value="0.15"', 'value="0.20"']:
            self.assertIn(value, self.text)

    def test_internal_fallback_and_exact_beam_are_not_selectable(self):
        self.assertNotIn('id="calc-goal-mode"', self.text)
        self.assertNotIn('<option value="0">exact</option>', self.text)
        self.assertNotIn('<option value="0.01">1%</option>', self.text)
        self.assertIn("sensitivity === null ? 'fiducial' : 'explicit'", self.text)

    def test_sensitivity_accepts_any_positive_float(self):
        self.assertIn('id="calc-sens" name="sens" type="number" min="0" '
                      'step="any"', self.text)
        self.assertIn("if (!finitePositive(value))", self.text)

    def test_bandwidth_accepts_sub_mhz_values(self):
        self.assertIn('id="calc-bandwidth" name="bandwidth" type="number" '
                      'min="0" step="any"', self.text)

    def test_millijansky_per_beam_unit_is_converted_to_microjanskys(self):
        self.assertIn('<option value="mJy">mJy/beam</option>', self.text)
        self.assertIn("request.sensUnit === 'mJy'", self.text)
        self.assertIn("goalMicroJy = request.sensitivity * 1000", self.text)

    def test_resolution_accepts_sub_milliarcsecond_precision(self):
        self.assertIn('id="calc-res" name="resolution" type="number" min="0" '
                      'step="any"', self.text)
        self.assertIn("readCalcNumber('calc-res', 'Resolution', errors)", self.text)

    def test_report_header_copy_and_stats_location(self):
        self.assertNotIn("Track 2 curve generation", self.text)
        self.assertNotIn("5&ndash;6 Jul 2026", self.text)
        self.assertIn("adaptive refinement where needed", self.text)
        self.assertIn('href="https://ngect.nrao.edu"', self.text)
        self.assertGreater(self.text.index('id="tiles"'),
                           self.text.index('id="data-table"'))

    def test_adaptive_validation_is_explained_and_drawn(self):
        self.assertIn("every adaptive cell touching the point passed", self.text)
        self.assertIn("residual-validated)</p>", self.text)
        self.assertIn("p.validation === 'residual-validated'", self.text)
        self.assertIn("p.validation !== 'not-assessed'", self.text)
        self.assertIn("l: 'residual-validated results'", self.text)
        self.assertIn("<th>adaptive validation</th>", self.text)

    def test_beam_margin_is_request_driven(self):
        self.assertNotIn("CALC_BEAM_MARGIN", self.text)
        self.assertIn("request.beamMargin", self.text)

    def test_strict_first_and_no_strict_warning_are_explicit(self):
        self.assertIn("groupA - groupB", self.text)
        self.assertIn("no feasible subarray meets the ", self.text)
        self.assertIn("row.skirtMet", self.text)

    def test_fiducial_and_kelvin_formulas_are_present(self):
        self.assertIn("Math.sqrt(60 / request.bandwidth)", self.text)
        self.assertIn("main_natural_1min_fiducial", self.text)
        self.assertIn("kelvinToMicroJy", self.text)

    def test_confusion_is_separate_and_blocks_only_mfs(self):
        self.assertIn("psf_squared_volume_first_null_sr", self.text)
        self.assertIn("Math.sqrt(omega2AtFreq / gaussianOmega2)", self.text)
        self.assertIn("if (DATA.fixed_window)", self.text)
        self.assertIn("goalMicroJy < confusionMicroJy", self.text)
        self.assertIn("never added", self.text)

    def test_psf_restoring_beam_and_volume_ratio_are_reported(self):
        self.assertIn("restoring_fwhm_geo_arcsec", self.text)
        self.assertNotIn("reference_gaussian_fwhm_arcsec", self.text)
        self.assertNotIn("gaussian_fit_fwhm_arcsec", self.text)
        self.assertNotIn("double_measured_fwhm_arcsec", self.text)
        self.assertIn("psf_to_gaussian_volume_ratio", self.text)
        self.assertIn("tclean restoring-beam volume", self.text)

    def test_single_channel_visibility_estimate_is_in_ranked_listing(self):
        self.assertIn("const CALC_CORRELATOR_DUMP_SECONDS = 5", self.text)
        self.assertIn("const CALC_VISIBILITY_CHANNELS = 1", self.text)
        self.assertIn("nAnt * (nAnt - 1) / 2", self.text)
        self.assertIn("fmtVisibilityCount(row.nVisibilities)", self.text)
        self.assertIn("'visibilities'", self.text)
        self.assertIn("no autocorrelations", self.text)

    def test_skirt_controls_are_synchronized_both_directions(self):
        self.assertIn("plotS0.value = currentS0", self.text)
        self.assertIn("calcSelect.value = currentS0", self.text)


if __name__ == "__main__":
    unittest.main()

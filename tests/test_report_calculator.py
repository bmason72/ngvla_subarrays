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
        for value in ['value="0.01"', 'value="0.05"', 'value="0.10"',
                      'value="0.15"', 'value="0.20"']:
            self.assertIn(value, self.text)

    def test_internal_fallback_and_exact_beam_are_not_selectable(self):
        self.assertNotIn('id="calc-goal-mode"', self.text)
        self.assertNotIn('<option value="0">exact</option>', self.text)
        self.assertIn("sensitivity === null ? 'fiducial' : 'explicit'", self.text)

    def test_sensitivity_accepts_any_positive_float(self):
        self.assertIn('id="calc-sens" name="sens" type="number" min="0" '
                      'step="any"', self.text)
        self.assertIn("if (!finitePositive(value))", self.text)

    def test_report_header_copy_and_stats_location(self):
        self.assertNotIn("Track 2 curve generation", self.text)
        self.assertNotIn("5&ndash;6 Jul 2026", self.text)
        self.assertIn("adaptive refinement where needed", self.text)
        self.assertIn('href="https://ngect.nrao.edu"', self.text)
        self.assertGreater(self.text.index('id="tiles"'),
                           self.text.index('id="data-table"'))

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

    def test_skirt_controls_are_synchronized_both_directions(self):
        self.assertIn("plotS0.value = currentS0", self.text)
        self.assertIn("calcSelect.value = currentS0", self.text)


if __name__ == "__main__":
    unittest.main()

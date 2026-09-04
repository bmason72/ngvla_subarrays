"""Tests for the CASA-free PSF profile payload transform."""

import json
import unittest

from curvegen.export_psf_data import (parse_profile_line,
                                      derive_psf_metrics,
                                      transform_profile_lines,
                                      PROFILE_LINE_ERRORS)


def profile(key, res=0.1, **extra):
    record = {
        "key": key,
        "res_geo_arcsec": res,
        "r_arcsec": [0.0, 0.1],
        "psf": [1.0, 0.2],
    }
    record.update(extra)
    return json.dumps(record)


class TestTransformProfileLines(unittest.TestCase):
    def test_last_line_wins(self):
        lines = [
            profile("briggs_0.40_1.000", res=0.2),
            profile("briggs_0.40_1.000", res=0.3),
        ]
        payloads, warnings = transform_profile_lines(lines)
        self.assertEqual(payloads["briggs_0.40_1.000"]["res_geo_arcsec"],
                         0.3)
        self.assertEqual(warnings, [])

    def test_negative_zero_key_is_normalized(self):
        payloads, warnings = transform_profile_lines(
            [profile("briggs_-0.00_2.500")])
        self.assertNotIn("briggs_-0.00_2.500", payloads)
        self.assertIn("briggs_0.00_2.500", payloads)
        self.assertEqual(warnings, [])

    def test_cut_fields_are_passed_through(self):
        extras = {
            "bmaj_arcsec": 0.12,
            "bmin_arcsec": 0.08,
            "bpa_deg": -35.0,
            "cut_r_arcsec": [-0.1, 0.0, 0.1],
            "cut_maj": [0.2, 1.0, 0.2],
            "cut_min": [0.1, 1.0, 0.1],
        }
        payloads, warnings = transform_profile_lines(
            [profile("natural_2.00_0.000", **extras)])
        payload = payloads["natural_2.00_0.000"]
        for field, value in extras.items():
            self.assertEqual(payload[field], value)
        self.assertEqual(warnings, [])

    def test_malformed_json_is_skipped_with_warning(self):
        payloads, warnings = transform_profile_lines([
            profile("natural_2.00_0.000"),
            '{"key": "broken"',
            profile("briggs_-2.00_0.000"),
        ])
        self.assertEqual(len(payloads), 2)
        self.assertEqual(len(warnings), 1)
        self.assertIn("line 2:", warnings[0])


class TestDerivedPsfMetrics(unittest.TestCase):
    def test_gaussian_core_fit_and_first_null_volume(self):
        # Unit Gaussian with FWHM 1 arcsec, followed by an artificial first
        # null at 2 FWHM.  The enclosed volume is effectively the full
        # Gaussian volume at that radius.
        radii = [i * 0.05 for i in range(41)] + [2.05]
        values = [2.0 ** (-4.0 * radius * radius) for radius in radii[:-1]]
        values.append(-0.01)
        metrics = derive_psf_metrics({"r_arcsec": radii, "psf": values})
        self.assertAlmostEqual(metrics["measured_fwhm_arcsec"], 1.0,
                               delta=0.01)
        self.assertAlmostEqual(metrics["gaussian_fit_fwhm_arcsec"], 1.0,
                               delta=0.01)
        self.assertAlmostEqual(metrics["first_null_arcsec"], 2.0,
                               delta=0.06)
        self.assertAlmostEqual(metrics["psf_to_gaussian_volume_ratio"], 1.0,
                               delta=0.02)
        self.assertAlmostEqual(
            metrics["psf_to_gaussian_squared_volume_ratio"], 1.0,
            delta=0.03)
        self.assertAlmostEqual(
            metrics["confusion_beam_sqrt_sr"] ** 2,
            metrics["psf_squared_volume_first_null_sr"])

    def test_huber_fit_resists_one_bad_core_bin(self):
        radii = [i * 0.05 for i in range(13)]
        values = [2.0 ** (-4.0 * radius * radius) for radius in radii]
        values[7] = 0.9
        metrics = derive_psf_metrics({"r_arcsec": radii, "psf": values})
        self.assertAlmostEqual(metrics["gaussian_fit_fwhm_arcsec"], 1.0,
                               delta=0.08)

    def test_capture_edge_is_not_treated_as_a_null(self):
        metrics = derive_psf_metrics({
            "r_arcsec": [0.0, 0.25, 0.5, 0.75],
            "psf": [1.0, 0.84, 0.5, 0.21],
        })
        self.assertNotIn("first_null_arcsec", metrics)
        self.assertNotIn("psf_volume_first_null_sr", metrics)
        self.assertNotIn("confusion_beam_sqrt_sr", metrics)

    def test_positive_composite_pedestal_uses_first_radial_minimum(self):
        metrics = derive_psf_metrics({
            "r_arcsec": [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5,
                         1.75, 2.0, 2.25],
            "psf": [1.0, 0.82, 0.48, 0.30, 0.22, 0.24, 0.28,
                    0.35, 0.40, 0.42],
        })
        self.assertEqual(metrics["first_null_method"], "radial_minimum")
        self.assertGreater(metrics["first_null_value"], 0)
        self.assertIn("psf_squared_volume_first_null_sr", metrics)

    def test_nan_line_is_skipped_previous_valid_line_wins(self):
        """A line whose psf array contains a NaN reads back fine under
        Python's json module (which is not strict-JSON compliant), but the
        release page embeds this exporter's output as literal JS/JSON, so
        such a line must be warned about and skipped -- the previous valid
        line for that key then wins, per the append-only/last-line-wins
        convention.  json.dumps rejects NaN outright, so the poisoned line
        is built as a raw string, the way real corruption would arrive."""
        good = profile("briggs_0.40_1.000", res=0.2)
        poisoned = ('{"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.3, '
                   '"r_arcsec": [0.0, 0.1], "psf": [1.0, NaN]}')
        payloads, warnings = transform_profile_lines([good, poisoned])
        self.assertEqual(payloads["briggs_0.40_1.000"]["res_geo_arcsec"], 0.2)
        self.assertEqual(len(warnings), 1)
        self.assertIn("line 2:", warnings[0])


class TestParseProfileLine(unittest.TestCase):
    """parse_profile_line is THE shared definition of a valid profile line,
    used directly by transform_profile_lines above and by backfill_psf.
    cut_bearing_keys -- so it is tested directly here too."""

    def test_valid_line_round_trips(self):
        extras = {"cut_r_arcsec": [-0.1, 0.0, 0.1],
                 "cut_maj": [0.2, 1.0, 0.2], "cut_min": [0.1, 1.0, 0.1]}
        key, record = parse_profile_line(
            profile("briggs_-0.00_2.500", res=0.3, **extras))
        # the key comes back normalize_key-canonicalized
        self.assertEqual(key, "briggs_0.00_2.500")
        # the record is intact (nothing stripped -- that's the caller's job)
        self.assertEqual(record["res_geo_arcsec"], 0.3)
        self.assertEqual(record["cut_maj"], [0.2, 1.0, 0.2])

    def test_nan_line_raises(self):
        line = ('{"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.1, '
               '"r_arcsec": [0.0, 0.1], "psf": [1.0, NaN]}')
        with self.assertRaises(PROFILE_LINE_ERRORS):
            parse_profile_line(line)

    def test_missing_field_line_raises(self):
        line = json.dumps({"key": "briggs_0.40_1.000",
                          "res_geo_arcsec": 0.1, "r_arcsec": [0.0, 0.1]})
        # "psf" is missing
        with self.assertRaises(PROFILE_LINE_ERRORS):
            parse_profile_line(line)

    def test_non_dict_line_raises(self):
        with self.assertRaises(PROFILE_LINE_ERRORS):
            parse_profile_line(json.dumps([1, 2, 3]))


if __name__ == "__main__":
    unittest.main()

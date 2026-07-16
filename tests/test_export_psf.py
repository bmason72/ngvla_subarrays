"""Tests for the CASA-free PSF profile payload transform."""

import json
import unittest

from curvegen.export_psf_data import transform_profile_lines


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


if __name__ == "__main__":
    unittest.main()

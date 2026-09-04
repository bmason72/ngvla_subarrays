"""Portable Memo-96 data export and kernel parity tests."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

from sa_select import sensitivity
from sa_select.data.export_sensitivity_data import export


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "ngvla-sensitivity-calculator"


class TestSensitivityDataExport(unittest.TestCase):

    def test_export_round_trips_and_records_checksums(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sensitivity.json"
            export(UPSTREAM, output)
            payload = json.loads(output.read_text())
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(set(payload["receiver_data"]),
                         {"BAND_1", "BAND_2", "BAND_3", "BAND_4",
                          "BAND_5", "BAND_6"})
        self.assertEqual(payload["source_sha256"],
                         sensitivity.data_info()["source_sha256"])

    def test_packaged_kernel_matches_upstream_natural_path(self):
        source = UPSTREAM / "ngVLA_sensitivity_calculator.py"
        spec = importlib.util.spec_from_file_location("_parity_upstream", source)
        upstream = importlib.util.module_from_spec(spec)
        with contextlib.chdir(UPSTREAM), contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(upstream)

        cases = [("main", 30.0, None), ("core", 30.0, None),
                 ("sba", 1.5, None), ("spiral+mid", 90.0, None),
                 ("mid+long", 30.0, 2000.0)]
        for name, frequency, delta_v in cases:
            with self.subTest(name=name, frequency=frequency, delta_v=delta_v):
                kind = "continuum" if delta_v is None else "line"
                dv_arg = 10000.0 if delta_v is None else delta_v
                with contextlib.chdir(UPSTREAM), \
                        contextlib.redirect_stdout(io.StringIO()):
                    expected = upstream.sigma_ps_fn(
                        subarray=name, freq=frequency, type_cal=kind,
                        t_int=3600.0, theta=-1, delta_v=dv_arg,
                        verbose=False)[0][1] * 1e-6
                actual = sensitivity.natural_rms(
                    name, frequency, t_obs_hr=1.0, delta_v=delta_v,
                    include_confusion=True)
                self.assertAlmostEqual(actual, expected,
                                       delta=1e-12 * expected)

    def test_confusion_is_separate_from_default_thermal_rms(self):
        parameters = sensitivity._SUBARRAY_TABLE["core"]
        theta_arcsec = float(parameters["theta_nat_30_GHz"]) / 1000.0
        omega2 = 0.5 * sensitivity._beam_solid_angle_sr(theta_arcsec)
        confusion = sensitivity.confusion_rms(30.0, theta_arcsec, omega2)
        thermal = sensitivity.natural_rms("core", 30.0)
        upstream_total = sensitivity.natural_rms(
            "core", 30.0, include_confusion=True)
        self.assertGreater(confusion, 0)
        self.assertAlmostEqual(upstream_total ** 2,
                               thermal ** 2 + confusion ** 2,
                               delta=1e-20)

    def test_confusion_scales_with_sqrt_integral_beam_squared(self):
        base = sensitivity.confusion_rms(1.4, 10.0)
        gaussian_omega2 = 0.5 * sensitivity._beam_solid_angle_sr(10.0)
        doubled_variance_area = sensitivity.confusion_rms(
            1.4, 10.0, 2.0 * gaussian_omega2)
        self.assertAlmostEqual(doubled_variance_area / base, 2.0 ** 0.5)

    def test_confusion_model_is_serializable_and_sorted(self):
        model = sensitivity.confusion_model()
        json.dumps(model)
        theta = model["theta_fwhm_arcsec"]
        self.assertEqual(theta, sorted(theta))


if __name__ == "__main__":
    unittest.main()

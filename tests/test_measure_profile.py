"""
Pure-numpy test for curvegen/measure.py radial_profile (no casatools):
a synthetic 2-D Gaussian's azimuthal profile must recover the input FWHM
and be normalized and monotone-decreasing out to 1 FWHM.

Run from the repository root:

    python3 -m unittest tests.test_measure_profile
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "curvegen"))


class TestRadialProfile(unittest.TestCase):

    def _radial_profile(self):
        try:
            from measure import radial_profile
        except ImportError as e:
            self.skipTest("curvegen/measure.py not importable CASA-free: %s"
                          % e)
        return radial_profile

    def test_gaussian_profile(self):
        radial_profile = self._radial_profile()
        fwhm = 1.0                       # arcsec
        cell = 0.02                      # arcsec/pixel: 50 px per FWHM
        n = 301
        c = n // 2
        yy, xx = np.mgrid[0:n, 0:n]
        r_pix = np.hypot(yy - c, xx - c) * cell
        sigma = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
        img = np.exp(-0.5 * (r_pix / sigma) ** 2)

        r, prof = radial_profile(img, (c, c), cell, r_max_arcsec=2.0,
                                 n_bins=80)
        self.assertEqual(len(r), len(prof))
        self.assertTrue(len(r) > 10)

        # normalized: the input peak is 1 and the innermost annular mean
        # must sit essentially at it
        self.assertAlmostEqual(float(prof[0]), 1.0, delta=0.02)

        # monotone decreasing out to 1 FWHM
        within = r <= fwhm
        self.assertTrue((np.diff(prof[within]) < 0).all(),
                        "profile not monotone-decreasing inside 1 FWHM")

        # recovered half-max radius = FWHM/2 within 5%
        i = int(np.argmax(prof < 0.5))
        self.assertGreater(i, 0)
        r_half = float(np.interp(0.5, [prof[i], prof[i - 1]],
                                 [r[i], r[i - 1]]))
        self.assertAlmostEqual(r_half, fwhm / 2.0, delta=0.05 * fwhm / 2.0)

    def test_empty_bins_dropped(self):
        radial_profile = self._radial_profile()
        # bin width far below the pixel size: inner bins are empty and must
        # be dropped, not returned as NaN
        img = np.ones((21, 21))
        r, prof = radial_profile(img, (10, 10), 1.0, r_max_arcsec=10.0,
                                 n_bins=40)
        self.assertEqual(len(r), len(prof))
        self.assertTrue(np.isfinite(prof).all())
        self.assertLess(len(r), 40)

    def test_no_module_level_casatools_import(self):
        """The CASA-free contract, enforced: casatools must only be imported
        lazily inside functions (a reintroduced top-level import cannot be
        caught at runtime under CASA's python, where the import succeeds)."""
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "curvegen", "measure.py")
        with open(path) as f:
            tree = ast.parse(f.read())
        for node in tree.body:                       # module level only
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            self.assertFalse(
                any(n.split(".")[0] in ("casatools", "casatasks")
                    for n in names),
                "measure.py has a module-level CASA import again: %s" % names)


class TestCaptureProfile(unittest.TestCase):
    """Sweep.capture_profile JSONL semantics (no CASA imaging: the profile
    function is stubbed; sweep.py itself needs casatasks, so skip without)."""

    def _sweep_mod(self):
        try:
            import importlib
            return importlib.import_module("sweep")
        except ImportError as e:
            self.skipTest("curvegen/sweep.py needs CASA here: %s" % e)

    def test_jsonl_line_stem_rounding_and_append(self):
        import json
        import tempfile
        sweep_mod = self._sweep_mod()

        class FakeSweep(sweep_mod.Sweep):
            def __init__(self, subarray):        # skip CASA/file setup
                self.subarray = subarray

        orig_profile = sweep_mod.psf_radial_profile
        orig_dir = sweep_mod.PROFILE_DIR
        try:
            sweep_mod.psf_radial_profile = \
                lambda path, res: ([0.123456789, 0.2], [1.0, 0.987654321])
            with tempfile.TemporaryDirectory() as tmp:
                sweep_mod.PROFILE_DIR = tmp
                s = FakeSweep("spiral+mid")
                s.capture_profile("natural_2.00_0.000", "x.psf", 0.0111234567)
                s.capture_profile("natural_2.00_0.000", "x.psf", 0.0111234567)
                path = os.path.join(tmp, "spiral_mid.jsonl")   # stem: + -> _
                self.assertTrue(os.path.isfile(path))
                with open(path) as f:
                    lines = f.read().splitlines()
                # a re-measured point appends; consumers take the LAST line
                self.assertEqual(len(lines), 2)
                rec = json.loads(lines[-1])
                self.assertEqual(rec["key"], "natural_2.00_0.000")
                # floats rounded to 5 significant digits
                self.assertEqual(rec["res_geo_arcsec"], 0.011123)
                self.assertEqual(rec["r_arcsec"], [0.12346, 0.2])
                self.assertEqual(rec["psf"], [1.0, 0.98765])
        finally:
            sweep_mod.psf_radial_profile = orig_profile
            sweep_mod.PROFILE_DIR = orig_dir


if __name__ == "__main__":
    unittest.main()

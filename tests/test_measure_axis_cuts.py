"""
Pure-numpy test for curvegen/measure.py psf_axis_cuts (no casatools):
a synthetic elliptical Gaussian PSF's major/minor-axis cuts must recover the
input bmaj/bmin on the RIGHT axis.  Two distinct bugs are checked for:
  - a sin/cos (major/minor) swap, which a plain sign flip along a pixel
    axis would NOT catch (the cut is a line through the symmetric PSF
    center, so flipping both signs together just walks it backwards); and
  - a per-axis sign error (e.g. the standard CASA case, R.A. increment
    negative / Dec. increment positive) that flips only ONE pixel axis'
    relationship to the sky -- this samples neither the true major nor
    minor axis, and is NOT caught by an all-positive-signs test.

Run from the repository root:

    python3 -m unittest tests.test_measure_axis_cuts
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "curvegen"))


def _elliptical_gaussian(n, cell, bmaj, bmin, bpa_deg, sign0=1.0, sign1=1.0):
    """Build a synthetic PSF cutout in the SAME [axis0, axis1] convention
    psf_axis_cuts documents: bpa is measured in SKY coordinates from north
    toward east, and `sign0`/`sign1` say how each PIXEL axis maps to those
    sky directions (+1: increasing pixel index increases the sky
    coordinate; -1: decreases it) -- e.g. sign0=-1 reproduces the standard
    CASA/FITS case where +axis0 (R.A.) is WEST.  Peak is 1.0 at the center
    pixel (n must be odd).
    """
    c = n // 2
    a0, a1 = np.mgrid[0:n, 0:n]                    # a0: axis0, a1: axis1
    d0, d1 = (a0 - c) * cell, (a1 - c) * cell
    east, north = sign0 * d0, sign1 * d1            # sky-frame offsets
    pa = np.deg2rad(bpa_deg)
    along_maj = east * np.sin(pa) + north * np.cos(pa)   # onto major axis
    along_min = east * np.cos(pa) - north * np.sin(pa)   # onto minor axis
    sig_maj = bmaj / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    sig_min = bmin / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    return np.exp(-0.5 * ((along_maj / sig_maj) ** 2
                         + (along_min / sig_min) ** 2))


def _fwhm_from_cut(r, cut):
    """Half-max radius x2, from the positive-r half of a symmetric cut
    (linear interpolation between the last sample >= 0.5 and the first < 0.5)."""
    r = np.asarray(r, dtype=float)
    cut = np.array([np.nan if v is None else v for v in cut], dtype=float)
    pos = r >= 0
    r_pos, c_pos = r[pos], cut[pos]
    i = int(np.argmax(c_pos < 0.5))
    assert i > 0, "cut never drops below half max"
    r_half = np.interp(0.5, [c_pos[i], c_pos[i - 1]], [r_pos[i], r_pos[i - 1]])
    return 2.0 * r_half


class TestPsfAxisCuts(unittest.TestCase):

    def _psf_axis_cuts(self):
        try:
            from measure import psf_axis_cuts
        except ImportError as e:
            self.skipTest("curvegen/measure.py not importable CASA-free: %s"
                          % e)
        return psf_axis_cuts

    def _check_one_bpa(self, bpa_deg, sign0=1.0, sign1=1.0):
        psf_axis_cuts = self._psf_axis_cuts()
        bmaj, bmin = 1.0, 0.5                        # arcsec; axis ratio 2
        cell = 0.02                                  # arcsec/pixel
        n = 301
        c = n // 2
        cutout = _elliptical_gaussian(n, cell, bmaj, bmin, bpa_deg,
                                      sign0, sign1)
        r_max = 3.0 * np.sqrt(bmaj * bmin)           # matches sweep's 3xres_geo

        r, cut_maj, cut_min = psf_axis_cuts(cutout, (c, c), cell, bpa_deg,
                                            r_max, n=161,
                                            sign0=sign0, sign1=sign1)
        r = np.asarray(r)
        self.assertEqual(len(r), 161)
        self.assertEqual(len(cut_maj), len(r))
        self.assertEqual(len(cut_min), len(r))

        # (b) peak at r=0, value ~1.0 (r=0 lands exactly on the center pixel)
        i0 = int(np.argmin(np.abs(r)))
        self.assertAlmostEqual(r[i0], 0.0, delta=1e-9)
        self.assertAlmostEqual(cut_maj[i0], 1.0, delta=1e-6)
        self.assertAlmostEqual(cut_min[i0], 1.0, delta=1e-6)

        # (c) symmetric within tolerance: cut(-r) ~= cut(+r)
        cut_maj_arr = np.array([np.nan if v is None else v for v in cut_maj])
        cut_min_arr = np.array([np.nan if v is None else v for v in cut_min])
        np.testing.assert_allclose(cut_maj_arr, cut_maj_arr[::-1], atol=0.01)
        np.testing.assert_allclose(cut_min_arr, cut_min_arr[::-1], atol=0.01)

        # (a) + (d) FWHM recovered on the RIGHT axis, within 5%: this is the
        # major/minor-swap detector -- with axis ratio 2, a sin/cos swap
        # would report cut_maj's FWHM ~= bmin (0.5) and cut_min's ~= bmaj
        # (1.0), failing both assertions below.
        fwhm_maj = _fwhm_from_cut(r, cut_maj)
        fwhm_min = _fwhm_from_cut(r, cut_min)
        self.assertAlmostEqual(fwhm_maj, bmaj, delta=0.05 * bmaj)
        self.assertAlmostEqual(fwhm_min, bmin, delta=0.05 * bmin)

    def test_bpa_0(self):
        self._check_one_bpa(0.0)

    def test_bpa_30(self):
        self._check_one_bpa(30.0)

    def test_bpa_90(self):
        self._check_one_bpa(90.0)

    def test_bpa_minus_60(self):
        self._check_one_bpa(-60.0)

    def test_standard_casa_signs_negative_ra_increment(self):
        """The standard CASA/FITS convention: axis0 (R.A.) increment is
        NEGATIVE (+axis0 pixel index is WEST), axis1 (Dec.) is POSITIVE
        (+axis1 is north) -- i.e. sign0=-1, sign1=+1.  This differs from a
        whole-vector sign flip (sign0=sign1=-1, which is just a harmless
        mirror): flipping only ONE axis's sign changes which line through
        the center is sampled, so this must be handled per-axis or the cuts
        land on neither the true major nor minor axis."""
        self._check_one_bpa(30.0, sign0=-1.0, sign1=1.0)

    def test_out_of_bounds_is_none_not_clipped_or_nan(self):
        psf_axis_cuts = self._psf_axis_cuts()
        # a tiny cutout with r_max reaching past its edges: samples beyond
        # the last full pixel must come back None (json-safe), not clipped
        # to the edge value or silently NaN.
        n = 21
        c = n // 2
        cutout = _elliptical_gaussian(n, 0.02, 1.0, 0.5, 0.0)
        r, cut_maj, _cut_min = psf_axis_cuts(cutout, (c, c), 0.02, 0.0,
                                             r_max_arcsec=1.0, n=41)
        self.assertIn(None, cut_maj)
        # samples that DID land inside the cutout must be plain floats
        self.assertTrue(any(v is not None for v in cut_maj))
        in_bounds = [v for v in cut_maj if v is not None]
        self.assertTrue(all(isinstance(v, float) for v in in_bounds))

    def test_no_module_level_casatools_import(self):
        """Shared contract with test_measure_profile.py: casatools must only
        be imported lazily inside functions, so this test file and
        psf_axis_cuts stay importable/runnable without CASA."""
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "curvegen", "measure.py")
        with open(path) as f:
            tree = ast.parse(f.read())
        for node in tree.body:
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            self.assertFalse(
                any(n.split(".")[0] in ("casatools", "casatasks")
                    for n in names),
                "measure.py has a module-level CASA import again: %s" % names)


if __name__ == "__main__":
    unittest.main()

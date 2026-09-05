"""
Tests for sa_select/stroh.py (MStroh delivery adapters, docs/plans/RELEASE_PLAN.md T5).

A synthetic subarray_data.json fixture covers the format logic everywhere;
tests against the real delivery run only where mstroh/ is present (it is
gitignored -- an external delivery, not part of this repo).
"""

import contextlib
import io
import json
import os
import tempfile
import unittest

import numpy as np

from sa_select import stroh
from sa_select.schema import ObservingRequest
from sa_select.selector import select_subarrays

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MSTROH_JSON = os.path.join(REPO_ROOT, "mstroh", "subarray_data.json")
HAVE_MSTROH = os.path.isfile(MSTROH_JSON)

SQRT2 = np.sqrt(2.0)


def synthetic_json_path(case):
    """A one-subarray subarray_data.json: eta rises linearly from 1 to 3 over
    log10(theta_mas, sqrt2 convention) in [3, 4] (i.e. ~0.7-7 arcsec geo)."""
    from scipy.interpolate import CubicSpline
    x = np.linspace(3.0, 4.0, 9)
    cs = CubicSpline(x, 1.0 + 2.0 * (x - 3.0))
    data = {
        "toy": dict(b_min=30.0, b_max=1000.0, N_ant=20,
                    theta_nat_30_GHz=1000.0,       # sqrt2 convention, mas
                    spline_type="cubic",
                    spline_params=[cs.c.tolist(), cs.x.tolist()]),
        "nospline": dict(b_min=10.0, b_max=100.0, N_ant=6,
                         theta_nat_30_GHz=5000.0, spline_type="none"),
    }
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    case.addCleanup(os.unlink, f.name)
    json.dump(data, f)
    f.close()
    return f.name


class TestSyntheticPackage(unittest.TestCase):

    def setUp(self):
        self.path = synthetic_json_path(self)
        self.data = stroh.load_subarray_data(self.path)

    def test_load_converts_conventions(self):
        toy = self.data["toy"]
        self.assertIsNotNone(toy["ppoly"])
        self.assertAlmostEqual(toy["theta_nat_arcsec"], 1.0 / SQRT2, places=6)
        self.assertIsNone(self.data["nospline"]["ppoly"])

    def test_curve_samples_geometry_and_notes(self):
        samples = stroh.curve_samples("toy", self.data["toy"], n_points=21)
        self.assertEqual(len(samples), 21)
        # x=3 -> theta 1000 mas sqrt2 conv -> 1/sqrt2 arcsec geo, eta 1
        self.assertAlmostEqual(samples[0].resolution, 1.0 / SQRT2, places=6)
        self.assertAlmostEqual(samples[0].eta, 1.0, places=6)
        self.assertAlmostEqual(samples[-1].eta, 3.0, places=6)
        for s in samples:
            self.assertIsNone(s.skirt)                # point-source only
            self.assertEqual(s.source, "stroh")
            self.assertIn("placeholder", s.note)

    def test_point_source_selection_feasible_with_warning(self):
        lib = stroh.curve_library(self.path)
        request = ObservingRequest(resolution=2.0, frequency=30,
                                   imaging=False)
        result = select_subarrays(request, library=lib)
        names = [c.subarray.name for c in result.feasible]
        self.assertIn("toy", names)
        toy = result.feasible[names.index("toy")]
        self.assertTrue(any("placeholder" in w for w in toy.warnings))

    def test_imaging_selection_finds_no_sculpted_samples(self):
        lib = stroh.curve_library(self.path)
        request = ObservingRequest(resolution=2.0, frequency=30,
                                   imaging=True)
        result = select_subarrays(request, library=lib)
        self.assertEqual(result.feasible, [])

    def test_no_spline_subarray_is_infeasible_not_crashing(self):
        lib = stroh.curve_library(self.path)
        request = ObservingRequest(resolution=2.0, frequency=30,
                                   imaging=False)
        result = select_subarrays(request, library=lib)
        infeasible = {c.subarray.name for c in result.infeasible}
        self.assertIn("nospline", infeasible)


class TestCfgAdapter(unittest.TestCase):

    def _cfg(self, rows):
        f = tempfile.NamedTemporaryFile("w", suffix=".cfg", delete=False)
        self.addCleanup(os.unlink, f.name)
        f.write("# observatory=NGVLA\n# coordsys=XYZ\n")
        for r in rows:
            f.write("%f %f %f 18.0 %s\n" % r)
        f.close()
        return f.name

    def test_geometry_and_uvcut(self):
        # three antennas on a line: baselines 100, 900, 1000 m
        path = self._cfg([(0, 0, 0, "a"), (100, 0, 0, "b"), (1000, 0, 0, "c")])
        info = stroh.subarray_info_from_cfg("toy", path)
        self.assertEqual(info.n_ant, 3)
        self.assertAlmostEqual(info.b_min_m, 100.0)
        self.assertAlmostEqual(info.b_max_m, 1000.0)
        cut = stroh.subarray_info_from_cfg("toy", path, min_uvrange_m=150.0)
        self.assertAlmostEqual(cut.b_min_m, 900.0)
        self.assertIn("uvrange>150", cut.las_coeff_note)


@unittest.skipUnless(HAVE_MSTROH, "mstroh/ delivery not present")
class TestRealDelivery(unittest.TestCase):
    """Spot checks against docs/architecture/mstroh_comparison.md's verified numbers."""

    def test_core_native_beam(self):
        data = stroh.load_subarray_data(MSTROH_JSON)
        # 711.2 mas geo (comparison memo table, +0.16% vs ours)
        self.assertAlmostEqual(data["core"]["theta_nat_arcsec"], 0.7112,
                               delta=0.001)

    def test_spiral_spline_values(self):
        data = stroh.load_subarray_data(MSTROH_JSON)
        pp = data["spiral"]["ppoly"]
        eta_98 = float(pp(np.log10(98 * SQRT2)))
        self.assertAlmostEqual(eta_98, 1.28, delta=0.01)

    def test_cli_stroh_query(self):
        from sa_select import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--stroh", MSTROH_JSON, "--resolution", "1.0",
                             "--frequency", "30", "--point-source"])
        self.assertEqual(code, 0)
        self.assertIn("stroh", out.getvalue())


if __name__ == "__main__":
    unittest.main()

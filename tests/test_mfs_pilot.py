"""
Tests for the MFS imaging pilot launcher's CASA-free pieces (MFS-3 imaging
half, docs/plans/mfs-imaging-pilot-spec.md):
  * curvegen/mfs_pilot_points.py  -- the 10-point pilot lattice generator
  * curvegen/mfs_pilot_compare.py -- the nchan-convergence / timing comparator

Nothing here calls tclean or simulate.py, and nothing writes into the real
curvegen/results-*/ directories (a placeholder test once appended real rows
to results/core.csv -- see docs/plans/PLAN.md gotchas -- so every CSV here
lives under a tempfile.mkdtemp() directory).

Run from the repo root:
    /work2/10240/bmason72/stampede3/casaenv/bin/casapy -m unittest \
        tests.test_mfs_pilot
"""

import csv
import os
import shutil
import sys
import tempfile
import unittest

CURVEGEN = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "curvegen")
sys.path.insert(0, CURVEGEN)

import mfs_pilot_points as points_mod          # noqa: E402
import mfs_pilot_compare as compare_mod        # noqa: E402

CSV_FIELDS = ["subarray", "weighting", "robust", "taper_mas", "imsize",
              "cell_arcsec", "bmaj_arcsec", "bmin_arcsec", "bpa_deg",
              "res_geo_arcsec", "sigma_dirty", "skirt", "status", "error",
              "elapsed_s"]


def row(weighting, robust, taper_mas, res_geo_arcsec=0.05, sigma_dirty=1.0,
       skirt=0.02, status="ok", bmaj_arcsec=None, bmin_arcsec=None,
       elapsed_s=10.0, imsize=4096, subarray="core"):
    if bmaj_arcsec is None:
        bmaj_arcsec = res_geo_arcsec
    if bmin_arcsec is None:
        bmin_arcsec = res_geo_arcsec
    return dict(subarray=subarray, weighting=weighting, robust=robust,
                taper_mas=taper_mas, imsize=imsize, cell_arcsec=res_geo_arcsec / 5,
                bmaj_arcsec=bmaj_arcsec, bmin_arcsec=bmin_arcsec, bpa_deg=0.0,
                res_geo_arcsec=res_geo_arcsec, sigma_dirty=sigma_dirty,
                skirt=skirt, status=status, error="", elapsed_s=elapsed_s)


def write_csv(path, rows):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# a deterministic fake config.taper_list_mas: ignores its args, returns 14
# distinct log-spaced-looking values so mid/coarse indices are exact and
# obvious to check.
FAKE_TAPERS = [round(0.3 * 1.6 ** i, 3) for i in range(14)]


def fake_taper_list_mas(res_fine_mas, res_nat_mas):
    return list(FAKE_TAPERS)


class TestBuildPoints(unittest.TestCase):

    def setUp(self):
        self.rows = {
            points_mod.point_key("natural", 2.0, 0.0):
                row("natural", 2.0, 0.0, res_geo_arcsec=0.500),
            points_mod.point_key("briggs", -2.0, 0.0):
                row("briggs", -2.0, 0.0, res_geo_arcsec=0.020),
        }

    def test_ten_points_no_seed_duplication(self):
        pts = points_mod.build_points(self.rows, "core", fake_taper_list_mas)
        self.assertEqual(len(pts), 10)
        keys = {tuple(p) for p in pts}
        self.assertEqual(len(keys), 10)   # all distinct
        # the briggs r=-2, taper=0 seed must never be re-requested
        self.assertNotIn(("briggs", -2.0, 0.0), keys)

    def test_exact_mid_coarse_taper_indices(self):
        pts = points_mod.build_points(self.rows, "core", fake_taper_list_mas)
        mid = FAKE_TAPERS[points_mod.MID_TAPER_INDEX]
        coarse = FAKE_TAPERS[points_mod.COARSE_TAPER_INDEX]
        tapers_seen = {p[2] for p in pts}
        self.assertEqual(tapers_seen, {0.0, round(mid, 3), round(coarse, 3)})
        # natural row only ever gets {mid, coarse}, never taper=0
        nat_tapers = {p[2] for p in pts if p[0] == "natural"}
        self.assertEqual(nat_tapers, {round(mid, 3), round(coarse, 3)})
        # briggs rows: exactly the 3 requested robusts, each at up to 3 tapers
        briggs_robusts = {p[1] for p in pts if p[0] == "briggs"}
        self.assertEqual(briggs_robusts, {-2.0, -0.4, 1.2})

    def test_rounding_matches_canon_rt_precision(self):
        pts = points_mod.build_points(self.rows, "core", fake_taper_list_mas)
        for weighting, robust, taper in pts:
            self.assertEqual(round(robust, 2), robust)
            self.assertEqual(round(taper, 3), taper)

    def test_missing_natural_seed_raises(self):
        rows = {points_mod.point_key("briggs", -2.0, 0.0):
                self.rows[points_mod.point_key("briggs", -2.0, 0.0)]}
        with self.assertRaises(RuntimeError):
            points_mod.build_points(rows, "core", fake_taper_list_mas)

    def test_missing_fine_seed_raises(self):
        rows = {points_mod.point_key("natural", 2.0, 0.0):
                self.rows[points_mod.point_key("natural", 2.0, 0.0)]}
        with self.assertRaises(RuntimeError):
            points_mod.build_points(rows, "core", fake_taper_list_mas)

    def test_seed_not_ok_raises(self):
        rows = dict(self.rows)
        bad_key = points_mod.point_key("briggs", -2.0, 0.0)
        rows[bad_key] = dict(rows[bad_key], status="failed")
        with self.assertRaises(RuntimeError):
            points_mod.build_points(rows, "core", fake_taper_list_mas)

    def test_generate_points_reads_csv_from_tmp_dir(self):
        tmp = tempfile.mkdtemp()
        try:
            write_csv(os.path.join(tmp, "core.csv"), list(self.rows.values()))
            pts = points_mod.generate_points("core", tmp, fake_taper_list_mas)
            self.assertEqual(len(pts), 10)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_generate_points_missing_csv_raises(self):
        tmp = tempfile.mkdtemp()
        try:
            with self.assertRaises(RuntimeError):
                points_mod.generate_points("core", tmp, fake_taper_list_mas)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_hyphenated_subarray_csv_name(self):
        tmp = tempfile.mkdtemp()
        try:
            write_csv(os.path.join(tmp, "core_spiral.csv"),
                     list(self.rows.values()))
            pts = points_mod.generate_points("core+spiral", tmp,
                                             fake_taper_list_mas)
            self.assertEqual(len(pts), 10)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestComparePass(unittest.TestCase):
    """Two nchan variants that agree well within the adopt-27 tolerances."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ref = os.path.join(self.tmp, "ref")
        self.other = os.path.join(self.tmp, "other")
        rows_ref = [
            row("natural", 2.0, 0.0, res_geo_arcsec=0.500, sigma_dirty=1.0,
               skirt=0.10),
            row("briggs", -2.0, 0.0, res_geo_arcsec=0.020, sigma_dirty=3.0,
               skirt=0.03),
            row("briggs", -0.40, 1.234, res_geo_arcsec=0.100, sigma_dirty=1.5,
               skirt=0.05),
        ]
        # other: everything within the pass tolerances (tiny perturbations)
        rows_other = [
            row("natural", 2.0, 0.0, res_geo_arcsec=0.5010, sigma_dirty=1.001,
               skirt=0.101),
            row("briggs", -2.0, 0.0, res_geo_arcsec=0.02005, sigma_dirty=3.003,
               skirt=0.0305),
            row("briggs", -0.40, 1.234, res_geo_arcsec=0.1004, sigma_dirty=1.502,
               skirt=0.0505),
        ]
        write_csv(os.path.join(self.ref, "core.csv"), rows_ref)
        write_csv(os.path.join(self.other, "core.csv"), rows_other)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_matched_and_pass(self):
        matched, problems = compare_mod.compare_subarray(
            self.ref, self.other, "core")
        self.assertEqual(len(matched), 3)
        self.assertEqual(problems, [])
        failures, p95, mx = compare_mod.evaluate(matched)
        self.assertEqual(failures, [])

    def test_main_exit_zero_and_report_written(self):
        out = os.path.join(self.tmp, "report.md")
        rc = compare_mod.main(["--ref", self.ref, "--other", self.other,
                              "--subarrays", "core", "--out", out])
        self.assertEqual(rc, 0)
        with open(out) as f:
            text = f.read()
        self.assertIn("Result: PASS", text)


class TestCompareEtaFail(unittest.TestCase):
    """A point whose eta diverges beyond the per-point d_eta tolerance."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ref = os.path.join(self.tmp, "ref")
        self.other = os.path.join(self.tmp, "other")
        rows_ref = [
            row("natural", 2.0, 0.0, res_geo_arcsec=0.500, sigma_dirty=1.0),
            row("briggs", -2.0, 0.0, res_geo_arcsec=0.020, sigma_dirty=3.0),
            row("briggs", 1.20, 5.0, res_geo_arcsec=0.200, sigma_dirty=2.0),
        ]
        rows_other = [
            row("natural", 2.0, 0.0, res_geo_arcsec=0.500, sigma_dirty=1.0),
            row("briggs", -2.0, 0.0, res_geo_arcsec=0.020, sigma_dirty=3.0),
            # eta_ref = 2.0, eta_other = 2.5 -> d_eta = 0.25, way over 0.005
            row("briggs", 1.20, 5.0, res_geo_arcsec=0.200, sigma_dirty=2.5),
        ]
        write_csv(os.path.join(self.ref, "core.csv"), rows_ref)
        write_csv(os.path.join(self.other, "core.csv"), rows_other)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fails_on_eta_divergence(self):
        matched, _ = compare_mod.compare_subarray(self.ref, self.other, "core")
        failures, p95, mx = compare_mod.evaluate(matched)
        self.assertTrue(any("1.20_5.000" in f or "briggs_1.20_5.000" in f
                            for f in failures),
                       failures)

    def test_main_exit_three(self):
        rc = compare_mod.main(["--ref", self.ref, "--other", self.other,
                              "--subarrays", "core"])
        self.assertEqual(rc, 3)


class TestCompareEndpointFail(unittest.TestCase):
    """A seed point (endpoint) whose skirt shifts beyond its own, tighter
    tolerance, even though eta itself would pass the ordinary point rule."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ref = os.path.join(self.tmp, "ref")
        self.other = os.path.join(self.tmp, "other")
        rows_ref = [
            row("natural", 2.0, 0.0, res_geo_arcsec=0.500, sigma_dirty=1.0,
               skirt=0.10),
            row("briggs", -2.0, 0.0, res_geo_arcsec=0.020, sigma_dirty=3.0,
               skirt=0.03),
        ]
        rows_other = [
            row("natural", 2.0, 0.0, res_geo_arcsec=0.500, sigma_dirty=1.0,
               skirt=0.10),
            # skirt jumps by 0.05 (> 0.02 endpoint limit); eta unchanged
            row("briggs", -2.0, 0.0, res_geo_arcsec=0.020, sigma_dirty=3.0,
               skirt=0.08),
        ]
        write_csv(os.path.join(self.ref, "core.csv"), rows_ref)
        write_csv(os.path.join(self.other, "core.csv"), rows_other)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fails_on_endpoint_skirt(self):
        matched, _ = compare_mod.compare_subarray(self.ref, self.other, "core")
        failures, p95, mx = compare_mod.evaluate(matched)
        self.assertTrue(any("endpoint" in f and "d_skirt" in f for f in failures),
                       failures)

    def test_main_exit_three(self):
        rc = compare_mod.main(["--ref", self.ref, "--other", self.other,
                              "--subarrays", "core"])
        self.assertEqual(rc, 3)


class TestCompareTimingOnly(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ref = os.path.join(self.tmp, "ref")
        write_csv(os.path.join(self.ref, "core.csv"), [
            row("natural", 2.0, 0.0, elapsed_s=10.0),
            row("briggs", -2.0, 0.0, elapsed_s=20.0),
            row("briggs", 1.20, 5.0, elapsed_s=30.0),
        ])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_timing_only_mode_exits_zero_no_criteria(self):
        out = os.path.join(self.tmp, "timing.md")
        rc = compare_mod.main(["--ref", self.ref, "--subarrays", "core",
                              "--out", out])
        self.assertEqual(rc, 0)
        with open(out) as f:
            text = f.read()
        self.assertIn("cost benchmark", text.lower())
        self.assertNotIn("Result:", text)

    def test_timing_stats_median_and_max(self):
        rows = compare_mod.read_all_rows(self.ref, "core")
        stats = compare_mod.timing_stats(rows)
        self.assertEqual(stats["n"], 3)
        self.assertEqual(stats["median"], 20.0)
        self.assertEqual(stats["max"], 30.0)


class TestCompareUnmatched(unittest.TestCase):
    """Points present in one dir only, or recorded non-ok, are reported as
    problems and never enter the matched/criteria set."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ref = os.path.join(self.tmp, "ref")
        self.other = os.path.join(self.tmp, "other")
        write_csv(os.path.join(self.ref, "core.csv"), [
            row("natural", 2.0, 0.0, res_geo_arcsec=0.5, sigma_dirty=1.0),
            row("briggs", -2.0, 0.0, res_geo_arcsec=0.02, sigma_dirty=3.0),
            row("briggs", 0.40, 2.0, res_geo_arcsec=0.15, sigma_dirty=1.8,
               status="failed"),
            row("briggs", 1.20, 9.0, res_geo_arcsec=0.30, sigma_dirty=1.2),
        ])
        write_csv(os.path.join(self.other, "core.csv"), [
            row("natural", 2.0, 0.0, res_geo_arcsec=0.5, sigma_dirty=1.0),
            row("briggs", -2.0, 0.0, res_geo_arcsec=0.02, sigma_dirty=3.0),
            # briggs 0.40/2.0 entirely absent from "other" -> unmatched
            # briggs 1.20/9.0 present and ok in both -> matched
            row("briggs", 1.20, 9.0, res_geo_arcsec=0.30, sigma_dirty=1.2),
        ])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_failed_and_missing_points_reported_not_matched(self):
        matched, problems = compare_mod.compare_subarray(
            self.ref, self.other, "core")
        matched_keys = {(m["weighting"], m["robust"], m["taper_mas"])
                       for m in matched}
        self.assertIn(("briggs", 1.20, 9.0), matched_keys)
        self.assertNotIn(("briggs", 0.40, 2.0), matched_keys)
        problem_keys = {p[0] for p in problems}
        self.assertIn(("briggs", 0.40, 2.0), problem_keys)

    def test_report_lists_unmatched_section(self):
        out = os.path.join(self.tmp, "report.md")
        compare_mod.main(["--ref", self.ref, "--other", self.other,
                         "--subarrays", "core", "--out", out])
        with open(out) as f:
            text = f.read()
        self.assertIn("unmatched / non-ok points", text)


class TestUsageErrors(unittest.TestCase):

    def test_missing_ref_dir_exit_two(self):
        rc = compare_mod.main(["--ref", "/no/such/dir/at/all"])
        self.assertEqual(rc, 2)

    def test_missing_other_dir_exit_two(self):
        tmp = tempfile.mkdtemp()
        try:
            rc = compare_mod.main(["--ref", tmp, "--other", "/no/such/dir"])
            self.assertEqual(rc, 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

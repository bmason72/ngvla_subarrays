"""
CASA-free tests for the spiral+5 / spiral+10 subarrays
(docs/plans/spiral-plus-subarrays-spec.md).

Covers: the selection rule in curvegen/make_spiral_plus.py, the config.py /
build_configs.py composition mechanism, and the metadata rows added to the
Rev F subarrays_revf_*.csv files.  No CASA/tclean involved -- numpy only.
"""

import csv
import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CURVEGEN = os.path.join(REPO_ROOT, "curvegen")
SELECTION_CSV = os.path.join(REPO_ROOT, "sa_select", "data",
                             "spiral_plus_selection.csv")

sys.path.insert(0, CURVEGEN)


# The full pre-existing revF composite-subarray dict, copied verbatim from
# curvegen/config.py before spiral+5/spiral+10 were added, so we can assert
# byte-identical membership for every subarray that already existed.
_PRE_EXISTING_REVF_SUBARRAYS = {
    "core-inner": ["core-inner"],
    "core": ["core"],
    "spiral": ["spiral"],
    "mid": ["mid"],
    "core+spiral": ["core", "spiral"],
    "core+mid": ["core", "mid"],
    "spiral+mid": ["spiral", "mid"],
    "main": ["core", "spiral", "mid"],
    "core-outer": ["core-outer"],
    "long": ["long"],
    "mid+long": ["mid", "long"],
    "spiral+mid+long": ["spiral", "mid", "long"],
    "main+long": ["core", "spiral", "mid", "long"],
    "spiral+core-outer": ["spiral", "core-outer"],
    "mid+spiral+core-outer": ["mid", "spiral", "core-outer"],
    "long+mid+spiral+core-outer": ["long", "mid", "spiral", "core-outer"],
}


class TestSpiralPlusSelectionRule(unittest.TestCase):
    """The tangent-plane nearest-core-antenna rule in make_spiral_plus.py."""

    @classmethod
    def setUpClass(cls):
        import make_spiral_plus as msp
        cls.msp = msp
        cls.rows, cls.geometry = msp.compute_selection()

    def test_five_and_ten_rows(self):
        plus5 = [r for r in self.rows if r["set"] == "+5"]
        plus10 = [r for r in self.rows if r["set"] == "+10"]
        self.assertEqual(len(plus5), 5)
        self.assertEqual(len(plus10), 5)
        self.assertEqual(len(self.rows), 10)

    def test_no_antenna_chosen_twice(self):
        chosen = [r["chosen_antenna"] for r in self.rows]
        self.assertEqual(len(chosen), len(set(chosen)),
                         "an antenna was selected more than once: %r" % chosen)

    def test_every_choice_is_a_core_station(self):
        core_names = set(self.geometry["core_names"])
        for r in self.rows:
            self.assertIn(r["chosen_antenna"], core_names)

    def test_plus10_contains_plus5(self):
        plus5 = {r["chosen_antenna"] for r in self.rows if r["set"] == "+5"}
        plus10 = {r["chosen_antenna"] for r in self.rows if r["set"] == "+10"}
        all_ten = plus5 | plus10
        self.assertEqual(len(all_ten), 10)
        self.assertTrue(plus5.issubset(all_ten))

    def test_one_pick_per_arm_per_pass(self):
        for tag in ("+5", "+10"):
            arms = [r["arm"] for r in self.rows if r["set"] == tag]
            self.assertEqual(sorted(arms), ["spa", "spb", "spc", "spd", "spe"])

    def test_core_radii_sane_and_spiral_radii_increase_outward(self):
        # sanity check on the ECEF->ENU tangent-plane conversion itself
        core_r = self.geometry["core_r"]
        self.assertLess(core_r.max(), 5000.0,
                        "core antenna radii should be a few km at most")
        spiral_names = self.geometry["spiral_names"]
        spiral_r = self.geometry["spiral_r"]
        for arm in ("spa", "spb", "spc", "spd", "spe"):
            idx = sorted(
                (i for i, nm in enumerate(spiral_names)
                 if nm.startswith(arm)),
                key=lambda i: int(spiral_names[i][len(arm):]))
            radii = [spiral_r[i] for i in idx]
            self.assertEqual(radii, sorted(radii),
                             "arm %s radii should increase outward along "
                             "the station numbering" % arm)


class TestSpiralPlusSelectionCsv(unittest.TestCase):
    """The cached selection table sa_select/data/spiral_plus_selection.csv."""

    def test_csv_exists_with_ten_rows(self):
        self.assertTrue(os.path.isfile(SELECTION_CSV), SELECTION_CSV)
        with open(SELECTION_CSV, newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 10)
        for field in ("set", "arm", "tip_station", "chosen_antenna",
                     "distance_m", "r_antenna_m", "r_tip_m", "az_diff_deg"):
            self.assertIn(field, rows[0])
        self.assertEqual({r["set"] for r in rows}, {"+5", "+10"})


class TestSpiralPlusConfig(unittest.TestCase):
    """config.py / build_configs.py membership for the two new subarrays."""

    def test_config_exposes_spiral_plus_with_right_antenna_counts(self):
        import build_configs as bc
        import config
        self.assertIn("spiral+5", config.SUBARRAYS)
        self.assertIn("spiral+10", config.SUBARRAYS)

        spiral_n = len(bc.read_antenna_lines("spiral"))
        n5 = len(bc.spiral_plus_core_lines("core-spiral+5"))
        n10 = len(bc.spiral_plus_core_lines("core-spiral+10"))
        self.assertEqual(spiral_n, 54)
        self.assertEqual(n5, 5)
        self.assertEqual(n10, 10)
        self.assertEqual(spiral_n + n5, 59)
        self.assertEqual(spiral_n + n10, 64)

    def test_plus10_lines_are_superset_of_plus5_lines(self):
        import build_configs as bc
        names5 = {ln.split()[-1].strip()
                 for ln in bc.spiral_plus_core_lines("core-spiral+5")}
        names10 = {ln.split()[-1].strip()
                  for ln in bc.spiral_plus_core_lines("core-spiral+10")}
        self.assertTrue(names5.issubset(names10))
        self.assertEqual(len(names5), 5)
        self.assertEqual(len(names10), 10)

    def test_existing_revf_subarrays_are_byte_identical(self):
        import config
        for name, components in _PRE_EXISTING_REVF_SUBARRAYS.items():
            self.assertEqual(config.SUBARRAYS[name], components,
                             "subarray %r membership changed" % name)
        # additive only: the two new subarrays plus the pre-existing ones,
        # nothing dropped
        self.assertEqual(
            set(config.SUBARRAYS),
            set(_PRE_EXISTING_REVF_SUBARRAYS) | {"spiral+5", "spiral+10"})

    def test_spiral_plus_absent_from_run_and_mfs_sets(self):
        import config
        self.assertNotIn("spiral+5", config.RUN_SET)
        self.assertNotIn("spiral+10", config.RUN_SET)
        self.assertNotIn("spiral+5", config.MFS_SUBARRAYS)
        self.assertNotIn("spiral+10", config.MFS_SUBARRAYS)

    def test_mfs_subarrays_unaffected_in_mfs_mode(self):
        # config freezes (rev, sim_mode, MFS) at import; validate the MFS
        # branch in a subprocess so this test doesn't disturb the module
        # already imported (non-MFS) above.
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "import config\n"
            "assert 'spiral+5' not in config.SUBARRAYS, config.SUBARRAYS\n"
            "assert 'spiral+10' not in config.SUBARRAYS, config.SUBARRAYS\n"
            "assert sorted(config.SUBARRAYS) == sorted(config.MFS_SUBARRAYS)\n"
        ) % CURVEGEN
        env = dict(os.environ, NGVLA_REV="revF", NGVLA_SIM_MODE="track",
                   NGVLA_BAND="band4")
        result = subprocess.run([sys.executable, "-c", code], cwd=CURVEGEN,
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class TestSpiralPlusMetadataRows(unittest.TestCase):
    """The metadata rows added to the Rev F subarrays_revf_*.csv files.

    Only the mono snapshot CSV carries spiral+5/spiral+10 rows (bmason D12,
    21 Sep 2026): the Band-4 MFS combos are out of scope, and MFS mode
    filters config.SUBARRAYS/IMSIZE to config.MFS_SUBARRAYS, which does not
    include these two names -- a metadata CSV must never offer a subarray
    the config cannot build (docs/plans/spiral-plus-campaign-plan.md, task
    S0).
    """

    CSVS = ["subarrays_revf_snapshot.csv"]
    MFS_CSVS = ["subarrays_revf_mfs_band4_snapshot.csv",
                "subarrays_revf_mfs_band4_track.csv"]

    def test_rows_present_and_parse(self):
        from sa_select.curves import load_subarrays, DATA_DIR
        for fname in self.CSVS:
            path = os.path.join(DATA_DIR, fname)
            info = load_subarrays(path)
            for name, expected_n in (("spiral+5", 59), ("spiral+10", 64)):
                self.assertIn(name, info, "%s missing from %s" % (name, fname))
                self.assertEqual(info[name].n_ant, expected_n,
                                 "%s n_ant in %s" % (name, fname))
                self.assertIsNone(info[name].beam_cap_arcsec,
                                 "%s beam cap should be blank (unmeasured) "
                                 "in %s" % (name, fname))

    def test_absent_from_mfs_band4_csvs(self):
        # D12 (21 Sep 2026): revF/track only, not MFS. spiral+5/spiral+10
        # are not in config.MFS_SUBARRAYS, so offering them here would be a
        # KeyError waiting to happen in a future Band-4 run.
        from sa_select.curves import load_subarrays, DATA_DIR
        for fname in self.MFS_CSVS:
            info = load_subarrays(os.path.join(DATA_DIR, fname))
            self.assertNotIn("spiral+5", info, fname)
            self.assertNotIn("spiral+10", info, fname)

    def test_not_added_to_default_authoritative_csv(self):
        # subarrays.csv (revF/track, the release/offered default) is
        # hand-maintained and out of scope for this spec.
        from sa_select.curves import load_subarrays, DATA_DIR
        info = load_subarrays(os.path.join(DATA_DIR, "subarrays.csv"))
        self.assertNotIn("spiral+5", info)
        self.assertNotIn("spiral+10", info)


if __name__ == "__main__":
    unittest.main()

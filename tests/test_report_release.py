"""
Tests for the release build of the combined curves report (RELEASE_PLAN.md
T3; WRAPUP.md items 2+3): make_report.combined_combo_plan is the pure
registry-rows -> kept-combos + flags mapping behind `--combined --release`.
Release mode keeps only RELEASE_COMBOS and stamps imaging_omitted=True on the
RELEASE_PTSRC_ONLY campaigns' dropdown metadata; non-release (internal)
builds are untouched.  The page JS that consumes the flag is not tested here.

make_report.py has no CASA dependency (config.py + sa_select.envelope only
need numpy), so this imports it directly, same as tests/test_envelope.py.
Run from the repository root:

    python3 -m unittest tests.test_report_release
"""

import csv
import os
import subprocess
import sys
import unittest

CURVEGEN = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "curvegen")
sys.path.insert(0, CURVEGEN)

import make_report as mr  # noqa: E402


def reg_row(rev, sim_mode):
    """A config_registry.csv-shaped row (only the columns the plan reads,
    plus the samples_csv routing column build_combined reads afterwards)."""
    return {"rev": rev, "sim_mode": sim_mode,
            "subarrays_csv": "subarrays_%s_%s.csv" % (rev, sim_mode),
            "samples_csv": "%s_%s_curves.csv" % (rev, sim_mode)}


# every registered combo as of this writing, in registry-like order
ROWS = [reg_row("revF", "track"), reg_row("revF", "snapshot"),
        reg_row("revD", "track"), reg_row("revD", "snapshot"),
        reg_row("revC", "track")]


class TestReleaseConstants(unittest.TestCase):

    def test_ptsrc_only_is_a_subset_of_release_combos(self):
        self.assertTrue(mr.RELEASE_PTSRC_ONLY <= set(mr.RELEASE_COMBOS))

    def test_reference_campaign_is_released_with_imaging(self):
        self.assertIn("revF_track", mr.RELEASE_COMBOS)
        self.assertNotIn("revF_track", mr.RELEASE_PTSRC_ONLY)


class TestCombinedComboPlan(unittest.TestCase):

    def test_combo_header_includes_refinement_and_ngect_context(self):
        sub = mr.combo_entry("revD", "track")["sub_html"]
        self.assertIn("adaptive refinement where needed", sub)
        self.assertIn('href="https://ngect.nrao.edu"', sub)

    def test_non_release_keeps_every_row_in_order_unflagged(self):
        plan = mr.combined_combo_plan(ROWS)
        self.assertEqual([r["rev"] + "_" + r["sim_mode"] for r, _ in plan],
                         [r["rev"] + "_" + r["sim_mode"] for r in ROWS])
        for row, entry in plan:
            self.assertIs(row, ROWS[[r["rev"] + "_" + r["sim_mode"]
                                     for r in ROWS].index(entry["key"])])
            self.assertNotIn("imaging_omitted", entry)

    def test_release_keeps_only_release_combos(self):
        plan = mr.combined_combo_plan(ROWS, release=True)
        self.assertEqual([entry["key"] for _, entry in plan],
                         ["revF_track", "revD_track", "revC_track"])

    def test_release_flags_exactly_the_ptsrc_only_combos(self):
        plan = mr.combined_combo_plan(ROWS, release=True)
        flags = {entry["key"]: entry.get("imaging_omitted")
                 for _, entry in plan}
        self.assertEqual(flags, {"revF_track": None,
                                 "revD_track": True,
                                 "revC_track": True})
        # the flag is a real boolean True (JSON true), not just truthy
        for _, entry in plan:
            if "imaging_omitted" in entry:
                self.assertIs(entry["imaging_omitted"], True)

    def test_release_entry_metadata_is_otherwise_the_normal_entry(self):
        (_, released), = [p for p in
                          mr.combined_combo_plan(ROWS, release=True)
                          if p[1]["key"] == "revD_track"]
        normal = mr.combo_entry("revD", "track")
        self.assertNotIn("imaging_omitted", normal)   # flag never leaks back
        stripped = dict(released)
        stripped.pop("imaging_omitted")
        self.assertEqual(stripped, normal)

    def test_release_plan_over_the_real_registry(self):
        reg = os.path.join(mr.DATA_DIR, "config_registry.csv")
        with open(reg, newline="") as f:
            rows = list(csv.DictReader(f))
        plan = mr.combined_combo_plan(rows, release=True)
        keys = [entry["key"] for _, entry in plan]
        self.assertTrue(set(keys) <= set(mr.RELEASE_COMBOS))
        # today's registry registers at least the two combos with data
        self.assertIn("revF_track", keys)
        self.assertIn("revD_track", keys)


class TestReleaseCliGuard(unittest.TestCase):

    def test_release_without_combined_is_an_error(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(CURVEGEN, "make_report.py"),
             "--release", "unused.html"],
            capture_output=True, text=True, cwd=CURVEGEN)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--release is only valid together with --combined",
                      proc.stderr)


if __name__ == "__main__":
    unittest.main()

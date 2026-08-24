"""
Tests for the sa_select CLI (rev routing, release-scope warning, batch mode)
and the selector's n_ant_actual wiring (RELEASE_PLAN.md T4).

Run with the CASA python (stdlib unittest only, no pytest) from the repo root.
"""

import contextlib
import csv
import io
import json
import os
import tempfile
import unittest

from sa_select import cli
from sa_select import selector as sel_mod
from sa_select.schema import ObservingRequest
from sa_select.selector import select_subarrays

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(argv):
    """(exit_code, stdout, stderr) of one cli.main() call."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestCliRevRouting(unittest.TestCase):

    def test_data_info_requires_no_observing_request(self):
        code, out, err = run_cli(["--data-info"])
        self.assertEqual(code, 0)
        self.assertFalse(err)
        info = json.loads(out)
        self.assertEqual(info["schema"], "ngvla.memo96.sensitivity-tables")
        self.assertTrue(info["campaigns"])

    def test_default_rev_query_runs(self):
        code, out, _ = run_cli(["--resolution", "0.01", "--frequency", "30",
                                "--point-source"])
        self.assertEqual(code, 0)
        self.assertIn("revF/track", out)

    def test_unregistered_rev_fails_cleanly(self):
        code, _, err = run_cli(["--rev", "revZ", "--resolution", "0.01",
                                "--frequency", "30"])
        self.assertEqual(code, 2)
        self.assertIn("cannot load curves", err)

    def test_revc_fails_cleanly_until_campaign_runs(self):
        # revC/track is registered but its curve CSV is produced by the (not
        # yet run) campaign; the CLI must fail with a readable message, not a
        # traceback.  DELETE this test's expectation (flip to success) once
        # revc_track_curves.csv lands.
        csv_path = os.path.join(REPO_ROOT, "sa_select", "data",
                                "revc_track_curves.csv")
        if os.path.exists(csv_path):
            self.skipTest("revC curves have landed; routing is live")
        code, _, err = run_cli(["--rev", "revC", "--resolution", "0.01",
                                "--frequency", "30"])
        self.assertEqual(code, 2)
        self.assertIn("cannot load curves", err)


class TestReleaseScopeWarning(unittest.TestCase):

    def test_revd_imaging_query_warns(self):
        code, _, err = run_cli(["--rev", "revD", "--resolution", "0.05",
                                "--frequency", "30", "--imaging"])
        self.assertIn("outside the released scope", err)
        self.assertIn(code, (0, 2))     # warning must not change feasibility

    def test_revd_point_source_query_does_not_warn(self):
        _, _, err = run_cli(["--rev", "revD", "--resolution", "0.05",
                             "--frequency", "30", "--point-source"])
        self.assertNotIn("outside the released scope", err)

    def test_revf_imaging_query_does_not_warn(self):
        _, _, err = run_cli(["--resolution", "0.05", "--frequency", "30",
                             "--imaging"])
        self.assertNotIn("outside the released scope", err)


class TestBatchMode(unittest.TestCase):
    """--batch: the EOP-case-list entry point."""

    def _write_cases(self, rows, fieldnames):
        f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                        newline="")
        self.addCleanup(os.unlink, f.name)
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
        f.close()
        return f.name

    def test_two_cases_top_two(self):
        path = self._write_cases(
            [dict(case="PF1", resolution="0.01", frequency="30",
                  imaging="point-source"),
             dict(case="PF2", resolution="0.1", frequency="30",
                  imaging="imaging")],
            ["case", "resolution", "frequency", "imaging"])
        code, out, _ = run_cli(["--batch", path, "--top", "2"])
        self.assertEqual(code, 0)
        rows = list(csv.DictReader(io.StringIO(out)))
        cases = {r["case"] for r in rows}
        self.assertEqual(cases, {"PF1", "PF2"})
        for r in rows:
            self.assertIn(int(r["rank"]), (1, 2))
            self.assertEqual(r["feasible"], "True")

    def test_cell_fallback_to_flags(self):
        # frequency comes from the command line; the row only sets resolution
        path = self._write_cases([dict(case="a", resolution="0.01")],
                                 ["case", "resolution"])
        code, out, _ = run_cli(["--batch", path, "--frequency", "30",
                                "--point-source"])
        self.assertEqual(code, 0)
        rows = list(csv.DictReader(io.StringIO(out)))
        self.assertTrue(rows)

    def test_infeasible_case_reported_and_exit_2(self):
        path = self._write_cases(
            [dict(case="bad", resolution="1e-9", frequency="30")],
            ["case", "resolution", "frequency"])
        code, out, _ = run_cli(["--batch", path])
        self.assertEqual(code, 2)
        rows = list(csv.DictReader(io.StringIO(out)))
        self.assertEqual(rows[0]["case"], "bad")
        self.assertEqual(rows[0]["feasible"], "False")
        self.assertTrue(rows[0]["reasons"])


class TestNAntActualWiring(unittest.TestCase):
    """selector must pass the metadata CSV's n_ant to integration_time so a
    revision whose antenna counts differ from the backing table (Rev C) gets
    the N(N-1) rescale; for Rev F/D the counts match and the factor is 1."""

    def test_selector_passes_n_ant_actual(self):
        from sa_select import sensitivity as sens
        seen = {}
        orig = sens.integration_time

        def spy(calc_name, freq_ghz, eta, goal, delta_v=None,
                n_ant_actual=None):
            seen[calc_name] = n_ant_actual
            return 1.0

        sens.integration_time = spy
        try:
            request = ObservingRequest(resolution=0.01, frequency=30,
                                       sensitivity=1e-6, imaging=False)
            result = select_subarrays(request)
        finally:
            sens.integration_time = orig
        self.assertTrue(result.feasible)
        by_name = {c.subarray.calc_name or c.subarray.name: c.subarray.n_ant
                   for c in result.feasible}
        for calc_name, n_seen in seen.items():
            self.assertIsNotNone(n_seen)
            if calc_name in by_name:
                self.assertEqual(n_seen, by_name[calc_name])


if __name__ == "__main__":
    unittest.main()

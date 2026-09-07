"""Focused tests for HTML report generation provenance."""

import datetime
import os
import subprocess
import sys
import unittest
from unittest import mock


CURVEGEN = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "curvegen")
sys.path.insert(0, CURVEGEN)

import make_report as mr  # noqa: E402


class TestReportProvenance(unittest.TestCase):

    def test_clean_full_commit_and_local_iso_time(self):
        instant = datetime.datetime(
            2026, 9, 4, 15, 6, 7,
            tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))
        sha = "0123456789abcdef0123456789abcdef01234567"
        with mock.patch.object(
                mr.subprocess, "check_output", side_effect=[sha + "\n", ""]):
            signature, generated_at = mr.report_provenance(instant)
        self.assertEqual(signature, sha)
        self.assertEqual(generated_at, "2026-09-04T15:06:07-05:00")

    def test_tracked_changes_append_dirty_and_untracked_are_ignored(self):
        sha = "fedcba9876543210fedcba9876543210fedcba98"
        with mock.patch.object(
                mr.subprocess, "check_output",
                side_effect=[sha + "\n", " M curvegen/make_report.py\n"]) as run:
            signature, _ = mr.report_provenance()
        self.assertEqual(signature, sha + "-dirty")
        self.assertIn("--untracked-files=no", run.call_args_list[1].args[0])

    def test_git_failure_is_unknown(self):
        with mock.patch.object(
                mr.subprocess, "check_output",
                side_effect=subprocess.CalledProcessError(128, "git")):
            signature, generated_at = mr.report_provenance()
        self.assertEqual(signature, "unknown")
        self.assertRegex(
            generated_at,
            r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")

    def test_footer_is_html_safe_and_at_page_bottom(self):
        source = ('<div class="wrap">content\n'
                  '<footer class="report-provenance">'
                  '__REPORT_PROVENANCE__</footer>\n</div>')
        rendered = mr.inject_report_provenance(
            source, signature='<bad&"sha>',
            generated_at="2026-09-04T15:06:07-05:00<script>")
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn('&lt;bad&amp;&quot;sha&gt;', rendered)
        self.assertIn(" &middot; Git commit ", rendered)
        self.assertLess(rendered.index("content"), rendered.index("Generated "))
        self.assertNotIn("__REPORT_PROVENANCE__", rendered)

    def test_shared_template_footer_is_after_report_content(self):
        with open(mr.TEMPLATE) as handle:
            template = handle.read()
        self.assertEqual(template.count("__REPORT_PROVENANCE__"), 1)
        self.assertLess(template.index('<div class="tiles" id="tiles">'),
                        template.index('<footer class="report-provenance">'))


if __name__ == "__main__":
    unittest.main()

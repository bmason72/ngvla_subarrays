"""
Tests for the release page's standalone PSF embedding (RELEASE_PLAN.md's
"standalone release page" follow-up): make_report.embed_psf_payloads reads
the lazy-load psf/<comboKey>/<stem>.js JSONP files and inlines them as
gzip+base64 <script type="text/plain" data-psf-id="..."> blocks, so the
release page can travel as one HTML file with no sibling psf/ directory.
The browser-side decode (report_template.html's loadPsfData) is not tested
here.

make_report.py has no CASA dependency (config.py + sa_select.envelope only
need numpy), so this imports it directly, same as tests/test_envelope.py and
tests/test_report_release.py.  Run from the repository root:

    python3 -m unittest tests.test_report_standalone
"""

import base64
import gzip
import json
import os
import sys
import tempfile
import unittest

CURVEGEN = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "curvegen")
sys.path.insert(0, CURVEGEN)

import make_report as mr  # noqa: E402


def write_psf_js(psf_base, combo_key, stem, payload_id, obj):
    """Write one <psf_base>/<combo_key>/<stem>.js JSONP registration file."""
    combo_dir = os.path.join(psf_base, combo_key)
    os.makedirs(combo_dir, exist_ok=True)
    path = os.path.join(combo_dir, stem + ".js")
    with open(path, "w") as f:
        f.write('window.PSF_REGISTER("%s", %s);' % (payload_id, json.dumps(obj)))
    return path


def decode_block(block_html):
    """(id, decoded-json-obj) from one '<script type="text/plain"
    data-psf-id="...">BASE64</script>' block string."""
    id_start = block_html.index('data-psf-id="') + len('data-psf-id="')
    id_end = block_html.index('"', id_start)
    payload_id = block_html[id_start:id_end]
    body_start = block_html.index(">", id_end) + 1
    b64 = block_html[body_start:block_html.index("</script>", body_start)]
    obj = json.loads(gzip.decompress(base64.b64decode(b64)).decode("utf-8"))
    return payload_id, obj


class TestEmbedPsfPayloads(unittest.TestCase):

    def test_round_trip_one_combo(self):
        with tempfile.TemporaryDirectory() as psf_base:
            write_psf_js(psf_base, "combo_a", "core", "combo_a/core",
                        {"k": [1.5, -2]})
            html = mr.embed_psf_payloads("<p>x</p>\n<script>1</script>",
                                         ["combo_a"], psf_base=psf_base)
            blocks = [seg for seg in html.split("\n")
                     if "data-psf-id=" in seg]
            self.assertEqual(len(blocks), 1)
            payload_id, obj = decode_block(blocks[0])
            self.assertEqual(payload_id, "combo_a/core")
            self.assertEqual(obj, {"k": [1.5, -2]})
            # the block must land before the page's <script> tag
            self.assertLess(html.index('data-psf-id='), html.index("<script>"))

    def test_stem_with_plus_and_minus_preserves_id_verbatim(self):
        with tempfile.TemporaryDirectory() as psf_base:
            write_psf_js(psf_base, "combo_a", "spiral_mid",
                        "combo_a/spiral+mid", {"a": 1})
            html = mr.embed_psf_payloads("<script>1</script>", ["combo_a"],
                                         psf_base=psf_base)
            self.assertIn('data-psf-id="combo_a/spiral+mid"', html)
            block = html[html.index('<script type="text/plain"'):
                        html.index("</script>",
                                   html.index('<script type="text/plain"')) + len("</script>")]
            payload_id, obj = decode_block(block)
            self.assertEqual(payload_id, "combo_a/spiral+mid")
            self.assertEqual(obj, {"a": 1})

    def test_missing_combo_dir_is_skipped_not_an_error(self):
        with tempfile.TemporaryDirectory() as psf_base:
            write_psf_js(psf_base, "combo_a", "core", "combo_a/core",
                        {"only": "combo_a"})
            html = mr.embed_psf_payloads("<script>1</script>",
                                         ["combo_a", "absent"],
                                         psf_base=psf_base)
            self.assertEqual(html.count("data-psf-id="), 1)
            self.assertIn('data-psf-id="combo_a/core"', html)

    def test_malformed_wrapper_raises_value_error_naming_the_file(self):
        with tempfile.TemporaryDirectory() as psf_base:
            combo_dir = os.path.join(psf_base, "combo_a")
            os.makedirs(combo_dir)
            bad_path = os.path.join(combo_dir, "core.js")
            with open(bad_path, "w") as f:
                f.write("not a PSF_REGISTER call at all")
            with self.assertRaises(ValueError) as ctx:
                mr.embed_psf_payloads("<script>1</script>", ["combo_a"],
                                      psf_base=psf_base)
            self.assertIn(bad_path, str(ctx.exception))

    def test_html_without_script_tag_raises_value_error(self):
        with tempfile.TemporaryDirectory() as psf_base:
            write_psf_js(psf_base, "combo_a", "core", "combo_a/core", {"k": 1})
            with self.assertRaises(ValueError):
                mr.embed_psf_payloads("<p>no script here</p>", ["combo_a"],
                                      psf_base=psf_base)

    def test_nan_constant_raises_value_error_naming_the_file(self):
        # json.dumps (and Python's json.loads) silently accept the
        # NaN/Infinity extension; the browser's strict JSON.parse does not,
        # so embed_psf_payloads must reject it before compressing.
        with tempfile.TemporaryDirectory() as psf_base:
            path = write_psf_js(psf_base, "combo_a", "core", "combo_a/core",
                                {"k": float("nan")})
            with self.assertRaises(ValueError) as ctx:
                mr.embed_psf_payloads("<script>1</script>", ["combo_a"],
                                      psf_base=psf_base)
            self.assertIn(path, str(ctx.exception))

    def test_escaped_id_raises_value_error(self):
        with tempfile.TemporaryDirectory() as psf_base:
            path = write_psf_js(psf_base, "combo_a", "core",
                                r"combo_a\/core", {"a": 1})
            with self.assertRaises(ValueError) as ctx:
                mr.embed_psf_payloads("<script>1</script>", ["combo_a"],
                                      psf_base=psf_base)
            self.assertIn(path, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

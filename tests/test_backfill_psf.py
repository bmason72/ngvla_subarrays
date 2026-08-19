"""
Tests for curvegen/backfill_psf.py (PSF-inspector P2, anchor backfill).

CASA-free in the sense of the sibling tests: no real imaging/simulation is
done -- the anchor-set and needs-backfill logic run on synthetic data, and the
tclean-kwargs parity test monkeypatches the single tclean call.  backfill_psf
imports sweep (which needs casatasks), so the CASA-dependent parts are guarded
with skipTest, exactly like tests/test_measure_profile.py's TestCaptureProfile.

Run under CASA's python:
    /work2/10240/bmason72/stampede3/casaenv/bin/casapy -m unittest \
        tests.test_backfill_psf
"""

import ast
import importlib
import json
import os
import sys
import tempfile
import unittest

CURVEGEN = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "curvegen")
sys.path.insert(0, CURVEGEN)


def _modules():
    """(sweep, backfill_psf) modules, or None if CASA is unavailable here."""
    try:
        return (importlib.import_module("sweep"),
                importlib.import_module("backfill_psf"))
    except ImportError:
        return None


def _profile_line(key, cut=False, cut_rmax_fwhm=10.0):
    rec = {"key": key, "res_geo_arcsec": 0.1,
           "r_arcsec": [0.0, 0.1], "psf": [1.0, 0.2]}
    if cut:
        rec.update(bmaj_arcsec=0.10, bmin_arcsec=0.08, bpa_deg=12.0,
                   cut_r_arcsec=[-0.1, 0.0, 0.1],
                   cut_maj=[0.2, 1.0, 0.2], cut_min=[0.1, 1.0, 0.1])
        if cut_rmax_fwhm is not None:
            rec["cut_rmax_fwhm"] = cut_rmax_fwhm
    return json.dumps(rec)


class TestAnchorSet(unittest.TestCase):
    """Anchor set = imaging(s0=0.10) + point-source curve anchors + natural."""

    def setUp(self):
        mods = _modules()
        if mods is None:
            self.skipTest("curvegen/backfill_psf.py needs CASA here")
        self.backfill = mods[1]

    def test_anchor_keys_from_samples(self):
        bf = self.backfill

        def s(res, eta, skirt, w, r, t):
            return dict(res=res, eta=eta, skirt=skirt,
                        weighting=w, robust=r, taper=t)

        # a tiny 3-row lattice (natural + briggs -2 + briggs -1.6, two tapers
        # each) so build_curve has segments to interpolate along
        samples = [
            s(1.00, 1.00, 0.50, "natural", 2.0, 0.0),
            s(1.20, 1.05, 0.45, "natural", 2.0, 12.0),
            s(0.60, 2.00, 0.06, "briggs", -2.0, 0.0),
            s(0.75, 1.60, 0.09, "briggs", -2.0, 12.0),
            s(0.70, 1.50, 0.15, "briggs", -1.6, 0.0),
            s(0.85, 1.30, 0.18, "briggs", -1.6, 12.0),
        ]
        keys = bf.anchor_keys_from_samples(samples, max_res=None)

        # the natural reference is always an anchor
        self.assertIn("natural_2.00_0.000", keys)
        # every anchor is one of the input measured samples (env_keys are
        # measured Points; nothing invented)
        sample_keys = {bf._canonical_key(x["weighting"], x["robust"],
                                         x["taper"]) for x in samples}
        self.assertTrue(keys <= sample_keys, keys - sample_keys)
        # the low-skirt fine point anchors the imaging (s0=0.10) curve
        self.assertIn("briggs_-2.00_0.000", keys)
        self.assertGreater(len(keys), 1)


class TestNeedsBackfill(unittest.TestCase):
    """cut_bearing_keys: last-line-wins, cut_maj presence, -0.00 normalization."""

    def setUp(self):
        mods = _modules()
        if mods is None:
            self.skipTest("curvegen/backfill_psf.py needs CASA here")
        self.backfill = mods[1]

    def test_cut_bearing_filtering(self):
        bf = self.backfill
        lines = [
            _profile_line("briggs_0.40_1.000", cut=True),   # cut-bearing
            _profile_line("natural_2.00_0.000", cut=False),  # azimuthal only
            _profile_line("briggs_-0.00_2.500", cut=True),   # -0.00 spelling
            _profile_line("briggs_1.20_3.000", cut=True),    # cut, then...
            _profile_line("briggs_1.20_3.000", cut=False),   # ...superseded
            '{"key": "broken"',                              # malformed
        ]
        keys = bf.cut_bearing_keys(lines)
        self.assertIn("briggs_0.40_1.000", keys)
        self.assertNotIn("natural_2.00_0.000", keys)      # no cut_maj
        # negative zero normalized to match the anchor/JS spelling
        self.assertIn("briggs_0.00_2.500", keys)
        self.assertNotIn("briggs_-0.00_2.500", keys)
        # last line for this key is azimuthal-only, so it still needs backfill
        self.assertNotIn("briggs_1.20_3.000", keys)

    def test_negative_zero_written_key_matches_zero_anchor(self):
        """A profile line WRITTEN with the old '-0.00' spelling must be
        recognized as cut-bearing for an anchor whose robust rounds to zero
        (the FIX-3 class of gotcha, covered on both sides)."""
        bf = self.backfill
        keys = bf.cut_bearing_keys([_profile_line("briggs_-0.00_1.000",
                                                  cut=True)])
        anchor = bf._canonical_key("briggs", -0.0, 1.0)
        self.assertEqual(anchor, "briggs_0.00_1.000")
        self.assertIn(anchor, keys)

    def test_missing_cut_rmax_fwhm_is_stale(self):
        """(a) cut_maj present but no cut_rmax_fwhm at all -- a line from
        before this field existed -- must count as stale, not cut-bearing."""
        bf = self.backfill
        line = _profile_line("briggs_0.40_1.000", cut=True,
                             cut_rmax_fwhm=None)
        self.assertNotIn("briggs_0.40_1.000", bf.cut_bearing_keys([line]))

    def test_current_rmax_is_cut_bearing(self):
        """(b) cut_rmax_fwhm at the current measure.CAPTURE_RMAX_FWHM (10.0)
        is cut-bearing."""
        bf = self.backfill
        line = _profile_line("briggs_0.40_1.000", cut=True,
                             cut_rmax_fwhm=10.0)
        self.assertIn("briggs_0.40_1.000", bf.cut_bearing_keys([line]))

    def test_stale_rmax_is_not_cut_bearing(self):
        """(c) cut_rmax_fwhm from the old (3-FWHM) range is stale: the range
        bump makes every such anchor stale so it is re-imaged."""
        bf = self.backfill
        line = _profile_line("briggs_0.40_1.000", cut=True,
                             cut_rmax_fwhm=3.0)
        self.assertNotIn("briggs_0.40_1.000", bf.cut_bearing_keys([line]))

    def test_non_numeric_rmax_is_stale_not_a_crash(self):
        """(d) malformed cut_rmax_fwhm (e.g. a string that isn't a number)
        must be treated as stale, and must never raise."""
        bf = self.backfill
        line = _profile_line("briggs_0.40_1.000", cut=True,
                             cut_rmax_fwhm="x")
        self.assertNotIn("briggs_0.40_1.000", bf.cut_bearing_keys([line]))

    def test_last_line_wins_across_mixed_ranges(self):
        """(e) last-line-wins still holds when the lines mix capture ranges:
        an old-range line superseded by a current-range line is cut-bearing,
        and vice versa."""
        bf = self.backfill
        lines = [
            _profile_line("briggs_0.40_1.000", cut=True, cut_rmax_fwhm=3.0),
            _profile_line("briggs_0.40_1.000", cut=True, cut_rmax_fwhm=10.0),
            _profile_line("briggs_-1.20_2.000", cut=True, cut_rmax_fwhm=10.0),
            _profile_line("briggs_-1.20_2.000", cut=True, cut_rmax_fwhm=3.0),
        ]
        keys = bf.cut_bearing_keys(lines)
        self.assertIn("briggs_0.40_1.000", keys)
        self.assertNotIn("briggs_-1.20_2.000", keys)

    def test_missing_cut_array_is_stale(self):
        """A line with cut_maj but no cut_min (or no cut_r_arcsec) is not
        usable -- the report needs all three arrays to draw anything."""
        bf = self.backfill
        rec = {"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.1,
              "r_arcsec": [0.0, 0.1], "psf": [1.0, 0.2],
              "cut_r_arcsec": [-0.1, 0.0, 0.1], "cut_maj": [0.2, 1.0, 0.2],
              "cut_rmax_fwhm": 10.0}   # no cut_min
        self.assertNotIn("briggs_0.40_1.000",
                         bf.cut_bearing_keys([json.dumps(rec)]))

    def test_empty_cut_arrays_are_stale(self):
        """A junk line with cut_maj/cut_min/cut_r_arcsec all present but
        empty must not suppress backfill forever: the report has nothing to
        draw from an empty array either."""
        bf = self.backfill
        rec = {"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.1,
              "r_arcsec": [0.0, 0.1], "psf": [1.0, 0.2],
              "cut_r_arcsec": [], "cut_maj": [], "cut_min": [],
              "cut_rmax_fwhm": 10.0}
        self.assertNotIn("briggs_0.40_1.000",
                         bf.cut_bearing_keys([json.dumps(rec)]))

    def test_mismatched_cut_lengths_are_stale(self):
        """Unequal-length cut arrays can't be zipped index-for-index by the
        report, so they don't count as usable cuts."""
        bf = self.backfill
        rec = {"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.1,
              "r_arcsec": [0.0, 0.1], "psf": [1.0, 0.2],
              "cut_r_arcsec": [-0.1, 0.0, 0.1], "cut_maj": [0.2, 1.0, 0.2],
              "cut_min": [0.1, 1.0], "cut_rmax_fwhm": 10.0}
        self.assertNotIn("briggs_0.40_1.000",
                         bf.cut_bearing_keys([json.dumps(rec)]))

    def test_infinite_rmax_is_stale(self):
        """A poisoned cut_rmax_fwhm of Infinity (which Python's json module
        accepts on read even though it is not valid JSON) must not satisfy
        the range check -- json.dumps can't produce this line (allow_nan
        rejects it), so it is built as a raw string, the way real-world
        corruption on a shared filesystem could arrive."""
        bf = self.backfill
        line = ('{"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.1, '
               '"r_arcsec": [0.0, 0.1], "psf": [1.0, 0.2], '
               '"cut_r_arcsec": [-0.1, 0.0, 0.1], '
               '"cut_maj": [0.2, 1.0, 0.2], "cut_min": [0.1, 1.0, 0.1], '
               '"cut_rmax_fwhm": Infinity}')
        self.assertNotIn("briggs_0.40_1.000", bf.cut_bearing_keys([line]))

    def test_all_null_cut_arrays_are_stale(self):
        """(a) cut_maj/cut_min present, non-empty, equal length -- but every
        sample is null: drawCuts skips a null sample outright, so an
        all-null arm draws nothing and is not usable."""
        bf = self.backfill
        rec = {"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.1,
              "r_arcsec": [0.0, 0.1], "psf": [1.0, 0.2],
              "cut_r_arcsec": [-0.1, 0.0, 0.1],
              "cut_maj": [None, None, None], "cut_min": [None, None, None],
              "cut_rmax_fwhm": 10.0}
        self.assertNotIn("briggs_0.40_1.000",
                         bf.cut_bearing_keys([json.dumps(rec)]))

    def test_string_cut_arrays_are_stale(self):
        """(b) cut_maj/cut_min full of strings (not real numbers) are
        equally unusable -- a JS Number() coercion is not what the report
        does; drawCuts wants a real number or nothing."""
        bf = self.backfill
        rec = {"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.1,
              "r_arcsec": [0.0, 0.1], "psf": [1.0, 0.2],
              "cut_r_arcsec": [-0.1, 0.0, 0.1],
              "cut_maj": ["a", "b", "c"], "cut_min": ["d", "e", "f"],
              "cut_rmax_fwhm": 10.0}
        self.assertNotIn("briggs_0.40_1.000",
                         bf.cut_bearing_keys([json.dumps(rec)]))

    def test_huge_integer_rmax_is_stale_not_a_crash(self):
        """(c) cut_rmax_fwhm as a legal-JSON integer with ~400 digits
        overflows float() -- must be treated as stale, not raise."""
        bf = self.backfill
        huge = "1" + "0" * 400
        line = ('{"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.1, '
               '"r_arcsec": [0.0, 0.1], "psf": [1.0, 0.2], '
               '"cut_r_arcsec": [-0.1, 0.0, 0.1], '
               '"cut_maj": [0.2, 1.0, 0.2], "cut_min": [0.1, 1.0, 0.1], '
               '"cut_rmax_fwhm": %s}' % huge)
        self.assertNotIn("briggs_0.40_1.000", bf.cut_bearing_keys([line]))

    def test_non_numeric_radii_are_stale(self):
        """Radii must be real numbers: a value paired with a junk radius is
        a sample renderPsfChart skips, so real values on string radii still
        draw nothing."""
        bf = self.backfill
        rec = {"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.1,
              "r_arcsec": [0.0, 0.1], "psf": [1.0, 0.2],
              "cut_r_arcsec": ["x", "x", "x"],
              "cut_maj": [0.2, 1.0, 0.2], "cut_min": [0.1, 1.0, 0.1],
              "cut_rmax_fwhm": 10.0}
        self.assertNotIn("briggs_0.40_1.000",
                         bf.cut_bearing_keys([json.dumps(rec)]))

    def test_single_sample_cuts_are_stale(self):
        """One sample per cut passes no drawability test: an SVG line needs
        two points per arm, so a lone r=0 sample draws nothing."""
        bf = self.backfill
        rec = {"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.1,
              "r_arcsec": [0.0, 0.1], "psf": [1.0, 0.2],
              "cut_r_arcsec": [0.0], "cut_maj": [1.0], "cut_min": [1.0],
              "cut_rmax_fwhm": 10.0}
        self.assertNotIn("briggs_0.40_1.000",
                         bf.cut_bearing_keys([json.dumps(rec)]))

    def test_one_drawable_arm_per_cut_suffices(self):
        """A cut whose real samples all sit in ONE arm still draws that arm:
        two real values at r >= 0 are a visible line even when the r <= 0 arm
        is all null."""
        bf = self.backfill
        rec = {"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.1,
              "r_arcsec": [0.0, 0.1], "psf": [1.0, 0.2],
              "cut_r_arcsec": [-0.1, 0.0, 0.1],
              "cut_maj": [None, 1.0, 0.2], "cut_min": [None, 1.0, 0.1],
              "cut_rmax_fwhm": 10.0}
        self.assertIn("briggs_0.40_1.000",
                      bf.cut_bearing_keys([json.dumps(rec)]))

    def test_huge_integer_cut_value_is_stale_not_a_crash(self):
        """A ~400-digit integer inside cut_maj is legal strict JSON but
        overflows math.isfinite -- it must read as not-a-real-number (and
        here leaves the r<=0 arm with one real sample and the r>=0 arm with
        two, so the line stays cut-bearing via the r>=0 arm), never crash
        the planner."""
        bf = self.backfill
        huge = "1" + "0" * 400
        line = ('{"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.1, '
               '"r_arcsec": [0.0, 0.1], "psf": [1.0, 0.2], '
               '"cut_r_arcsec": [-0.1, 0.0, 0.1], '
               '"cut_maj": [%s, 1.0, 0.2], "cut_min": [0.1, 1.0, 0.1], '
               '"cut_rmax_fwhm": 10.0}' % huge)
        self.assertIn("briggs_0.40_1.000", bf.cut_bearing_keys([line]))

    def test_agreement_invalid_last_line_is_invisible_not_a_fallback_gap(self):
        """(d) THE AGREEMENT CASE: a valid cut-bearing line followed by a
        last line with good-looking cuts but a NaN buried in "psf" must NOT
        supersede the valid one -- parse_profile_line rejects the NaN line
        outright, so it is as invisible to the planner as it is to the
        exporter (which would also fall back to the first line).  Report and
        planner therefore agree: the key stays cut-bearing."""
        bf = self.backfill
        good = _profile_line("briggs_0.40_1.000", cut=True, cut_rmax_fwhm=10.0)
        poisoned = ('{"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.1, '
                   '"r_arcsec": [0.0, 0.1], "psf": [1.0, NaN], '
                   '"cut_r_arcsec": [-0.1, 0.0, 0.1], '
                   '"cut_maj": [0.2, 1.0, 0.2], "cut_min": [0.1, 1.0, 0.1], '
                   '"cut_rmax_fwhm": 10.0}')
        keys = bf.cut_bearing_keys([good, poisoned])
        self.assertIn("briggs_0.40_1.000", keys)

    def test_agreement_invalid_last_line_does_not_promote_stale_key(self):
        """(d) inverse: a valid AZIMUTHAL-ONLY line followed by an invalid
        line with (otherwise) good cuts must NOT be treated as cut-bearing --
        the invalid line is invisible, so the last-standing valid line (no
        cuts) is what counts."""
        bf = self.backfill
        good = _profile_line("briggs_0.40_1.000", cut=False)
        poisoned = ('{"key": "briggs_0.40_1.000", "res_geo_arcsec": 0.1, '
                   '"r_arcsec": [0.0, 0.1], "psf": [1.0, NaN], '
                   '"cut_r_arcsec": [-0.1, 0.0, 0.1], '
                   '"cut_maj": [0.2, 1.0, 0.2], "cut_min": [0.1, 1.0, 0.1], '
                   '"cut_rmax_fwhm": 10.0}')
        keys = bf.cut_bearing_keys([good, poisoned])
        self.assertNotIn("briggs_0.40_1.000", keys)


class TestPointKeyNegativeZero(unittest.TestCase):
    """FIX 3: sweep.point_key folds a robust/taper that rounds to -0.0."""

    def setUp(self):
        mods = _modules()
        if mods is None:
            self.skipTest("curvegen/sweep.py needs CASA here")
        self.point_key = mods[0].point_key

    def test_negative_zero_folds_to_positive(self):
        pk = self.point_key
        self.assertEqual(pk("briggs", -0.0, 0.0), "briggs_0.00_0.000")
        self.assertEqual(pk("briggs", -0.001, 0.0), pk("briggs", 0.0, 0.0))
        self.assertEqual(pk("briggs", -0.004, 1.0), "briggs_0.00_1.000")

    def test_nonzero_values_unchanged(self):
        pk = self.point_key
        self.assertEqual(pk("briggs", -1.2, 5.0), "briggs_-1.20_5.000")
        self.assertEqual(pk("briggs", 0.4, 12.0), "briggs_0.40_12.000")
        # a legitimate -0.01 (rounds AWAY from zero) is preserved
        self.assertEqual(pk("briggs", -0.006, 0.0), "briggs_-0.01_0.000")


class TestCaptureProfileCutsFlag(unittest.TestCase):
    """FIX 1: capture_profile returns True only when the cut fields were
    actually written; an azimuthal-only fallback returns False."""

    def _sweep(self):
        mods = _modules()
        if mods is None:
            self.skipTest("curvegen/sweep.py needs CASA here")
        return mods[0]

    def test_flag_tracks_cut_fields(self):
        sweep_mod = self._sweep()

        class FakeSweep(sweep_mod.Sweep):
            def __init__(self, sa):            # skip CASA/file setup
                self.subarray = sa

        saved = (sweep_mod.psf_radial_profile,
                 sweep_mod.psf_axis_cuts_from_psf, sweep_mod.PROFILE_DIR)
        try:
            sweep_mod.psf_radial_profile = lambda p, r: ([0.0, 0.1], [1.0, 0.2])
            sweep_mod.psf_axis_cuts_from_psf = \
                lambda p, r, bpa, **k: ([-0.1, 0.0, 0.1], [0.2, 1.0, 0.2],
                                        [0.1, 1.0, 0.1])
            with tempfile.TemporaryDirectory() as tmp:
                sweep_mod.PROFILE_DIR = tmp
                s = FakeSweep("core")
                # cuts written -> True
                self.assertTrue(s.capture_profile(
                    "briggs_0.40_1.000", "x.psf", 0.1, beam=(0.1, 0.08, 10.0)))
                # no beam -> azimuthal only -> False
                self.assertFalse(s.capture_profile(
                    "briggs_0.40_1.000", "x.psf", 0.1))
                # cut capture raises -> swallowed to azimuthal only -> False
                def boom(*a, **k):
                    raise RuntimeError("cut capture failed")
                sweep_mod.psf_axis_cuts_from_psf = boom
                self.assertFalse(s.capture_profile(
                    "briggs_0.40_1.000", "x.psf", 0.1, beam=(0.1, 0.08, 10.0)))
                with open(os.path.join(tmp, "core.jsonl")) as fh:
                    last = json.loads(fh.read().splitlines()[-1])
                self.assertNotIn("cut_maj", last)   # the fallback line has no cut
        finally:
            (sweep_mod.psf_radial_profile,
             sweep_mod.psf_axis_cuts_from_psf, sweep_mod.PROFILE_DIR) = saved


class TestBackfillTally(unittest.TestCase):
    """FIX 1: unresolved anchors (missing row / cut-failure) are tallied and
    surfaced as a nonzero exit, and imaging keeps going past a failure."""

    def _mods(self):
        mods = _modules()
        if mods is None:
            self.skipTest("curvegen/backfill_psf.py needs CASA here")
        return mods

    def test_subarray_tally(self):
        _sweep, bf = self._mods()

        class FakeSweep:
            def __init__(self, sa):
                self.subarray = sa

        keys = ["briggs_-2.00_0.000", "briggs_-1.60_0.000", "briggs_0.00_0.000"]
        rows = {  # -1.60 has NO row -> unresolved (missing); others usable
            "briggs_-2.00_0.000": dict(status="ok", cell_arcsec="0.01",
                                       imsize="4096", weighting="briggs",
                                       robust="-2.0", taper_mas="0.0"),
            "briggs_0.00_0.000": dict(status="ok", cell_arcsec="0.01",
                                      imsize="4096", weighting="briggs",
                                      robust="0.0", taper_mas="0.0"),
        }
        saved = (bf.ReadOnlyResultsSweep, bf.plan, bf.row_index, bf.backfill_one)
        try:
            bf.ReadOnlyResultsSweep = FakeSweep
            bf.plan = lambda sw, sa: (set(keys), set(), set(keys))
            bf.row_index = lambda sw: rows
            # 0.00 images but its cut capture fails (returns False)
            bf.backfill_one = \
                lambda sw, sa, key, row: key != "briggs_0.00_0.000"
            res = bf.backfill_subarray("core")
            self.assertEqual(res["imaged"], 1)        # -2.00 resolved
            self.assertEqual(res["unresolved"], 2)    # -1.60 missing + 0.00 cut-fail
            self.assertEqual(res["ran"], 2)           # -2.00 and 0.00 ran tclean
        finally:
            (bf.ReadOnlyResultsSweep, bf.plan, bf.row_index,
             bf.backfill_one) = saved

    def test_main_exits_nonzero_on_unresolved(self):
        _sweep, bf = self._mods()
        saved = (bf.registry_paths, bf.offered_order, bf.backfill_subarray)
        old_argv = sys.argv
        try:
            bf.registry_paths = lambda rev, mode: ("x.csv", "y.csv")
            bf.offered_order = lambda csv: ["core"]
            sys.argv = ["backfill_psf.py"]
            bf.backfill_subarray = lambda sa, dry_run=False, limit=None: \
                dict(imaged=0, unresolved=1, deferred=0, ran=1)
            with self.assertRaises(SystemExit) as cm:
                bf.main()
            self.assertEqual(cm.exception.code, 1)
            # all resolved -> clean return (no SystemExit)
            bf.backfill_subarray = lambda sa, dry_run=False, limit=None: \
                dict(imaged=1, unresolved=0, deferred=0, ran=1)
            bf.main()
        finally:
            (bf.registry_paths, bf.offered_order, bf.backfill_subarray) = saved
            sys.argv = old_argv


class TestStaleProductCleanup(unittest.TestCase):
    """FIX 2: partial products from a walltime-killed prior run are removed
    BEFORE tclean (the workdir imagename is stable across runs)."""

    def test_pre_tclean_cleanup(self):
        mods = _modules()
        if mods is None:
            self.skipTest("curvegen/backfill_psf.py needs CASA here")
        sweep, bf = mods
        order = []
        saved = (bf._remove_products, sweep.tclean, bf.beam_arcsec)
        try:
            bf._remove_products = lambda name: order.append("clean")
            sweep.tclean = lambda **kw: order.append("tclean")
            bf.beam_arcsec = lambda p: (0.5, 0.4, 12.0)
            inst = bf.ReadOnlyResultsSweep.__new__(bf.ReadOnlyResultsSweep)
            inst.subarray = "core"
            inst.vis = "fake.ms"
            inst.workdir = "/tmp/wd"
            inst.ensure_ready = lambda: None
            inst.capture_profile = lambda *a, **k: True
            row = dict(weighting="briggs", robust="-1.2", taper_mas="5.0",
                       imsize="4096", cell_arcsec="0.05", status="ok")
            key = bf._canonical_key("briggs", -1.2, 5.0)
            self.assertTrue(bf.backfill_one(inst, "core", key, row))
            # a clean happens before the tclean, and again in finally
            self.assertEqual(order[0], "clean")
            self.assertLess(order.index("clean"), order.index("tclean"))
            self.assertEqual(order[-1], "clean")
        finally:
            (bf._remove_products, sweep.tclean, bf.beam_arcsec) = saved


class TestNoCurveDataWrite(unittest.TestCase):
    """The 'must never touch curve data' guarantee: mechanism + structure."""

    def test_readonly_sweep_record_raises(self):
        mods = _modules()
        if mods is None:
            self.skipTest("curvegen/backfill_psf.py needs CASA here")
        sweep, backfill = mods
        self.assertTrue(issubclass(backfill.ReadOnlyResultsSweep, sweep.Sweep))
        inst = backfill.ReadOnlyResultsSweep.__new__(
            backfill.ReadOnlyResultsSweep)          # skip CASA/file __init__
        with self.assertRaises(RuntimeError):
            inst.record({"weighting": "natural", "robust": "2.0",
                         "taper_mas": "0.0"})

    def test_backfill_source_has_no_results_writer_call(self):
        """No code path in backfill_psf.py calls a Sweep results writer.  This
        is CASA-free (a static AST scan), so it holds even where the module
        cannot be imported."""
        forbidden = {"record", "run_point", "skip_point", "append_row"}
        path = os.path.join(CURVEGEN, "backfill_psf.py")
        with open(path) as f:
            tree = ast.parse(f.read())
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute):
                    called.add(fn.attr)
                elif isinstance(fn, ast.Name):
                    called.add(fn.id)
        self.assertEqual(called & forbidden, set(),
                         "backfill_psf.py calls a results writer: %s"
                         % (called & forbidden))


class TestTcleanParity(unittest.TestCase):
    """The sweep and the backfill must build the SAME tclean call."""

    def test_tclean_called_only_in_run_tclean(self):
        """CASA-free structural guarantee that tclean_kwargs/run_tclean is the
        single place the call is constructed and executed."""
        path = os.path.join(CURVEGEN, "sweep.py")
        with open(path) as f:
            tree = ast.parse(f.read())
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for sub in ast.walk(node):
                    if (isinstance(sub, ast.Call)
                            and isinstance(sub.func, ast.Name)
                            and sub.func.id == "tclean"
                            and node.name != "run_tclean"):
                        offenders.append(node.name)
        self.assertEqual(offenders, [],
                         "tclean() called outside run_tclean: %s" % offenders)

    def test_run_point_and_backfill_use_identical_tclean_kwargs(self):
        mods = _modules()
        if mods is None:
            self.skipTest("curvegen/backfill_psf.py needs CASA here")
        sweep, backfill = mods

        calls = []
        saved = {n: getattr(sweep, n) for n in
                 ("tclean", "beam_arcsec", "image_rms", "psf_skirt",
                  "CAPTURE_PROFILES")}
        saved_bf_beam = backfill.beam_arcsec
        try:
            # single interception point for BOTH paths (run_tclean -> tclean)
            sweep.tclean = lambda **kw: calls.append(kw)
            sweep.beam_arcsec = lambda p: (0.5, 0.4, 12.0)
            sweep.image_rms = lambda p: 1.0
            sweep.psf_skirt = lambda p, r: (0.1, None)
            sweep.CAPTURE_PROFILES = False
            backfill.beam_arcsec = lambda p: (0.5, 0.4, 12.0)

            # -- run_point path (skip CASA __init__, stub CASA setup) --
            sp = sweep.Sweep.__new__(sweep.Sweep)
            sp.subarray = "core"
            sp.limit = None
            sp.n_run = 0
            sp.rows = {}
            sp.vis = "fake.ms"
            sp.cell = 0.05
            sp.workdir = "/tmp/wd"
            sp.imsize = 4096
            sp.beam_cap = None
            sp.min_uvrange_m = None
            sp.ensure_ready = lambda: None
            sp.record = lambda row: None            # never write curve data here
            sp.run_point("briggs", -1.2, 5.0)

            # -- backfill path, SAME point and parameters --
            bf = backfill.ReadOnlyResultsSweep.__new__(
                backfill.ReadOnlyResultsSweep)
            bf.subarray = "core"
            bf.vis = "fake.ms"
            bf.workdir = "/tmp/wd"
            bf.ensure_ready = lambda: None
            bf.capture_profile = lambda *a, **k: None
            cell_pt = max(0.05, 5.0 / sweep.OVERSAMPLE / 1e3)
            row = dict(weighting="briggs", robust="-1.2", taper_mas="5.0",
                       imsize="4096", cell_arcsec="%.6g" % cell_pt,
                       status="ok")
            key = backfill._canonical_key("briggs", -1.2, 5.0)
            backfill.backfill_one(bf, "core", key, row)

            self.assertEqual(len(calls), 2, "both paths must call tclean once")

            def without_imagename(kw):
                kw = dict(kw)
                kw.pop("imagename", None)    # per-call image name differs
                return kw

            self.assertEqual(without_imagename(calls[0]),
                             without_imagename(calls[1]))
        finally:
            for n, v in saved.items():
                setattr(sweep, n, v)
            backfill.beam_arcsec = saved_bf_beam


if __name__ == "__main__":
    unittest.main()

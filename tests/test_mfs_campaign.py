"""CASA-free contracts for the first (Ka-band) MFS campaign tranche."""

import csv
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CURVEGEN = ROOT / "curvegen"
REGISTRY = ROOT / "sa_select" / "data" / "config_registry.csv"


def run_config(code, **extra_env):
    env = dict(os.environ, NGVLA_REV="revF", NGVLA_SIM_MODE="track",
               NGVLA_BAND="band4")
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", code], cwd=str(CURVEGEN), env=env,
        text=True, capture_output=True)


class TestMFSBandAxis(unittest.TestCase):

    def test_registry_has_extended_schema_and_both_ka_modes(self):
        with REGISTRY.open(newline="") as f:
            rows = list(csv.DictReader(f))
        # Re-opened fieldnames are clearer than depending on seek behavior.
        with REGISTRY.open(newline="") as f:
            fieldnames = csv.DictReader(f).fieldnames
        for name in ["band", "ref_freq_ghz", "freq_lo_ghz",
                     "freq_hi_ghz", "nchan", "curve_types", "noise_policy"]:
            self.assertIn(name, fieldnames)
        ka = {(r["rev"], r["sim_mode"], r["band"]): r for r in rows
              if r["band"]}
        self.assertEqual(set(ka), {("revF", "track", "band4"),
                                   ("revF", "snapshot", "band4")})
        for row in ka.values():
            self.assertEqual((row["ref_freq_ghz"], row["freq_lo_ghz"],
                              row["freq_hi_ghz"]),
                             ("27.0", "20.25", "33.75"))
            self.assertEqual(row["curve_types"], "both")
            self.assertEqual(row["noise_policy"], "equal")

        from sa_select.curves import load_campaign_registry, load_registry
        full = load_campaign_registry()
        self.assertIn(("revF", "track", "band4"), full)
        # Selector-facing legacy view remains mono and cannot accidentally
        # apply 30/f scaling to a fixed-window native curve.
        self.assertEqual(load_registry()[("revF", "track")],
                         ("subarrays.csv", "revf_curves.csv"))

    def test_mfs_metadata_keeps_native_caps_out_of_30ghz_field(self):
        for mode in ("track", "snapshot"):
            path = (ROOT / "sa_select" / "data" /
                    ("subarrays_revf_mfs_band4_%s.csv" % mode))
            with path.open(newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 7)
            self.assertTrue(all("beam_cap_arcsec_native" in row for row in rows))
            self.assertTrue(all(not row["beam_cap_arcsec_30ghz"] for row in rows))

    def test_registry_has_robust_step_column_blank_for_mono_set_for_band4(self):
        with REGISTRY.open(newline="") as f:
            rows = list(csv.DictReader(f))
        with REGISTRY.open(newline="") as f:
            fieldnames = csv.DictReader(f).fieldnames
        self.assertIn("robust_step", fieldnames)
        self.assertEqual(fieldnames[-1], "robust_step")   # appended, stable order
        for r in rows:
            if r["band"]:
                self.assertEqual(r["robust_step"], "0.2")
            else:
                self.assertEqual(r["robust_step"], "")

    def test_mono_robust_list_is_byte_identical(self):
        # C1 (6 Sep 2026): ROBUST_STEP is registry-driven, but every mono row
        # has a blank robust_step, so the 11-value 0.4-step list must be
        # unchanged.
        proc = subprocess.run(
            [sys.executable, "-c",
             "import config as c\n"
             "assert c.ROBUST_STEP == 0.4, c.ROBUST_STEP\n"
             "assert c.ROBUST_LIST == [round(-2.0 + 0.4*i, 2) "
             "for i in range(11)], c.ROBUST_LIST\n"],
            cwd=str(CURVEGEN), text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_band4_robust_list_has_21_values_at_0_2_step(self):
        proc = run_config(
            "import config as c\n"
            "assert c.ROBUST_STEP == 0.2, c.ROBUST_STEP\n"
            "assert len(c.ROBUST_LIST) == 21, len(c.ROBUST_LIST)\n"
            "assert c.ROBUST_LIST[0] == -2.0 and c.ROBUST_LIST[-1] == 2.0\n",
            NGVLA_SIM_MODE="snapshot", NGVLA_NCHAN="32")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_manifest_records_robust_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = ("""
import campaign_manifest as cm
cm.RESULTS_DIR = %r
data = cm.ensure_manifest(create=True, casa_version='CASA-test')
assert data['campaign']['robust_step'] == 0.2, data['campaign']
assert data['campaign']['n_robust'] == 21, data['campaign']
""" % tmp)
            proc = run_config(code, NGVLA_SIM_MODE="snapshot",
                             NGVLA_NCHAN="32")
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_mfs_curve_types_both_accepted_unknown_rejected(self):
        proc = run_config("import config as c; assert c.CURVE_TYPES == 'both'")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Exercise the reject path with a genuinely bad registry value: a
        # scratch copy of the registry with one extra row (a private scratch
        # sim_mode so the real band4 rows are untouched), restored in
        # `finally`.  band4 must stay a real BANDS key (config.py validates
        # the band name before ever reading the registry row).
        original = REGISTRY.read_text()
        try:
            REGISTRY.write_text(
                original.rstrip("\n") + "\n"
                "revF,test_curve_types,band4,27.0,20.25,33.75,32,nonsense,"
                "equal,subarrays_revf_mfs_band4_track.csv,"
                "revf_track_band4_curves.csv,0.2\n")
            proc = run_config("import config", NGVLA_SIM_MODE="test_curve_types",
                              NGVLA_NCHAN="32")
        finally:
            REGISTRY.write_text(original)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("curve_types must be", proc.stderr)

    def test_mfs_config_requires_explicit_nchan(self):
        # Registry nchan is pinned to 32 for band4 (bmason, 6 Sep 2026), so
        # config.py now resolves nchan from the registry with no env var set;
        # confirm that resolution rather than the old blank-registry failure.
        proc = run_config("import config; assert config.NCHAN == 32")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_mfs_config_nchan_override_needs_variant(self):
        # Production must match the pinned registry nchan (32); a named
        # pilot variant may override it (27-vs-54 confirmation pilot).
        proc = run_config("import config", NGVLA_NCHAN="27")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("disagrees with registry nchan=32", proc.stderr)
        proc = run_config("import config; assert config.NCHAN == 27; "
                          "assert config.RESULTS_DIR.endswith('_pilot-nchan027-equal')",
                          NGVLA_NCHAN="27",
                          NGVLA_CAMPAIGN_VARIANT="pilot-nchan027-equal")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_mfs_config_routes_fixed_window_and_separate_paths(self):
        code = """
import config
assert config.MFS and config.BAND == 'band4'
assert config.NCHAN == 32
assert (config.REF_FREQ_GHZ, config.FREQ_LO_GHZ, config.FREQ_HI_GHZ) == (27.0, 20.25, 33.75)
assert config.FIRST_CHANNEL_CENTER_GHZ == 20.4609375
assert config.SIM['frequency'] == '20.4609375GHz'
assert config.SIM['channel_width'] == '0.421875GHz'
assert config.SIM['correlations'] == 'RR LL'
assert config.SIM['expected_integrations'] == 240
assert config.RESULTS_DIR.endswith('results-revF_track_band4')
assert sorted(config.SUBARRAYS) == sorted(config.MFS_SUBARRAYS)
"""
        proc = run_config(code, NGVLA_NCHAN="32")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_mfs_variant_isolates_artifacts_but_reuses_geometry(self):
        code = """
import config
assert config.CAMPAIGN_VARIANT == 'pilot-nchan032'
assert config.CFG_DIR.endswith('configs-revF_track_band4')
assert config.RESULTS_DIR.endswith('results-revF_track_band4_pilot-nchan032')
assert config.MS_DIR.endswith('ms-revF_track_band4_pilot-nchan032')
assert config.WORK_DIR.endswith('work-revF_track_band4_pilot-nchan032')
"""
        proc = run_config(code, NGVLA_NCHAN="32",
                          NGVLA_CAMPAIGN_VARIANT="pilot-nchan032")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_mfs_variant_rejects_unsafe_or_mono_values(self):
        proc = run_config("import config", NGVLA_NCHAN="32",
                          NGVLA_CAMPAIGN_VARIANT="../escape")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("safe slug", proc.stderr)

        env = dict(os.environ, NGVLA_REV="revF", NGVLA_SIM_MODE="snapshot",
                   NGVLA_BAND="", NGVLA_CAMPAIGN_VARIANT="pilot")
        proc = subprocess.run([sys.executable, "-c", "import config"],
                              cwd=str(CURVEGEN), env=env, text=True,
                              capture_output=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("only valid for MFS", proc.stderr)

    def test_mfs_sampler_mode_stays_fresh_after_table_is_populated(self):
        code = """
from adaptive import PointTable, Sampler
rows = [
    dict(weighting='natural', robust=2.0, taper_mas=0.0,
         res_geo_arcsec=0.0013, sigma_dirty=1.0, skirt=0.05, status='ok'),
    dict(weighting='briggs', robust=-2.0, taper_mas=0.0,
         res_geo_arcsec=0.0010, sigma_dirty=1.02, skirt=0.05, status='ok'),
]
table = PointTable(rows, subarray='core')
assert Sampler('core', table=table).mode == 'fresh'
try:
    Sampler('core', table=table, mode='retrofit')
except ValueError as exc:
    assert 'require fresh' in str(exc)
else:
    raise AssertionError('MFS retrofit mode was accepted')
"""
        proc = run_config(code, NGVLA_NCHAN="32")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_manifest_is_persisted_and_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = """
import json
import campaign_manifest as cm
cm.RESULTS_DIR = %r
first = cm.ensure_manifest(create=True, casa_version='CASA-test')
second = cm.ensure_manifest(create=False, casa_version='CASA-test')
assert first == second and first['spectral_window']['nchan'] == 32
path = cm.manifest_path()
data = json.load(open(path))
assert data['campaign']['run_mode'] == 'fresh'
assert data['campaign']['variant'] == ''
data['spectral_window']['nchan'] = 64
json.dump(data, open(path, 'w'))
try:
    cm.ensure_manifest(create=False, casa_version='CASA-test')
except RuntimeError as exc:
    assert 'does not match' in str(exc)
else:
    raise AssertionError('changed manifest was accepted')
""" % tmp
            proc = run_config(code, NGVLA_NCHAN="32")
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_mfs_imaging_and_ms_validation_contracts_are_present(self):
        sweep = (CURVEGEN / "sweep.py").read_text()
        simulate = (CURVEGEN / "simulate.py").read_text()
        for text in ["specmode=\"mfs\"", "nterms=1",
                     "deconvolver=\"hogbom\"", "stokes=\"I\"",
                     "parallel=False"]:
            self.assertIn(text, sweep)
        self.assertIn('stokes=SIM["correlations"]', simulate)
        self.assertIn('_validate_ms(ms_path)', simulate)
        self.assertIn('os.path.join(ms_path, "SPECTRAL_WINDOW")', simulate)
        self.assertIn('os.path.join(ms_path, "POLARIZATION")', simulate)

    def test_mfs_collector_uses_native_not_30ghz_schema(self):
        code = """
import collect
assert 'resolution_arcsec_native' in collect.OUT_FIELDS
assert 'taper_arcsec_native' in collect.OUT_FIELDS
assert 'band' in collect.OUT_FIELDS
assert 'ref_freq_ghz' in collect.OUT_FIELDS
assert 'resolution_arcsec_30ghz' not in collect.OUT_FIELDS
assert 'taper_arcsec_30ghz' not in collect.OUT_FIELDS
"""
        proc = run_config(code, NGVLA_NCHAN="32")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_mfs_report_routes_native_schema_and_enables_fixed_calculator(self):
        code = """
import make_report as mr
assert mr.registry_paths('revF', 'track', 'band4')[1].endswith(
    'revf_track_band4_curves.csv')
combo = mr.combo_entry('revF', 'track', 'band4')
assert combo['key'] == 'revF_track_band4'
assert not combo['imaging_omitted'] and not combo['calculator_omitted']
assert '30/f-scaled' in combo['sub_html']
mr.ACTIVE_ORDER = ['main']
sens = mr.build_mfs_sens_table()['main']
assert sens['freq_ghz'] == [27.0]
assert sens['sigma_nat_ujy'][0] > 0
"""
        proc = run_config(code, NGVLA_NCHAN="32")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_snapshot_sim_pilot_is_isolated_and_simulation_only(self):
        batch = (CURVEGEN / "mfs_snapshot_sim_pilot.sbatch").read_text()
        submit = (CURVEGEN / "submit_mfs_snapshot_sim_pilot.sh").read_text()
        self.assertIn("NGVLA_SIM_MODE=snapshot", batch)
        self.assertIn("NGVLA_BAND=band4", batch)
        self.assertIn("pilot-nchan%03d-equal", batch)
        self.assertIn('"$CG/simulate.py" "$SA"', batch)
        self.assertIn("/usr/bin/time -v", batch)
        self.assertNotIn("fill_grid.py", batch)
        self.assertNotIn("adaptive.py", batch)
        self.assertNotIn("collect.py", batch)
        self.assertIn('NCHAN_LIST="27:54"', submit)
        self.assertIn("NGVLA_MFS_MS_BASE", submit)


class TestSubmitCampaignModeSwitch(unittest.TestCase):
    """`submit_campaign.sh --mode mfs|1chan` replaces `--band` (bmason,
    7 Sep 2026): `--band` is confusing since the mono campaign is also Ka
    band.  These are CASA-free: no sbatch is ever reached."""

    def test_mfs_band_lookup_resolves_registered_combo(self):
        proc = subprocess.run(
            [sys.executable, "campaign_tasks.py", "mfs_band"],
            cwd=str(CURVEGEN), text=True, capture_output=True,
            env=dict(os.environ, NGVLA_REV="revF", NGVLA_SIM_MODE="snapshot"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "band4")

    def test_mfs_band_lookup_fails_closed_with_no_mfs_row(self):
        proc = subprocess.run(
            [sys.executable, "campaign_tasks.py", "mfs_band"],
            cwd=str(CURVEGEN), text=True, capture_output=True,
            env=dict(os.environ, NGVLA_REV="revC", NGVLA_SIM_MODE="track"))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no MFS combo registered for revC/track", proc.stderr)

    def test_mfs_band_lookup_does_not_import_config(self):
        # The lookup must work before NGVLA_BAND is decided, so it cannot go
        # through config.py's module-level BAND validation: the mfs_band
        # function body must not import config.
        import re
        text = (CURVEGEN / "campaign_tasks.py").read_text()
        match = re.search(r"def mfs_band\(.*?\n(?=\ndef )", text, re.S)
        self.assertIsNotNone(match, "mfs_band function not found")
        self.assertNotIn("import config", match.group(0))

    def test_submit_campaign_usage_mentions_mode_not_band(self):
        proc = subprocess.run(["bash", str(CURVEGEN / "submit_campaign.sh")],
                              cwd=str(ROOT), text=True, capture_output=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--mode", proc.stderr)

    def test_submit_campaign_rejects_band_before_any_submission(self):
        # --prep-only would otherwise be the first thing that could reach
        # sbatch; --band must be rejected before that, so put it first on
        # the line and confirm nothing about sbatch is invoked.
        proc = subprocess.run(
            ["bash", str(CURVEGEN / "submit_campaign.sh"),
             "revF", "snapshot", "--band", "band4", "--prep-only"],
            cwd=str(ROOT), text=True, capture_output=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--mode mfs", proc.stderr)
        self.assertNotIn("prep job", proc.stdout)


if __name__ == "__main__":
    unittest.main()

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
               NGVLA_BAND="band4", **extra_env)
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
            self.assertEqual(row["curve_types"], "ptsrc")
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

    def test_mfs_config_requires_explicit_nchan(self):
        proc = run_config("import config")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("requires nchan", proc.stderr)

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
assert combo['imaging_omitted'] and not combo['calculator_omitted']
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
        self.assertIn('NCHAN_LIST="16:32:64:128"', submit)
        self.assertIn("NGVLA_MFS_MS_BASE", submit)


if __name__ == "__main__":
    unittest.main()

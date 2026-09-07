# Spec: Band-4 MFS snapshot production run on the standard chain

Status: worker spec, written 6 Sep 2026 (Fable orchestrator) from bmason's
decisions D3 to D8 in `docs/worklog/mfs-campaigns.md`.  Build target: a sonnet
worker.  Review: Fable + bmason.

## Goal

Make the proven mono campaign chain (prep, sweep with refine, collect and
report) run for the combo revF / snapshot / band4 at nchan 32, both curve
types, 7 subarrays, with a denser robust grid, and present the result in the
combined report as its own "MFS snapshot" view.  Produce the exact command
lines for bmason; do NOT submit any Slurm job.

## Facts established by scouting (6 Sep)

- No chain script rejects a full grid or requires the adaptive sampler.
- `curvegen/config.py:318` `ROBUST_LIST = np.arange(-2.0, 2.01, 0.4)` (11
  values); `N_TAPERS = 14` (line 320).  `point_key` rounds robust to 0.01, so a
  0.2 step is distinguishable.  `sa_select/envelope.py:55` `MAX_ROBUST_GAP =
  0.45` assumes the 0.4 step.  Docstrings in `config.py:8`, `refine.py:9`
  mention the 0.4 step.  `adaptive.py:119` seeds with every other ROBUST_LIST
  value (parked code, must keep importing and passing its tests).
- `config.py` around line 141 hard-rejects `curve_types != "ptsrc"` for MFS.
  `make_report.py:737-744` already branches on CURVE_TYPES.
- Refine runs inside `campaign_sweep.sbatch:39-43` with env defaults
  REFINE_BUDGET=60, ROUNDS=3, SCAN_POINTS=8; `submit_campaign.sh` exposes
  `--refine-budget/--refine-rounds`; mono polish used 200/8.
- `fill_beam_caps.py` runs in `campaign_prep.sbatch` and writes
  `beam_cap_arcsec_native` for MFS (`subarrays_revf_mfs_band4_snapshot.csv`,
  currently blank).
- `make_report.py:999-1024` `combo_entry()` labels MFS combos
  `"Rev F — snapshot — BAND4"` and leaves `note_html=""`; the template shows
  `note_html` in `combo-note-card`.  `fixed_window` already locks the
  calculator to the band window.
- Pilot manifests in `curvegen/results-revF_snapshot_band4_pilot-nchan0{27,54}-equal/campaign_manifest.json`
  embed `curve_types: ptsrc` and the sampler constants; manifest validation is
  a full-equality check.

## Changes

### C1. Per-combo robust step (registry driven)

- Add a `robust_step` column to `sa_select/data/config_registry.csv` (blank
  for every mono row = 0.4; `0.2` for both band4 rows).  Keep the header
  order stable: append the column at the end.
- `config.py`: `ROBUST_STEP = float(registry robust_step or 0.4)`;
  `ROBUST_LIST = [round(r, 2) for r in np.arange(-2.0, 2.0 + ROBUST_STEP/2, ROBUST_STEP)]`.
  Mono behaviour must be byte-identical (assert the 11 values in a test).
  Band4: 21 values from -2.0 to 2.0.
- Record `robust_step` (and the resulting robust count) in the campaign
  manifest (`campaign_manifest.py`) so a resumed sweep cannot silently mix
  grids.
- `sa_select/envelope.py`: derive the robust-gap limit from the data instead
  of the constant: `gap_limit = 1.125 * (smallest positive robust spacing in
  the table)`, falling back to 0.45 when a table has a single robust.  Mono
  tables give 0.45 exactly (test it).
- Grep for any other place that assumes 11 robusts or 0.4 (refine.py
  quantisation, fill_grid.py, sweep_parallel.py row scheduling, collect.py,
  make_report.py, tests) and make each use `config.ROBUST_LIST`/`ROBUST_STEP`.
  Update the two docstrings.
- `adaptive.py` seeds stay "every other ROBUST_LIST value"; confirm
  `tests/test_adaptive.py` still passes (mono config).

### C2. Both curve types for MFS

- Set `curve_types` to `both` on both band4 registry rows.
- Remove the `curve_types == "ptsrc"` hard reject in `config.py`; accept
  `ptsrc` or `both`, reject anything else with a clear message.
- Check `sweep.py`, `collect.py`, `make_report.py` produce the imaging curve
  for MFS the same way as mono (skirt is measured at every point regardless).
  The MFS-specific `fill_beam_caps` column routing is unchanged.
- Pilot manifests: regenerate the two pilot `campaign_manifest.json` files
  through the normal code path so they carry `curve_types: both` and
  `robust_step`, or delete them if the chain recreates them; then confirm
  `bash curvegen/submit_mfs_imaging_pilot.sh --dry-run` still preflights.
  MS-relevant fields (band, nchan, noise policy, correlations) must not
  change.

### C3. Report: "MFS snapshot" as its own view

- `combo_entry()` label for MFS combos: `"Rev F — MFS snapshot"` (track would
  be `"Rev F — MFS 4 h track"`); no `BAND4` in any user-facing string.  The
  payload key `revF_snapshot_band4` stays.
- `note_html` for MFS combos, one or two sentences: broadband (MFS)
  continuum, N channels across lo to hi GHz (from config: 32, 20.25, 33.75),
  reference frequency 27 GHz, equal per-channel noise; resolution and eta are
  native to this window and are not frequency-scaled; internal key `band4`.
  Numbers come from config/registry, never hard-coded in the template.
- Check the template's calculator labels for MFS combos read sensibly
  ("MFS reference frequency", "Fixed MFS window") and that the combo selector
  sorts the MFS view after the mono views.

### C4. Chain readiness and command lines (no submission)

- Read `submit_campaign.sh` and the three `campaign_*.sbatch` files.  Confirm
  `NGVLA_BAND`, `NGVLA_NOISE_POLICY` (and nothing else needed) reach every
  stage's environment.  If `submit_campaign.sh` cannot pass the band, add a
  `--band band4` option (or document `NGVLA_BAND=band4 bash submit_campaign.sh
  revF snapshot ...`).
- Confirm prep will: write the band4 cfgs (already present in
  `curvegen/configs-revF_snapshot_band4/`), simulate the 32-channel snapshot
  MSes for the 7 subarrays under `$SCRATCH` (production dirs, no variant),
  measure seeds, run `fill_beam_caps.py` (fills main's blank cap) and its
  verify step.
- Confirm sweep will use the 21-robust grid and that refine runs after it.
  Recommended refine knobs for this run: `--refine-budget 200 --refine-rounds 8`
  (the mono polish settings; snapshot points are cheap).
- **Do not run `submit_campaign.sh` unless you have read it and a flag
  provably performs no `sbatch` call.**  Instead preflight CASA-free:
  `NGVLA_REV=revF NGVLA_SIM_MODE=snapshot NGVLA_BAND=band4 NGVLA_NOISE_POLICY=equal casapy -c "import config as c; print(c.NCHAN, c.ROBUST_LIST, c.CURVE_TYPES, c.RESULTS_DIR, c.MS_DIR)"`
  from `curvegen/`, and run whatever plan/`--plan-only` entry points the
  chain scripts offer that do not touch CASA or Slurm.
- Write a new section at the top of `docs/ops/RUN_CAMPAIGNS.md`, "MFS snapshot
  production run (Band 4 internal key)", with the exact launch line(s),
  monitor lines, expected outputs (results CSV path, per-combo report path,
  combined report rebuild), and the harvest checklist (exit codes, refine log
  grep, `fill_beam_caps --verify`, tests, data commit).  Mark the old MFS
  pilot sections as optional.

### C5. Tests

- Registry `robust_step` parsing; mono ROBUST_LIST unchanged (11 values);
  band4 gives 21 values; manifest carries robust_step.
- Envelope gap derivation: 0.45 for a 0.4-step table, 0.225 for a 0.2-step
  table.
- `curve_types both` accepted for band4; unknown value rejected.
- `combo_entry` for the band4 combo: label contains "MFS snapshot", contains
  no "BAND4"/"band4" outside the key; `note_html` contains "32" and "20.25".
- Full suite green: `casapy -m unittest discover -s tests -t .`.

### C6. Docs and log

- `docs/worklog/mfs-campaigns.md`: rewrite "Next actions" (bmason launches
  the production chain; harvest; report review) and append a dated paragraph
  to the 6 Sep entry naming what was built and the test result.
- `docs/plans/MFS_CAMPAIGN_PLAN.md`: one status line under the 6 Sep
  paragraphs: production chain adapted (robust step 0.2, both curves, MFS
  snapshot report view), launch pending bmason.
- Do not commit.

## Out of scope

Adaptive sampler, replay, MFS track mode, other bands, noise A/B.

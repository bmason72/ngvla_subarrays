# Rev D + snapshot campaign — implementation handoff (12 Jul 2026)

Implements `docs/archive/plans/campaign_proposal_revd_snapshot.md` (features 5 & 6) plus its
prerequisite, the deferred tranche **Component D** — the `(rev, sim_mode)` axis,
which had never been implemented. Codex was used as a design thinking-partner up
front and as a diff reviewer at the end (7 findings, all resolved — one was a
false positive, verified).

**Status: all code that does not depend on the not-yet-run sweeps is done and
verified. 98 tests green; the default `(revF, track)` path is byte-for-byte
identical (report HTML + collect output diffed old-vs-new; regenerated cfg
comments too). NOT committed — `git status` shows the change set.**

## Code changes (independent of the sweeps)

- **`curvegen/config.py`** — env-driven `NGVLA_REV`/`NGVLA_SIM_MODE`; per-rev
  component maps / `SUBARRAYS` / `IMSIZE` / `MIN_UVRANGE_M`; `config_suffix()`
  routing fresh `results-<rev>_<mode>/` dirs (MS/work → `$NGVLA_SCRATCH`);
  snapshot = single 60 s dump at HA=0; caps hardcoded for the default combo,
  else loaded from that combo's metadata CSV.
- **`sa_select/curves.py`** + **`sa_select/data/config_registry.csv`** —
  `CurveLibrary.for_config(rev, sim_mode)`; the registry
  (`rev,sim_mode,subarrays_csv,samples_csv`) is the single routing source of
  truth.
- **`curvegen/collect.py` / `curvegen/make_report.py`** — route the curve +
  subarray CSVs and the report through the registry (`--rev/--sim-mode`, its own
  HTML per combo, env-consistency guard).
- **`curvegen/simulate.py`** — snapshot window `("-30s","30s")` + a hard
  "exactly one integration" assertion (verified: 1 dump; a real snapshot `core`
  sweep was run end-to-end).
- **`curvegen/build_configs.py` / `curvegen/build_subarrays_csv.py`** —
  generalized per rev; generated `subarrays_revd.csv` (b_min honors the 178 m
  spurious-shorts cut — Rev D `lba` has the same pathology as Rev F Long) and
  `subarrays_revf_snapshot.csv` (Rev F geometry, caps blanked).
- **`curvegen/fill_beam_caps.py`** — the two-step caps: measures caps from the
  natural seeds into the metadata CSV, **fails closed** if a reference seed is
  missing, `--verify` preflight. Fully integration-tested (synthetic seeds →
  fill → verify → fail-closed).
- **`curvegen/sweep.py`** — `--seeds-only` (prevents pre-cap pilot rows from
  contaminating heterogeneous curves — a real bug codex caught).

## The sbatch to launch (you submit from a login node)

A 3-stage pipeline (`prep → sweep job-array → collect+report`, chained with
`--dependency=afterok`, env `--export`ed to every stage because a Slurm
dependency does not inherit it):

```
bash curvegen/submit_campaign.sh revF snapshot --time 24:00:00   # Campaign 1
bash curvegen/submit_campaign.sh revD track     --time 48:00:00   # Campaign 2
```

- Long-baseline (>2600 km) subarrays get their own node; the rest share one
  node (your standing rule) — `campaign_tasks.py groups` defines the mapping.
- `--prep-only` submits just the seed+caps QA gate first, so you can eyeball
  seed beams / imsize / cell in `prep_<jobid>.log` before the sweep burns
  node-hours (then submit the rest with the two commands it prints).
- Everything is resumable; a task that hits its walltime continues on resubmit.

New sbatch/helper files: `campaign_prep.sbatch`, `campaign_sweep.sbatch`,
`campaign_collect.sbatch`, `submit_campaign.sh`, `campaign_tasks.py`.

## Two things to know

- **Committed `subarrays_revd.csv` has blank caps by design** — the campaign's
  prep measures and fills them (`fill_beam_caps.py`); `--verify` fails closed
  until then. Commit the updated caps (and the routed curve CSV) after a
  campaign finishes.
- **Known cosmetic limitation:** a non-default report's `profile`/`qa`
  diagnostic blocks still show the Rev F reference values (the
  curves/heatmaps/LAS/sens ARE combo-correct; the output filename
  disambiguates).

## Follow-ons (not done, by design)

- **Rev D / snapshot** is a one-registry-row + rerun follow-on if wanted after
  seeing campaigns 1 + 2 (no new code).
- The selector/calculator CLI is not yet wired with a user-facing `--rev` flag
  (it still defaults to Rev F via `CurveLibrary()`); `for_config` exists for
  when a second dataset is swept and we want to expose it.

See `docs/plans/PLAN.md` (section "(rev, sim_mode) axis + Rev D / snapshot campaign
machinery, 12 Jul 2026") for the durable in-repo record, and
`tmp/codex_revd_snapshot_design.md` + `tmp/codex_review*.out` for the codex
consult/review transcripts.

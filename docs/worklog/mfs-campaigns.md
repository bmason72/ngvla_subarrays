# MFS broadband continuum campaigns — rolling worklog

Scope, design, and assumptions live in `docs/plans/MFS_CAMPAIGN_PLAN.md` and
`docs/features/MFS2_ADAPTIVE_SAMPLER_SPEC.md`; this file tracks only current status. See
`docs/plans/NEXT_AGENT.md` for the hand-off and open decisions for bmason.

## Current status (as of 6 Sep 2026)

Decisions D3/D4 (bmason, 6 Sep 2026): the adaptive quadtree sampler is set
aside (parked, not abandoned) for MFS v1; production uses the standard
mono-style campaign chain on the full fixed grid (11 robust values by the
canonical 14 tapers plus the natural row) in snapshot mode, Band 4 only, the
same 7 subarrays (core-inner, core, spiral, mid, core+spiral, spiral+mid,
main), nchan 32, equal per-channel noise. No MFS track campaign and no
further timing benchmark run now. See the `### 2026-09-06` log entry below
for the reasoning and what was learned from the V1 replay investigation.

### Built (code)

All uncommitted (last commit `c264af4`, 5 Sep, is doc cleanup only):

- MFS-2a: `NGVLA_BAND` routing, required-nchan checks, immutable per-combo
  campaign manifest, multi-channel "RR LL" simulation, pinned MFS tclean
  setup (`specmode mfs`, `nterms 1`, cell at top-of-band).
- MFS-2b hardened; MFS-2c leaf/segmented-edge foundation and band-native
  collect/report routing built and tested CASA-free (see
  `docs/plans/MFS_CAMPAIGN_PLAN.md` status block).
- MFS-3 imaging pilot launcher — **available** (not a gate; the 27-vs-54
  snapshot confirmation check may still be run) (spec
  `docs/plans/mfs-imaging-pilot-spec.md`):
  `curvegen/submit_mfs_imaging_pilot.sh`, `curvegen/mfs_imaging_pilot.sbatch`,
  `curvegen/mfs_pilot_points.py` (10 non-seed points shared verbatim across
  nchan variants), `curvegen/mfs_pilot_compare.py` (criteria |dη|/η < 0.5 %,
  |dres|/res < 1 %, endpoint checks; exit 3 on criteria fail),
  `tests/test_mfs_pilot.py` (21 tests).
- MFS-2d V1 replay harness — **parked** along with the sampler it certifies
  (spec `docs/plans/mfs-v1-replay-spec.md`): `curvegen/replay_v1.py`,
  `tests/test_replay_v1.py` (19 tests); `curvegen/adaptive.py` gained an
  optional, default-None `seed_tapers` override (+45/-15 lines,
  uncommitted).
- Full suite: `casapy -m unittest discover -s tests -t .` gives "Ran 404
  tests ... OK (skipped=1)" (run 6 Sep, after the config and replay fixes).

### Run (data)

- Slurm job **3470012** "ngvla_mfs_snap_sim", COMPLETED 2026-09-04 21:46,
  elapsed 19 s. Created 4 Band-4 snapshot MSes (core.ms, main.ms x nchan
  27/54) under `/scratch/10240/bmason72/ngvla_curvegen/ms-revF_snapshot_band4_pilot-nchan0{27,54}-equal/`,
  ~15 s / 236-327 MB MaxRSS each. Logs:
  `/work2/10240/bmason72/stampede3/mfs_snapshot_sim_3470012*.log`. Manifests
  only (no result CSVs) in `curvegen/results-revF_snapshot_band4_pilot-nchan0{27,54}-equal/`
  (untracked); antenna cfgs in `curvegen/configs-revF_snapshot_band4/`
  (untracked). `$SCRATCH` is purge-eligible; regeneration costs ~15 s/MS.
- V1 replay (CPU only, no Slurm, ran 5 Sep): `curvegen/reports/v1_replay/REPORT.md`
  plus 10 per-map JSONs; budget sweep in
  `curvegen/reports/v1_replay/sweep/b{140,280,560,1120}_{fail,fallback}/`.

  | budget | converged (of 10) | p90 sample_fraction | median regret_max_covered |
  | --- | --- | --- | --- |
  | 140 (spec/audit) | 0 | 0.783 | n/a (0/10 converged) |
  | 280 | 4 | 0.968 | 0.051 |
  | 560 | 6 | 0.991 | n/a |
  | 1120 | 10 | 0.999 | n/a |

  All numbers from the `--on-miss fail` oracle (`sweep/b*_fail/REPORT.md`);
  the nearest-row `--on-miss fallback` oracle plateaus at 3-4/10 converged
  and is not a valid certification tool. At budget 1120 the replay has
  sampled 99.9 % of the legacy lattice — a replay ceiling, not a production
  estimate. Persistent cut disagreements at every budget: ~4 false + 4
  missed cuts across the suite (revD/track spiral+mid false; revF/track
  core+spiral missed) — not yet investigated.

### Not yet done

- Imaging half of the MFS-3 pilot not launched: no
  `/work2/10240/bmason72/stampede3/mfs_imaging_pilot_*.log`, no
  `/scratch/10240/bmason72/ngvla_curvegen/mfs_imaging_pilot/`, no results
  CSVs, no `nchan_convergence_vs_*.md`, no `timing_track.md` (checked 6 Sep;
  `sacct` for 4-6 Sep shows only 3470012, backfill 3470047_2, and idev
  sessions).
- Track-mode cost/timing benchmark: dropped (D4, 6 Sep); no MFS track
  campaign is planned now, Band-4 snapshot mode only.
- Noise A/B pilot moot while MFS is Ka-only (config pins `equal`).
- `fill_beam_caps` not run for band4 (main's beam cap is blank; harmless for
  the pilot, required before production).
- MFS-4 wave runner — **parked** (D3, 6 Sep) along with the sampler it was
  built to drive; not built.
- The standard campaign chain (prep, sweep, refine, fill_grid, collect,
  report) has not yet been exercised for revF/snapshot/band4 at nchan 32.
  Scout inventory (6 Sep): no script rejects a full grid or requires the
  sampler; the earlier "do not use submit_campaign.sh for MFS" note was
  policy, not code. What remains: `config.py` (about line 141) hard-rejects
  `curve_types` other than `ptsrc` for MFS, so imaging curves need that
  guard relaxed (skirt is measured at every grid point regardless);
  `campaign_prep.sbatch` already runs `fill_beam_caps.py`, which writes the
  band4 `beam_cap_arcsec_native` column; collect tags the combo
  `revF_snapshot_band4-mfs` and the combined report keys it
  `revF_snapshot_band4` with a fixed-window calculator entry, so band4 would
  enter the release page as its own section unless excluded; no test yet
  drives the chain for band4 (a `--prep-only` dry run plus a smoke test is
  the gap).
- Nothing MFS has been committed.

### Decisions pending (bmason)

Open questions, per bmason's 6 Sep decision:

1. Point-source curves only, or both point-source and imaging curves, from
   the full grid?
2. Keep the 7-subarray set (core-inner, core, spiral, mid, core+spiral,
   spiral+mid, main)?
3. Whether Band-4 results enter the combined release page and calculator, or
   stay as per-combo CSVs and reports for now.
4. When to make the milestone commit of the MFS code.

Scope confirmed 6 Sep: Band 4 only; other bands scaled (approximation, see
MFS_CAMPAIGN_PLAN).

### Next actions (in order)

1. Optional: bmason launches the 27-vs-54 snapshot confirmation run (not a
   gate) to confirm 0.5 GHz channels are converged.
2. Scout and spec what the standard campaign chain (prep, sweep, refine,
   fill_grid, collect, report) needs to run for revF/snapshot/band4 at
   nchan 32, including removing adaptive-only guards that reject full-grid
   MFS.
3. `fill_beam_caps` for band4 (main's cap is blank).
4. bmason launches the snapshot full-grid wave.
5. Milestone commit of the MFS code + specs once bmason has reviewed.

## Log

### 2026-09-06

Status review (Fable orchestrator + haiku scout + sonnet worker), no code
changes. Verified against the filesystem and `sacct`: the imaging half of
the MFS-3 pilot has never been launched (only job 3470012, the simulation
half, and the CPU-only V1 replay have run); confirmed no imaging pilot logs,
scratch dirs, or result CSVs exist. Confirmed test suite green: `casapy -m
unittest discover -s tests -t .` -> 402 tests OK (skipped=1). Confirmed
nothing MFS is committed (`git status`/`git diff --stat` against last commit
`c264af4`). Created this `docs/worklog/` area and its convention
(`docs/worklog/README.md`) and this file. Flagged a doc inconsistency:
`docs/plans/mfs-campaigns-detail.md` still describes the MFS-3 convergence
pilot as band 2, both modes, nchan 16..512 with two consecutive doublings;
`docs/plans/MFS_CAMPAIGN_PLAN.md` (authoritative, 5 Sep status) narrowed it
to Band 4 snapshot, core+main, nchan 27 vs 54. Added a superseded-pointer
line to the detail doc rather than rewriting it.

Later 6 Sep: bmason set production nchan for Band 4 at 32 (0.5 GHz channels
across the 13.5 GHz Band-4 window, rounded up to the next power of two; D1),
turning the 27-vs-54 snapshot pilot into a confirmation run rather than a
gate on the value. bmason also confirmed the MFS campaigns are Band 4 only
for now; curves for the other bands come from scaling the Band-4 curves
with wavelength, an approximation whose largest expected error is at the
fine, negative-robust end because fractional bandwidth differs across bands
(Band 4 is 0.50; Bands 1/2 are about 0.96/1.10; Band 6 is about 0.22); a
cheap Band-2 vs scaled-Band-4 check on core and main is queued (D2). Pinned
`nchan` to 32 on both band4 rows in `sa_select/data/config_registry.csv`.
Updated `docs/plans/MFS_CAMPAIGN_PLAN.md`, `docs/plans/mfs-campaigns-detail.md`,
`docs/ops/RUN_CAMPAIGNS.md`, `docs/plans/NEXT_AGENT.md`, and this file to
record D1/D2 and the pinned value. Ran the full test suite after the
registry edit (`casapy -m unittest discover -s tests -t .`): one test
(`test_mfs_config_requires_explicit_nchan`) had asserted the old
blank-registry failure and was updated to assert the new resolved value
instead; result: 402 tests, OK (skipped=1).

Pinning nchan exposed a launch blocker: `curvegen/config.py` raised whenever
`NGVLA_NCHAN` disagreed with the registry value, so the 27-vs-54 confirmation
pilot (which exports NGVLA_NCHAN=27) would have failed its preflight against
the pinned 32. Fixed the same day: the disagreement check now applies only to
production runs (no `NGVLA_CAMPAIGN_VARIANT`); a named pilot variant, which
already has isolated MS/results/work dirs and its own manifest, may override
nchan. New test `test_mfs_config_nchan_override_needs_variant`; MFS test
modules pass (34 tests) and `submit_mfs_imaging_pilot.sh --dry-run` preflights
cleanly at nchan 27.

Replay anomaly investigation (sonnet worker, CASA-free; report
`curvegen/reports/v1_replay/INVESTIGATION.md`). Findings: (1) sample_fraction
above 1 was a metric bug (hits on capped rows counted against a denominator
that excludes them; four of ten maps inflated, one from a true 0.14 to a
reported 0.91). Fixed the same day in `replay_v1.py` (numerator counts ok-row
hits only; new `n_ok_hits` field; regression test). (2) The four
"converged but FAIL" maps fail only on uncovered resolution bins: the legacy
tables carry up to 75 distinct taper values from several campaigns, the
fresh seed and its dyadic bisection reach few of them, so the exact-hit
subset's envelope collapses. A replay-oracle artifact, not a sampler fault;
more budget cannot fix it. (3) revF/track core+spiral is genuinely
budget-limited: no leaf was blocked by a missed request; it converges
cleanly at budget 560 using 349 of 605 ok rows; resolution dominates the
residual. Four maps that never converge at 1120 were not traced. (4) The
false and missed step cells are far from each other in taper (different
decades) and one map's truth has no steps at all; fresh and retrofit modes
classify identical data identically, so this is sparse-subset aliasing in the
replay, not a mode or tolerance issue. Verdict: no evidence of a sampler
defect, but the replay as built cannot certify the sampler either, and the
evidence does not support relaxing to an accuracy gate at 280 evals (the
honest track map needed 560). Recommendation to bmason: replace the
exact-hit oracle with a continuous surrogate oracle (interpolated legacy
surfaces, any request answerable) so the sampler's logic is tested without
the grid mismatch, then set the production budget from that.

Later 6 Sep: bmason decided D3 and D4. D3: the adaptive quadtree sampler is
set aside for MFS v1 (parked, not abandoned). This parks MFS-2b/2c/2d/2e,
the V1 replay gate, and MFS-4 (the PyLauncher wave runner). Reasoning: the
sampler was designed on the assumption that a full MFS grid is unaffordable,
and that assumption is being dropped for snapshot mode; also, multi-channel
uv coverage very likely changes how eta and resolution respond to robust
relative to the mono simulations the sampler was tuned and tested on, so a
mono-based certification tests the wrong surface. D4: no MFS track campaign
and no further timing benchmark for now. Band-4 snapshot mode only. The
production path is the proven mono pipeline on the full fixed grid (11
robust values by the canonical 14 tapers plus the natural row), revF, the
same 7 subarrays (core-inner, core, spiral, mid, core+spiral, spiral+mid,
main), nchan 32, equal per-channel noise. Snapshot timing at 32 channels is
judged fine without a benchmark. What was learned (from the replay
investigation, `curvegen/reports/v1_replay/INVESTIGATION.md`): the replay's
failures were a metric bug (fixed), a coverage artifact of the fresh seed
versus the historical multi-campaign taper lattices, and sparse-subset
aliasing; the one traced track map genuinely needed about 560 evaluations;
no sampler defect was found. If the sampler is revived later, the cheap
snapshot MFS full grids are the right oracle for certifying it (real
multi-channel surfaces, grid built to coincide with its bisection points).
The 27-vs-54 snapshot confirmation pilot stays available (MSes exist;
launcher preflights cleanly) as an optional check that 0.5 GHz channels are
converged; it is not a gate. Open questions for bmason: point-source curves
only or both curves from the full grid; keep the 7-subarray set; whether
Band-4 results enter the combined release page and calculator or stay as
per-combo CSVs and reports for now; when to make the milestone commit of the
MFS code. Next step (agent side): scout and spec what the standard campaign
chain (prep, sweep, refine, fill_grid, collect, report) needs to run for
revF/snapshot/band4 at nchan 32, including removing adaptive-only guards
that reject full-grid MFS, and fill_beam_caps for band4 (main's cap is
blank). A scout is doing that inventory now; its findings will be added
later.

### 2026-09-05

MFS-3 imaging pilot launcher built (sonnet_worker, spec
`docs/plans/mfs-imaging-pilot-spec.md`): `curvegen/submit_mfs_imaging_pilot.sh`
+ `mfs_imaging_pilot.sbatch` (one slot: seeds -> pinned points -> points-file
sweeps -> compare), `mfs_pilot_points.py` (10 non-seed points: natural x
{mid, coarse} + robust {-2,-0.4,1.2} x {0, mid, coarse}), `mfs_pilot_compare.py`
(per-point |dη|/η < 0.5 %, |dres|/res < 1 %, endpoint checks, p95/max, timing
table; exit 3 on criteria fail), 21 tests. `--sim-mode track --nchan-list 27`
doubles as the cost benchmark. Band-4 `main` beam cap is blank (fill_beam_caps
not yet run for band4) — harmless for the pilot, required before production.

MFS-2d V1 replay harness built (sonnet_worker, spec
`docs/plans/mfs-v1-replay-spec.md`): `curvegen/replay_v1.py` (+19 tests);
`adaptive.py` gained an optional, default-None `seed_tapers` override.
Architecture finding: the fresh seed's 7 log-uniform tapers do not coincide
with the 14-level canonical lattice, so an exact-hit replay needs the seed
pinned to canonical[::2]+rim (the retrofit's grid); with that, exact-hit
fractions are 0.95-1.00. Verdict at the spec budget (audit 140): 0/10 maps
converge, all FAIL on budget exhaustion; p90 sample fraction 0.783 (threshold
0.60). Budget sweep: with the fail-on-miss oracle, convergence goes
0 -> 4 -> 6 -> 10 of 10 at budgets 140/280/560/1120; at 1120 the replay has
sampled 99.9 % of the legacy lattice (a replay ceiling, not a production
estimate); median regret_max_covered drops below 0.1 at budget ~280 (0.051).
Persistent cut disagreements at every budget: ~4 false + 4 missed cuts
across the suite (revD/track spiral+mid false; revF/track core+spiral
missed) — flagged for investigation, not yet done. The nearest-row fallback
oracle poisons certification (plateaus at 3-4/10 converged); `--on-miss
fail` is the honest oracle.

Consistency check: the mono retrofits (late-Aug waves, recovered from logs
that session) also spent ~80 evals/wave for 2-5 waves per map without
converging, so the replay is telling the truth about the certification
criterion, not about the replay mechanics.

Tests: 402 green (1 skipped). Nothing committed; pending bmason review of
the pilot launcher, the replay verdict, and the decisions logged in
`docs/plans/NEXT_AGENT.md`.

### 2026-09-04

MFS-2a landed: Ka-band routing (`NGVLA_BAND` env), required-nchan checks,
immutable per-combo campaign manifest, multi-channel simulation setup
(stokes "RR LL"), pinned MFS tclean setup (specmode mfs, nterms 1,
deconvolver hogbom, cell at top-of-band). MFS-2b substantially hardened.
MFS-2c leaf/segmented-edge foundation and band-native collect/report
routing built and CASA-free tested. Nothing launched yet at this point.

Simulation-only, snapshot nchan/RSS pilot readied and launched: Slurm job
**3470012** "ngvla_mfs_snap_sim", completed 21:46, elapsed 19 s total.
Created core.ms and main.ms Band-4 snapshot measurement sets at nchan 27
(0.5 GHz/channel) and 54 (0.25 GHz/channel) — 4 MSes, ~15 s and 236-327 MB
MaxRSS each. Logs under
`/work2/10240/bmason72/stampede3/mfs_snapshot_sim_3470012*.log`. This
validates the sim path and measures memory only; it does not run tclean or
touch production result tables.

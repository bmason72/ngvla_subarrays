# Spec: MFS-2d V1 retrospective replay harness

Written 5 Sep 2026 by the orchestrating agent for a sonnet_worker.  Read
`docs/features/MFS2_ADAPTIVE_SAMPLER_SPEC.md` ("Validation gates" -> V1, and
"Retrofit / warm-start mode"), `curvegen/adaptive.py` (esp. `PointTable`,
`QuadTree._seed_nodes`, `Sampler.plan_wave`, `run_wave_loop`,
`plan_only_report`), and how `tests/test_adaptive.py` drives `run_wave_loop`
with a fake sweep CASA-free.  Never run tclean/simulate; never `sbatch`.  Do
not edit `docs/plans/*`.  Tests: `casapy -m unittest discover -s tests -t .`
(362 green today; keep them green).

## Purpose

V1 gates deployment of the FRESH-seed MFS sampler: replay each existing mono
map's full point table through the sampler policy as a simulated acquisition
where each "measurement" is a table lookup, and score the result against the
full-table truth.

## Architecture finding you must handle (orchestrator, 5 Sep)

`QuadTree._seed_nodes` in fresh mode uses `N_SEED_TAPERS=7` log-uniform
levels between `t_min`/`t_max`; the mono lattice (`config.taper_list_mas`) has
14 log-spaced levels over the SAME endpoints.  7 levels over 6 intervals do not
coincide with 14 levels over 13 intervals, so a literal fresh replay would make
almost every tapered request an "unsupported request".  Therefore:

* Add an optional `seed_tapers=None` argument threaded `Sampler(...)` ->
  `QuadTree(...)`; when given (a list of taper_mas floats) fresh mode uses it
  instead of the 7 log-uniform levels.  Default `None` = today's behaviour,
  byte-for-byte; the manifest is NOT changed by this argument.  Add a test
  that the default path is unchanged.
* The replay harness runs fresh mode with `seed_tapers = canonical[::2]` plus
  the forced coarsest rim, exactly as retrofit mode derives them
  (`_seed_nodes` retrofit branch), so the seed wave hits exact keys; first
  bisections land on the skipped canonical tapers and on `ROBUST_LIST`
  midpoints (also exact); deeper bisections are exact only where the July/Aug
  retrofit waves measured them.
* Report, per map, the exact-hit fraction of requested keys, so bmason can
  judge how faithful the replay is.  Do not change production seed constants.

## Deliverables

1. `curvegen/replay_v1.py` (library + CLI, CASA-free; must import under
   plain casapy without CASA tasks being invoked).
   * `ReplaySweep(full_rows)`: `.rows` dict keyed by `point_key` (starts
     EMPTY); `run_point(weighting, robust, taper)` -> exact key hit: copy the
     full row into `.rows` and return it; miss: record an "unsupported
     request", pick the nearest full-table row in normalized (robust_to_u,
     taper_to_v) coordinates NOT already used, insert a COPY of it under the
     REQUESTED key with weighting/robust/taper rewritten to the request, flag
     it (`self.fallbacks`), return it.  Track requests, hits, fallbacks.
     `run_point` must never raise for a normal miss.
   * `replay_map(csv_path, subarray, beam_cap_mas, budget=None)`:
     full table = `PointTable.from_csv`; derive canonical seed tapers from
     its anchors via `config.grid_rows`/`taper_list_mas` exactly as the
     retrofit branch does; call `run_wave_loop(subarray, sweep=ReplaySweep,
     mode="fresh", budget=<fresh audit cap>, out=<buffer>)`; collect the
     stop reason (`"audit cap reached"` = budget exhaustion = FAIL).
   * Scoring (on EXACT hits only; fallback rows are excluded from every
     metric and from the replayed subset used for envelopes):
     - `sample_fraction` = exact hits used / rows in the full table (ok rows).
     - Envelope eta regret: build the point-source curve from the replayed
       exact-hit subset and from the full table with the SAME sa_select
       engine `collect.py` uses (find the function; do not reimplement the
       envelope), evaluate both on ~40 log-spaced resolution bins spanning
       the full curve's range, regret = eta_subset - eta_full; pass if
       max regret <= 0.1 (bins where the subset has no coverage count as
       failures and are listed).
     - Cuts: truth = `Sampler(full table, mode="retrofit").certify()` STEP
       cells (`feature_cells()`); replayed = final sampler STEP cells; match
       by overlapping `_leaf_res_range`; report false (replayed-only) and
       missed (truth-only) cuts; pass = 0 and 0.
     - Skirt feasibility at setpoints {0.05, 0.10, 0.15, 0.20}: for each
       resolution bin, "feasible" = some point within +-5% resolution has
       skirt <= setpoint; a mistake = full says feasible but subset says
       infeasible with margin > SIGMA skirt (0.02).  Pass = 0 mistakes.
     - Budget exhaustion = FAIL regardless.
   * Suite (spec finding #12; env per combo, so run each combo in a
     subprocess with `NGVLA_REV`/`NGVLA_SIM_MODE` set, or otherwise isolate
     config -- your choice, but one CLI command must run the whole suite):
     revD/snapshot {main+long, long, main}; revF/snapshot {main+long,
     long+mid+spiral+core-outer}; revD/track {long, main+long, spiral+mid};
     revF/track {long, core+spiral}.  Results CSVs: `curvegen/results/` is
     revF/track; others `curvegen/results-<rev>_<mode>/`; file names replace
     `+` with `_`.  Beam caps: use whatever `adaptive.py`'s CLI uses
     (`BEAM_CAP_ARCSEC` from config under that combo's env).
   * Acceptance: ALL maps pass AND p90 of sample_fraction <= 0.6.
   * Output: `curvegen/reports/v1_replay/<rev>_<mode>_<sa>.json` per map
     (metrics, requests/hits/fallbacks, stop reason, wave log) and
     `curvegen/reports/v1_replay/REPORT.md` (one table row per map + verdict
     + exact-hit fractions).  CLI: `replay_v1.py --suite` (all), or
     `replay_v1.py <subarray>` for the current env combo; `--out-dir`.
2. `tests/test_replay_v1.py` (CASA-free, synthetic tables, tmp dirs):
   exact hit vs unsupported vs flagged fallback; metrics exclude fallbacks;
   regret/cut/skirt scoring on a toy table with a known step; default
   `seed_tapers=None` leaves `_seed_nodes` output unchanged.
3. Run the real suite once on this dev node (it is CASA-free; a few minutes
   at most -- if any single map takes > 10 min, stop and report).  Commit
   nothing.

## Report back

Verdict table (map, sample fraction, exact-hit fraction, regret max, false/
missed cuts, skirt mistakes, stop reason, pass/fail); the p90 sample fraction;
tests count; any place the spec's metric definition was ambiguous and what
you chose; anything you could not do.

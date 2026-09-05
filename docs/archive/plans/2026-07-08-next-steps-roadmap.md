---
split_from: docs/plans/PLAN.md (lines 1325-1446 at commit 7f0a63f)
history: git log --follow docs/plans/PLAN.md
---
### Next-steps roadmap (8 Jul 2026, bmason directive)
Seven workstreams. **Sequencing constraint: the refine job (3285135) runs
`refine.py` then `collect.py` + `make_report.py` at its end, so DO NOT edit
`config/sweep/simulate/refine/envelope/make_report/collect/sensitivity/
report_template.html` until that job's final make_report has run** — those
edits would corrupt the in-flight run. `sa_select/{curves,selector,heuristics,
schema}.py` and new files are safe to edit meanwhile (the report path uses
`envelope`+`sensitivity`, not the selection layer).

1. **Full regular-grid fill by default + back-fill.** Drop the online pruning
   (eta-cap / beam-cap / convergence prune) in `curvegen/config.py`+`sweep.py`
   so every lattice cell is measured (bmason: "not a mode, a change"). Then
   re-sweep the current subarrays to back-fill the pruned cells. Compute
   (sbatch). Note: fuller grids make the bilinear cells denser/cleaner and
   shrink coverage gaps.
2. **[ENGINE DONE 8 Jul 2026] Threshold-relax (new DEFAULT).** `envelope.solve`
   default `mode="threshold"`: strict min-eta where a beam in the ±margin
   window has skirt≤s0 (relaxed=False, meets criterion); else min-skirt =
   best-achievable PSF (relaxed=True, best_skirt set), ties broken by eta, and
   **NO eta cap / skirt limit gates the relaxed answer** (bmason: report the
   best PSF whatever the eta). `relax=False` = strict-only. The old 1-for-1
   trade is preserved as `mode="legacy_trade"`. `SKIRT_TIE_TOL` for min-skirt
   ties. `curve()` gained `mode`. `curves.py` message reworded (no trade cap).
   Tests rewritten to the threshold policy (`threshold_pick` oracle,
   `TestThresholdRelax`; 65 green). Real-data effect: core/spiral/mid/
   core-inner meet 0.10 at 100% of resolutions (was 49% for core under λ=1),
   core+spiral 83%, spiral+mid 39%, main 12% (physical floor — honest).
   **REPORT SIDE DONE 8 Jul:** rewrote the calculator JS `lookupCurvePoint` to
   the threshold policy (min-eta among !relaxed window points, else min-skirt),
   removed `curveObjective`/`compareKeys`, updated `flagInfo`/markers/tooltips/
   prose (no more "trade"/"trade cap" language). Report regenerated; JS↔engine
   parity verified (worst |Δeta| 0.12 at the coarse near-cap end, <0.05 in the
   useful range; pinned by `TestReportSelectorParity`). Guard-review findings
   folded in: honest-ified the "no eta cap" claim (global ETA_CAP=5 still
   bounds candidates — never binds on Rev F data), added a refine same-taper
   regression test + a band-skirt assertion, moved the mid-file `__main__`
   guard to EOF. 67 tests green (casapy). **STILL REMAINING: (a) the s0
   setpoint is currently FIXED at 0.10 (baked into the pre-built curve); making
   it user-adjustable in the report needs pre-built curves at a few setpoints
   (JS can't run the engine) + a dropdown; (b) OPEN: fully remove the global
   ETA_CAP so relaxed truly reports "whatever the eta" (moot on Rev F data).**
   Design decision history below.

   Superseded design note (iterative-0.01 → threshold):
   trade).** tau=0.10; min-eta point with skirt<=tau (incl. bilinear cell
   interiors = the existing relax=False path); if none in the beam window,
   tau+=step (default 0.01, code constant) and retry up to a limit (default
   0.25, EXPOSED in the HTML report calculator). Beyond the limit:
   best-achievable-skirt flagged. Edits `envelope.py` (+curves/report thread
   the limit). **Codex design consult (8 Jul, `tmp/codex_relax.out`) — key
   finding: a literal 0.10,0.11,…,0.25 loop IS a staircase** (the 0.01
   admission grid makes the accepted cap a step function of theta → new
   report artifacts). **Recommended (pending bmason): continuous two-pass** —
   (1) strict: min-eta with skirt≤0.10, return if feasible (no relaxation);
   (2) else relax the cap to the CONTINUOUS best-achievable skirt over the
   window (not a 0.01 bucket), capped at the limit; (3) beyond limit,
   best-achievable flagged. 0.01 becomes a display rounding only, 0.25 the
   exposed hard limit. This delivers bmason's "minimal relaxation" intent
   WITHOUT the staircase. Also: `skirt_mode="threshold"` enum (not overloading
   `relax=True`); keep the old 1-for-1 trade only as `legacy_trade`; structured
   flags (`skirt_status` ∈ ok/threshold_relaxed/over_limit/no_skirt_data,
   `meets_requested_skirt` true only for skirt≤0.10). **The report calculator
   JS ranks by the OLD trade objective (`report_template.html` curveObjective
   ~L405) and MUST be rewritten to match, or report/selector diverge.**
   margin-band cell handling is a scan (not analytically exact) — new oracle
   tests needed for cap-tangency/strict↔relaxed transitions. Needs tests;
   pinned anomalies must stay fixed. **DECISION: continuous vs literal-0.01.**
3. **More parallelism in sweep + refine.** `sweep_parallel.py` already shards
   (--max-procs); raise defaults / better pack the icx node (~80 cores).
   `refine.py` is SERIAL — parallelize its per-jump point measurements (or run
   subarrays concurrently). Edits `refine.py`/`sweep_parallel.py`.
4. **Standalone portable selector function.** A function: science inputs
   (beam, freq, sensitivity, LAS, imaging?, optimize) -> ranked list (eta,
   robust/taper, integration time, antenna-hours, warnings), matching the
   web-page inputs. **bmason 8 Jul: the sensitivity part must CALL the ngECT
   python calculator live (NOT a pre-built tabulation like the web page).**
   `sa_select/sensitivity.py` already wraps it (`natural_rms`/`integration_time`
   invoke `ngVLA_sensitivity_calculator.py`), so this is already live — the
   task is a clean single entry point + **portable minimal checkout =
   `sa_select/` + `ngvla-sensitivity-calculator/` (incl. its .pkl) +
   `sa_select/data/*.csv`, needs numpy+scipy, NO CASA** + a portability test.
   Safe to build now (selection layer not used by the refine job).
   **DONE 8 Jul 2026:** the entry point already existed
   (`select_subarrays(ObservingRequest)` + `python -m sa_select` CLI, returning
   ranked candidates with eta/robust/taper/skirt/LAS/t_int/antHrs); the real
   gap was that `CurveLibrary` still defaulted to the memo-121 BOOTSTRAP table
   — **swapped the default to `revf_curves.csv`** (the long-standing TODO;
   bootstrap-replay tests pinned to bootstrap explicitly). Verified CASA-free
   end to end with the live ngECT path; added `sa_select/README.md`
   (minimal sparse-checkout + usage) and `TestPortability` (subprocess guard
   that the query path imports no CASA + a live-ngECT check). 69 tests green.
5. **Legacy/unused-code review — DONE 8 Jul 2026.** Codex produced a ranked
   removal list; bmason kept artifacts/, ngvla-taperability-pipeline/, and
   curves.names()/resolution_range() (provenance/API). Removed the safe dead
   code across v5-v8: `compareKeys`, unused `ETA_CAP`/`natural_row_measurements`
   imports, `sweep_parallel.existing_keys`, `build_points(key=)`, `make_report
   .DEFERRED` + the template's `DATA.deferred`, `sweep.py`'s legacy
   hyphen-filename fallback; and moved both test files' mid-file `__main__`
   guards to EOF (they were hiding later test classes from direct execution).
6. **Report fixes for LONG (diagnosed 8 Jul):**
   (a) **Overview x-range is a FIXED `xmin=1.5, xmax=80000` mas**
   (`report_template.html` optsCommon) — clips the fine end: 117/140 `long`
   samples and 18 main+long samples sit below 1.5 mas. Fix: lower xmin to
   cover the finest subarray (~0.2 mas) or derive from data.
   (b) **`long`'s janky/disconnected curve = spurious-shorts pathology.** Its
   bimodal baselines (spurious ~37 m shorts + multi-1000 km) leave a REAL beam
   coverage gap (e.g. ptsrc 3.7->11.6 mas, x3.1) where no taper yields an
   intermediate beam — so the curve fragments. This is the spurious-shorts
   issue deferred earlier; the LAS impact was small but the CURVE-SHAPE impact
   is large. **bmason 8 Jul: filter baselines < ~100 m where they are spurious
   — long, mid+long, spiral+mid+long, long+mid+spiral+core-outer (real-component
   b_min is >100 m there, so <100 m == LONG's spurious clusters). NOT main+long
   (core's legit 42 m baselines live there; LONG shorts "probably don't hurt").**
   Plan: per-subarray `min_uvrange_m` in config; apply `uvrange='>100m'` in the
   imaging step; reuse the existing MS (no re-sim) but RE-IMAGE those 4 — fold
   into the item-1 re-sweep. Minor caveat: eta then relative to filtered natural
   while the ngECT anchor is unfiltered natural (N_ant-based) — negligible.
   main+long etc. are fine (0 big gaps). **Refine crash fixed 8 Jul:**
   `candidates_between` did `tapers[1]` on a same-taper (robust-direction) jump
   → IndexError that killed main+long round 3 after +41 pts (rounds 1-2,
   collected); now guarded.


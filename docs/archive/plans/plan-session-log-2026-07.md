---
split_from: docs/plans/PLAN.md (lines 226-482 and 1447-1591 at commit 7f0a63f)
history: git log --follow docs/plans/PLAN.md
---
### v2 curve generation (5–6 Jul 2026, after bmason's review of v1 curves)
User feedback on v1 (all implemented):
- **No web artifacts** — bmason doesn't want Artifact publishing; produce **local HTML** under
  `curvegen/reports/` instead (memory: `no-web-artifacts`). Plots themselves were good.
- **Natural branch sampled too coarsely near native** (core jumped 0.71″→1.42″). Fix: tapers
  now start at 0.3× the robust=−2 beam so every subarray samples smoothly down to its
  untapered resolution.
- **Sculpt branch far too coarse; not finding the (robust, taper) eta-minimum** — filled
  triangles sat above filled circles, impossible if natural+taper is truly an edge of the
  searched space. Fix: full 2-D lattice, natural + robust −2…+2 step 0.4 × (0 + 14 log tapers),
  anchored per subarray by two seed points (self-calibrating), **eta ≤ 5 cap** prunes each row,
  plus a convergence prune when a briggs row lands on the natural+taper edge.
- **core+mid sculpting "went bonkers"** (false minima; tapering away the long spacings to use
  core+mid as core is not the goal — sculpt resolutions should track the higher-resolution
  component's range). **core+mid & main deferred** until the homogeneous set is solid;
  `collect.py` excludes their v1 results.
- **Current run set (homogeneous):** core-inner, core, spiral, mid, core+spiral, spiral+mid.
  Long-term: most of the memo-121 subarray list.
- **core-inner added** = memo 121 CoreInner, innermost **57** of the core's 114 antennas
  (by radius from core centroid — membership rule is our assumption; verify with Viviana).
  b_max 1.63 km; native beam 2.04″; natural skirt ≈ 0.10.
- **LAS coefficient → 0.80 for all 18-m subarrays** (bmason: memo-67 core value ~0.8, apply
  uniformly). `subarrays.csv` + builder updated; SBA stays 0.58 when added.
- **Deliverable to add:** a robust–taper-space illustration (eta map + skirt≤10% region +
  located minimum) for representative subarrays — build into the local report once v2 data
  lands. ☑ done (lattice heatmaps in the report).

### v2.1 (6 Jul 2026, second bmason review round)
- **Report mojibake** — template lacked `<meta charset="utf-8">`; local file opens defaulted
  to Latin-1. Fixed. (The artifact wrapper had been supplying it, masking the bug.)
- **Imaging-curve markers** → filled triangles on the all-SA overview (matches small-multiple
  symbol semantics).
- **Curve reduction** → sliding-window min (±5% beam tolerance on a 0.01-dex grid, the
  selector's own semantics), trimmed at **eta ≤ 5**; consecutive same-winner targets collapsed.
  Replaces disjoint bins, which let isolated (often eta>5 or v1-stray) points win single bins →
  the "popping" bmason flagged.
- **Infeasibility gaps are real and now rendered as line breaks** (res ratio > 1.35): e.g.
  **spiral+mid cannot be sculpted to skirt ≤ 10% between ~11 and ~55 mas** — negative robust
  saturates (−2…−0.8 beams identical) and best skirt bottoms out at 0.14–0.21, precisely
  memo 121's "bottom out at ~16%" phenomenon. Its imaging curve is genuinely sparse/gappy,
  not under-sampled.
- **`curvegen/refine.py`** — targeted adaptive refinement: wherever the imaging curve jumps
  > 0.25 in eta between adjacent resolutions (excluding infeasibility gaps), measure ~6
  bracketing (robust, taper) points per jump (robust ±0.2, taper ×/÷1.22, midpoints), up to 3
  rounds / 60-point budget, on top of the resumable sweep results. Core: one round, +24 pts,
  worst step 0.76 → 0.24. All 6 refined to worst steps 0.19–0.29.
- **Skirt relaxation (bmason, 6 Jul 2026): angular resolution is the PRIMARY requirement.**
  Where no (robust, taper) combo reaches skirt ≤ 0.10 at the requested resolution (e.g.
  spiral+mid ~11–55 mas, bottoming out at 0.14–0.21), do NOT exclude/leave a gap and do NOT
  distort resolution: relax the criterion to the best achievable skirt there, and FLAG it.
  Implemented in `CurveLibrary.solve(relax=True)` (default; `ObservingRequest.skirt_relax`),
  surfaced as `Candidate.warnings` (new field, non-fatal, printed as "note" lines in
  `.table()`), and in the report's imaging curves (hollow triangles + tooltip). 3 new
  regression tests (28 total).

### TACC round (6 Jul 2026, evening — resumed on Stampede3)
Environment: see `docs/ops/casaLocation.md` (modular CASA 6.7.5 venv in `$WORK` + `casapy`
wrapper; the previously-noted monolithic install is broken). 28/28 tests pass.
- **Homogeneous set refreshed:** all 6 MSes re-simulated; relaxation-aware
  `refine.py` re-run per the handoff plan (core-inner/core/spiral/mid converged at
  worst in-band eta step ≤ 0.24; core+spiral & spiral+mid refined their relaxed
  segments).
- **Heterogeneous rework implemented (core+mid, main):** per bmason's directive
  (sculpt resolutions track the higher-resolution component) + a Codex design
  review: (a) **beam cap** — points with beam > coarsest component's native beam
  (core 0.710″ @30 GHz) get `status="capped"` (measured but never collected — the
  v1 false-minima leak), rows prune after **two consecutive** capped points
  (beam-fit-discontinuity guard); (b) `N_TAPERS_HETERO = 18` (2.5-dex taper range);
  (c) `refine.py` also chases resolution jumps (not just eta jumps) for these two
  (plateau transitions can hide there); (d) v1 `core_mid.csv` archived to
  `results/v1-attic/`. Full lattices (≤228 pts, ~2.3 min/pt at imsize 15000)
  running. TODO when trusted: drop them from `DEFERRED` in `collect.py` +
  `make_report.py`.

### Feature tranche 1 (10-11 Jul 2026) — commits v11-v13, 93 tests green

From bmason's features.txt: v11 (67606c3) PSF radial-profile capture in the
sweep (results/profiles/<sa>.jsonl; future sweeps collect profiles free —
feeds feature 3); v12 (7afac69) ngECT curve export
(`casapy -m sa_select.export_ngect` -> sa_select/data/
ngect_subarray_data.json; geometric-mean beam convention — NOT Stroh's
sqrt(2) quadrature; PCHIP-PPoly splines, <1% vs engine, QA PNGs);
v13 (a40d4b1) report skirt-setpoint dropdown (pre-tabulated s0 = 0.05/0.10/
0.15/0.20; heatmap rings pinned to 0.10). The (rev, sim_mode) schema axis
(tranche component D) was DEFERRED by bmason — it is the prerequisite for
the RevD/snapshot campaigns (docs/archive/plans/campaign_proposal_revd_snapshot.md).  **Now
IMPLEMENTED (12 Jul 2026) together with the Rev D + snapshot campaign
machinery — see the dedicated section below.**  v13's missing codex review
was re-run post-hoc on the committed diff (11 Jul; findings adjudicated
below/in git).

**ASK BMASON next iteration:**
1. Eyeball verdict on the s0 dropdown UX (revf-curves.html) incl. relaxed
   tooltips at s0 != 10%, and on the export QA PNGs
   (curvegen/reports/ngect-export-qa/). (Deferred 11 Jul by bmason.)
2. Stroh outreach (bmason agrees, 11 Jul): the exported "imaging" splines
   for the four long-baseline combos use a labeled relaxed fallback
   (`selection_policy` field) because they have NO strict skirt<=0.10
   points — settle with Stroh/ngECT whether that is acceptable to the
   consumer, and share the sqrt(2)-convention + spiral-spline findings
   (docs/architecture/mstroh_comparison.md).

### (rev, sim_mode) axis + Rev D / snapshot campaign machinery (12 Jul 2026)

Implements features 5 (multiple config revisions) + 6 (snapshot sim) and the
deferred tranche component D that underpins them.  Codex design-consulted then
diff-reviewed (tmp/codex_revd_snapshot_design.md, tmp/codex_review*).  **All
code that does not depend on the not-yet-run sweeps is done; the sbatch is
staged for bmason to submit.** 96 tests green; default (revF, track) verified
byte-identical (report HTML + collect output diffed old-vs-new).

**The axis.** `curvegen/config.py` reads `NGVLA_REV` (revF|revD) and
`NGVLA_SIM_MODE` (track|snapshot) from the environment at import.  The DEFAULT
(revF, track) reproduces the old hardcoded config byte-for-byte (same dicts,
same `curvegen/{configs,results,ms,work}` paths).  Any other combo:
- component .cfg map + dir switch per rev (revD "long" = `lba.cfg`; core/spiral/
  mid map name-for-name); `SUBARRAYS`/`IMSIZE`/`MIN_UVRANGE_M` become per-rev.
- `config_suffix()` = `-<rev>_<sim_mode>`; `CFG_DIR`/`RESULTS_DIR` get it in the
  repo, `MS_DIR`/`WORK_DIR` go to `$NGVLA_SCRATCH/<kind><suffix>` (big/scratch).
- snapshot = a single 60 s integration centered on transit, `("-30s","30s")`;
  `simulate.py` asserts exactly one dump lands (verified: 1).
- `sa_select/data/config_registry.csv` (`rev,sim_mode,subarrays_csv,samples_csv`)
  is the source of truth; `CurveLibrary.for_config(rev,sim_mode)`,
  `collect.py`, and `make_report.py --rev/--sim-mode` all route through it.
  Rev D metadata is `subarrays_revd.csv`; revF/snapshot reuses Rev F geometry
  (`subarrays_revf_snapshot.csv`, caps blanked).  Each combo gets its OWN curve
  CSV + HTML report (`revd-track-curves.html`), so nothing collides.

**Beam caps two-step.** Default caps stay hardcoded in config.  For any other
combo the native beams differ, so caps are MEASURED from that combo's own
natural seeds: `CAP_REFERENCE[rev]` maps each heterogeneous subarray to the
offered subarray whose natural beam is its cap (revD: main←core, mid+long←mid,
main+long←main).  `fill_beam_caps.py` (run after the seed pass) writes those
caps INTO the metadata CSV; `config._load_caps_from_metadata()` reads them back
at import for the full grid.  It FAILS CLOSED if a reference seed is missing —
prep also does NOT regenerate the metadata CSV, so a resubmit never blanks the
caps.  (Rev D `lba` has the SAME spurious-short pathology as Rev F Long —
baselines 36-174 m then a jump to 131 km — so the existing 178 m cut applies to
long/mid+long; main+long is unfiltered, as in Rev F.)

**Campaign submission (bmason runs from a login node).** A 3-stage Slurm
pipeline wired by `curvegen/submit_campaign.sh <rev> <sim_mode> [--time] [--prep-only]`:
1. `campaign_prep.sbatch` — build cfgs, `sweep.py --seeds-only` for every
   cap-reference subarray (`campaign_tasks.py seeds`), then `fill_beam_caps`.
   Seeds-only (NOT a pilot): the two seeds are cap/lattice-invariant, so no
   pre-cap row can strand or mis-cap a heterogeneous subarray (codex review).
   QA gate: eyeball seed beams / imsize / cell in the log (or `--prep-only`).
2. `campaign_sweep.sbatch` — Slurm job ARRAY; `campaign_tasks.py groups` puts
   each long-baseline (>2600 km) subarray on its OWN node and the rest in one
   grouped task (bmason's node rule).  Each task: sweep_parallel → fill_grid →
   refine.  `--dependency=afterok` on prep.
3. `campaign_collect.sbatch` — collect → routed curve CSV + own HTML report;
   afterok on the array.
Env (`NGVLA_REV/SIM_MODE/SCRATCH`) is `--export`ed to EVERY stage (a Slurm
dependency does not inherit it).  Commands:
`bash curvegen/submit_campaign.sh revF snapshot --time 24:00:00`  (campaign 1),
`bash curvegen/submit_campaign.sh revD track --time 48:00:00`     (campaign 2).

**Known cosmetic limitation:** a non-default report's `profile`/`qa` diagnostic
blocks still show the Rev F reference values (the curves/heatmaps/LAS/sens ARE
combo-correct); the output filename disambiguates.  Rev D / snapshot (one more
registry row + rerun) is a follow-on if wanted after 1 + 2.

### Report-glitch fixes (9-10 Jul 2026 — post-recompute)

bmason flagged three glitches in the 9 Jul 00:15 report (the recompute job
3287698's final output).  All three diagnosed and fixed; 82 tests green;
report regenerated (`curvegen/reports/revf-curves.html`).

1. **Imaging-curve jumps (spiral+mid ~7.7/44 mas, core+spiral ~260 mas) =
   stale wrong-cell data**, not engine error: 68 v1-era sculpt points imaged
   with the native cell instead of the adaptive rule (see the new §13
   gotcha).  Repaired via `curvegen/repair_stale_cells.py` (all 68
   re-measured under the v2 convention, 0 failed; originals archived in
   `results/attic-badcell/`).  spiral+mid imaging now has ZERO adjacent-eta
   steps > 0.12; the survivors elsewhere are small (<= 0.15 in the eta <= 3
   operating range, e.g. core+spiral +0.12 @ ~800 mas) or sit in the
   eta > 4 far-coarse display fringe.  `collect.py` hard-fails on stale-cell
   rows now.
2. **Point-source coarse-end cliff (main+long 20.1->20.6 mas eta 1.18->2.25,
   spiral+mid+long alike) = beam-cap censoring**: the log taper grid's last
   sub-cap point sat ~20% short of the cap, so the cheap natural family
   was unmeasured there and the envelope fell onto an expensive family.
   **SEMANTICS CHANGE (needs bmason sign-off — flagged):** status="capped"
   sweep rows are now COLLECTED as interpolation anchors
   (`sample_status=capped_anchor` column in revf_curves.csv;
   `beam_cap_arcsec_30ghz` column in subarrays.csv), the engine gained
   `solve(..., max_res=)` / `solve_interval` / `curve(..., max_res=)`, and
   the report/selector clip offered answers at the cap (cap-specific
   infeasibility message; JS calculator matches).  Curves now ride the
   natural family to exactly the cap (main+long @20.6 mas: eta 1.05, was
   2.25).  Offered range only shrinks (never beyond cap); memo-121
   bootstrap-replay test updated accordingly (main's Rev-D-era 0.798"
   natural sample is now correctly cap-refused vs Rev F core's 0.710").
   Codex design-consulted (tmp/codex/tasks/, 9 Jul) both before and after.
3. **Heatmap censored cells = mixed-grid axes + an over-broad eta trim**:
   axes were "tapers in >= 6 samples" x "all distinct robusts" (a union of
   v1/v2/refine grids -> mostly-blank lattices), and make_report dropped
   eta > 5 samples before building heatmaps.  `build_heatmap` rebuilt on
   the canonical v2 lattice (`config.grid_rows` from the seed beams;
   natural + ROBUST_LIST rows), untrimmed eta (color clamps at 5, tooltip
   true value), per-status rendering (ok / capped-anchor hatch / skipped /
   failed), off-lattice-anchor footnotes.  **All 14 heatmaps are now fully
   dense — 2458 ok + 398 capped cells, 0 skipped/failed/missing — no
   further sweeps needed.**  (Report-side rework built by codex to Claude's
   spec, diff reviewed; codex's two review findings — max_res not threaded
   through curve()'s solves, and the un-regenerated curve table — both
   addressed.)

   Residual known steps (small, judged acceptable): fine-end steep
   segments at the uniform-weighting limit (real physics, marker-anchored,
   e.g. main+long eta 2.76->2.38 across a 2%-wide res span at 0.5 mas);
   eta>4 far-coarse lattice granularity (core-inner/mid/core);
   core+spiral +0.12 @ ~800 mas (genuine strict-strict lattice
   transition).  Next-level smoothing would need denser robust sampling
   near -2 / more coarse-end sculpt tapers.

4. **v10 cosmetics pass (10 Jul, bugs.txt):** four rendering-only fixes,
   built by codex to Claude's spec (tmp/codex_cosmetics_spec.md), diff
   reviewed line-by-line.  (a) marker density — `build_curve`'s run key
   dropped `c.robust` (family level `(weighting, relaxed, traded)`; on the
   robust branch robust drifts continuously so every grid point was marked
   and the halo strokes erased neighbours) plus a 7-px screen-space
   thinning backstop in `curveChart` that never drops first/last or
   relaxed-transition markers; all series now 12–21% marked (was ~100% in
   dense runs), curve res/eta DATA byte-identical.  (b) LAS labels:
   width-aware level allocation instead of identical-mas stacking.
   (c) series end labels: shared right gutter (M.r 84→188) at common x,
   >=13 px vertical separation clamped to the plot band, dashed
   curve-coloured leader lines.  (d) heatmap legend rebuilt as data-driven
   mini-SVG swatches drawn by the same cell primitives (capped-anchor
   hatch now contrast-flips at eta 2.5 like the skirt dot; null cells
   dashed; capped/skipped/failed/not-measured entries only shown when the
   status occurs in the data).  82 tests green; validate.py output
   byte-identical pre/post.

### UPDATE (13 Jul 2026) — 12 Jul sweep-campaign failure diagnosed + fixed; relaunch ready

The 12 Jul campaigns (revF/snapshot 3299896, revD/track 3299900) had prep
COMPLETE but every sweep array task FAIL in ~3 s.  Root cause:
`campaign_sweep.sbatch` assigned to `GROUPS`, a bash special variable whose
assignment fails with status 1 — the `|| exit 1` guard fired on the
*assignment*, not on `campaign_tasks.py` (which was fine).  Renamed to
`SA_GROUPS`.  No sweep work was lost; both preps' seeds + measured beam caps
survive on disk and in `subarrays_revd.csv` / `subarrays_revf_snapshot.csv`
(uncommitted — commit them).  revD/snapshot additionally lacked supporting
metadata: added the `config_registry.csv` row and generated
`sa_select/data/subarrays_revd_snapshot.csv` (`build_subarrays_csv.py`; caps
blank until its own prep runs — sweep preflight fails closed, verified).
All 4 registry combos now pass `campaign_tasks.py narray/groups/seeds`.
Codex (gpt-5.5 xhigh) reviewed the fixes: confirmed both, flagged committing
the untracked metadata CSV with the registry row as required for a clean
checkout.  Relaunch commands: `docs/ops/RUN_CAMPAIGNS.md` (step 0 cancels the two
orphaned DependencyNeverSatisfied collect jobs 3299897/3299901).  Memo
updated the same day (scope now 14 subarrays, full-grid + uv-filter + campaign
sections, real figures replacing the three placeholders).

### Recompute campaign staged (8 Jul 2026 — items 1 + 6a + 3, CODE DONE)
Codex-consulted design (`tmp/codex_sweep.out`). CODE (committed, awaiting a
re-sweep to regenerate DATA):
- **Item 1 (full grid):** `sweep.py run()` no longer eta-cap- or convergence-
  prunes; every (robust, taper) cell is measured. Beam-cap kept for the
  heterogeneous composites (physics exclusion). `natural_row_measurements` and
  the `ETA_CAP` import dropped from sweep.py; docstrings/config updated.
- **Item 6a (spurious shorts):** `config.MIN_UVRANGE_M` = {long, mid+long,
  spiral+mid+long, long+mid+spiral+core-outer} → **178 m** (LONG's clusters run
  37–176 m; the real long baselines are at 515 km; core-outer's legit b_min is
  179 m — so 178 m is the one cut that removes LONG's 30 spurious baselines
  everywhere AND keeps core-outer). `sweep.run_point` passes `uvrange='>178m'`
  to tclean (incl. the natural seed → eta consistent). NOT main+long. TODO on
  re-collect: update subarrays.csv b_min (long 515 km, mid+long 10.1 km,
  spiral+mid+long 811 m, long+mid+spiral+core-outer 179 m) + note the ngECT
  anchor is ~3.6% optimistic for `long` (30/435 baselines cut; negligible for
  combos).
- **Item 3 (parallelism):** `refine_parallel.py` runs subarrays concurrently
  (own scratch cwd + CSV); sweep uses `--max-procs 10`. (Codex's further win —
  sharding the natural row with the Briggs rows now that convergence pruning is
  gone — deferred.)
- **Campaign:** `curvegen/recompute.sbatch` (bmason submits from a login node):
  `prep_recompute.py` (archives the 4 uvrange CSVs to results/attic-uvrange/,
  strips eta/convergence `skipped` rows from the rest so the full grid
  re-measures them — dry-checked: 21–48 rows/subarray) → full-grid
  sweep_parallel+fill of all 14 offered → refine_parallel → collect →
  make_report. Resumable; prep idempotent. 48 h walltime.
**[FUTURE improvement — multi-node campaign (bmason 8 Jul 2026)]** The
recompute is single-node (`-N 1`, subarrays looped sequentially).  Subarrays
are embarrassingly parallel (own MS/CSV/scratch cwd; only collect+report is
shared), so a Slurm **job array** would parallelize the expensive ones.
**bmason's rule (8 Jul): give any subarray with baselines longer than
~2x1300 km (2600 km) its OWN node; do everything else on a single node.**
That set = the LONG-containing subarrays (Long b_max ~8686 km; the next
longest, mid/main, is ~1273 km < 2600 km): **long, mid+long, spiral+mid+long,
main+long, long+mid+spiral+core-outer** → 5 own-node tasks; the other 9 share
one node.  Design: a job array (5 heavy tasks + 1 grouped task), `prep_recompute`
as a single pre-job, `collect`+`make_report` as a post-job gated with
`--dependency=afterok`.  No sweep-code changes needed (calls the existing
scripts).  **Wrinkle to solve first:** `prep_recompute.py` is destructive if
re-run AFTER a successful recompute — it would re-archive the freshly re-swept
uvrange CSVs (they're present again) back to attic.  So the array flow needs a
prep that runs exactly once on the ORIGINAL data (or detects
already-filtered/full-grid CSVs and skips).  **Deferred (8 Jul): the single-node
recompute is already in flight, so a multi-node version is a NEXT-recompute
tool and can't be validated now without colliding with the running job; build
+ validate it before the next full recompute.**  [Recompute job 3287698
LAUNCHED by bmason 8 Jul; QA when it lands.]

7. **[DONE 12 Jul 2026]** Selectable config revisions (revD, revF) for curve
   generation, and per-rev snapshot vs 4-h-track sims — implemented as the
   (rev, sim_mode) env axis + registry (see the dedicated 12 Jul section
   above).  Each combo gets its own subarrays/curve CSVs + HTML report keyed
   through `config_registry.csv`; additive, default byte-identical.  NOT yet
   wired into the calculator/selector CLI as a user-facing `--rev` flag (the
   selector still defaults to revF via `CurveLibrary()`); `for_config` exists
   for when a second dataset is swept and we want to expose it.

**Context for another model/agent**: CLAUDE.md (repo guide) → this PLAN →
`docs/postmortems/2026-07-06-curve-anomaly.md` (why the engine is what it is) →
`docs/architecture/mstroh_comparison.md` (external validation) → `docs/ops/casaLocation.md` (TACC env:
casapy wrapper, quota/TempLattice gotchas) → `memo/` (the write-up) →
`codex-bridge/` + `tmp/codex/tasks/` (second-model consult/build transcripts).

### Curve-anomaly post-mortem + shared engine (6 Jul 2026, TACC evening)
bmason flagged pop-ups/drop-outs in both curve types (e.g. spiral+mid ptsrc
17.8 mas; mid imaging 8.08 mas; core+spiral imaging 103–118 mas sawtooth).
Post-mortem (`docs/postmortems/2026-07-06-curve-anomaly.md`): NOT noise — hard ±5% window +
hard skirt threshold + window-local relaxation applied to a quantized lattice
(mechanisms M1–M3, M3b, M4a–d; census: 14 anomalies, all composite configs;
codex critique folded in). **Fix implemented (bmason-approved):**
`sa_select/envelope.py` — shared piecewise row-interpolation engine
(non-extrapolating, taper-adjacent segments only, one eta-cap policy,
−0.0/dup hygiene, continuous best-achievable-skirt relaxation, interpolated
answers flagged with measured anchors) now drives BOTH `CurveLibrary.solve()`
and `make_report.build_curve` (dense 0.01-dex grid curves; markers gated).
All named anomalies fixed (e.g. 17.8 mas: eta 1.54→1.07; 11.7 mas drop-out
1.00→1.50-relaxed; 114 mas sawtooth → strict 1.50 at skirt 0.100 exactly).
43 tests green (15 new, incl. real-data regressions). Known residual:
robust-direction staircase at the fine end (~0.14 steps) — second-wave 2-D
interpolation / contour sampling if wanted. collect.py: skips in-flight
parallel shards; dedupes + canonicalizes robust on output.

### Handoff state (6 Jul 2026 — moving to a bigger platform for the next round)
Everything needed to resume is committed; see **README.md** for environment + commands.
- **Works now:** `sa_select` end-to-end on bootstrap data (28 tests green); `curvegen`
  v2.1 curves for the homogeneous set {core-inner, core, spiral, mid, core+spiral,
  spiral+mid} — 2-D lattice + refinement, skirt-relaxed imaging curves, local HTML report.
- **Not in git (regenerable):** simulated MSes, tclean work dirs, `curvegen/reports/`.
  `sweep.py <sa>` re-simulates and skips all recorded points — cheap to rebuild anywhere.
- **Final curve state:** 1299 samples. Imaging curves: strict segments smooth (max eta step
  0.24–0.31); **relaxed segments** (best-achievable skirt, e.g. 31/66 pts for core+spiral,
  55/96 for spiral+mid) still have ~0.5 steps because `refine.py` ran before relaxation
  landed. **First cheap task on the new platform:** re-run `refine.py` for all 6 (it now
  imports the relaxed `build_curve`, so it will target those segments), then `collect.py` +
  `make_report.py`.
- **Next round (more compute):** (1) heterogeneous subarrays core+mid & main — sculpt targets
  must track the higher-resolution component (don't taper away the long spacings); imsize
  15000 makes these hours-per-lattice on a laptop; (2) extend toward the full memo-121
  subarray list (incl. Long — remember spurious-shorts filtering — and SBA, D=6 m, no taper);
  (3) swap `sa_select`'s default data from bootstrap to Rev F once coverage suffices;
  (4) LaTeX memo (T7); (5) denser noise-free eta? (open question: single noise realization).

### Implementation decisions (5 Jul 2026, M2/T5 build)
- **`curvegen/`** at repo root (CASA-dependent, kept out of `sa_select/` so query time stays
  CASA-free): `config.py` (grids/presets — the only file to tweak), `build_configs.py`,
  `simulate.py`, `measure.py`, `sweep.py` (resumable driver), `collect.py` (→
  `sa_select/data/revf_curves.csv`, same schema as bootstrap).
- Runs under CASA's **python3 directly via `casatools`/`casatasks`** — no `casa -c`, no cluster.
  The old TORQUE submission layer (`create_images.py` + `casa_script_wrapper.py`) is replaced by
  a sequential local loop. **Sims DO work on macOS** (CASA 6.7) — the 2023 note in notes.txt is
  obsolete; the crash I hit was a `readantenna` unpacking bug (returns 7 or 8 items by version;
  feeding wrong types to `sm.setconfig` = hard C++ abort, exit 134).
- Sweep is **resumable**: done points are read from `results/<sa>.csv` and skipped; failed
  points re-run; grids in `config.py` can be extended and only new points execute.
- Sim setup identical to Viviana's (30 GHz, 4 h HA track, dec +24, 60 s, 1 chan, 1 Jy noise)
  for comparability. Grid: natural×13 tapers + robust −2…2×0.4 + sculpt (4 robusts × 4 tapers)
  ≈ 40 points/subarray. eta = dirty-image rms ratio to untapered natural (memo 55/72 method).
- Core sweep: ~6.5 s/point at imsize 4096 (M-series laptop). Core validation vs memo-121:
  natural skirt 0.116 vs 0.12; robust-branch skirt crosses 0.10 at robust ≈ 1.2 vs their
  sculpted points at robust 0.85–1.06 (pre-Rev-F configs, so ~agreement is expected).
  Rev F core native beam 0.710″ vs 0.719″ (memo-121 era) at 30 GHz.

### Implementation decisions (5 Jul 2026, M1 build)
- Package: **`sa_select/`** at repo root — `schema.py` (dataclasses + CSV column docs in the
  module docstring), `curves.py` (`CurveLibrary`), `heuristics.py`, `selector.py`,
  `sensitivity.py` (T4), `data/` (T3 output). Units: arcsec / GHz / Jy per beam / K / hours / m.
- **Store raw curve *samples***, not pre-built curves: the point-source vs imaging split is
  applied at query time (imaging = samples with skirt ≤ threshold). Honest with sparse bootstrap
  data, and the dense Track-2 grids drop into the same schema.
- v1 solve picks the best tabulated sample inside the beam-tolerance window (no interpolation);
  revisit once dense Track-2 grids exist.
- **Heuristics are pluggable**: `(feasible_candidates, request) -> ranked list`, built-ins
  `antenna_hours` & `integration_time` in a registry; any callable accepted by
  `select_subarrays`. With no sensitivity goal they rank by relative costs
  t ∝ eta²/(N(N−1)), antHrs ∝ eta²/(N−1).
- Samples without a skirt measurement are excluded from imaging queries (can't verify the
  constraint) but usable for point-source ones.

Rationale: the two genuinely hard, correctness-critical pieces are the selection
algorithm/scaling (T2) and the sculpting/PSF physics in the pipeline (T5) → top-tier model,
high effort. Plumbing/IO/CLI → mid model, medium effort.

---


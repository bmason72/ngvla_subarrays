# NGVLA Subarray-Selection Tool — Plan

Living planning doc so work can be resumed by any coding agent. Keep it updated; log gotchas
at the bottom. See `CLAUDE.md` for the authoritative task statement and repo map.

Status legend: ☐ not started · ◐ in progress · ☑ done · ⚠ blocked/needs decision

**Plan reviewed against the raw materials 5 Jul 2026** — Rev F configs, memo-121 CSVs,
taperability pipeline, and sensitivity-calculator pkl all spot-checked; findings folded into
§6, §7, §12, §13. No coding started yet (M1 is next).

---

## 1. Objective

A stand-alone, astronomer-readable Python module that, given an observing request, returns a
**ranked list of viable Rev F subarrays** with the `tclean` parameters (Briggs `robust` and/or
UV outer `taper`), the resulting sensitivity-loss (`eta`), antenna hours, and — bonus — an
integration time, chosen to hit the requested beam within a tolerance while minimizing either
integration time or antenna-hours.

### Inputs
- `resolution` (target beam FWHM, e.g. mas) — the angular resolution (AR) goal.
- `frequency` (GHz).
- `sensitivity` goal (point-source Jy/beam **or** brightness-temp K — must handle both; a K goal
  changes how eta trades against resolution).
- `LAS` (largest angular scale required).
- `imaging_project` (bool): imaging ⇒ apply PSF-skirt (sculpting) constraint; point-source
  detection ⇒ skirt unconstrained, only beam size must be met.
- `beam_margin` (default 0.05): fractional tolerance on the achieved beam vs. requested.
- `skirt_threshold` (default 0.10): max allowed PSF value at radius = 1 FWHM (imaging only).
- `optimize` ∈ {`integration_time`, `antenna_hours`}: the ranking objective.

**Design requirement (added 5 Jul 2026, user):** the selection/ranking heuristic must be
**pluggable** — a small strategy interface (feasible candidates in → ranked list out) so the
heuristic can be tweaked or swapped without touching the engine. The two `optimize` values are
just the built-in strategies.

### Output
A Python object (list of dataclasses / DataFrame rows), one per viable subarray, with:
subarray name, N_ant, chosen `robust`, `taper`, achieved beam (bmaj/bmin), `eta`, PSF skirt
level, LAS (does it satisfy the request?), antenna-hours, integration time, and diagnostics
(why an SA was excluded). Ranked by the chosen objective.

### Deliverables
1. The selection module (importable + small CLI).
2. Pre-tabulated curve data (see §5) checked into the repo.
3. A LaTeX memo documenting the algorithm and approach (must compile cleanly).
4. This plan, kept current.

---

## 2. Key definitions (grounded in the memos)

- **eta / inefficiency factor (`eta_w`):** image rms at a given resolution ÷ natural-weight rms.
  Natural weighting = 1.0 (the sensitivity optimum). Computed in
  `ngvla-taperability-pipeline/analyze_images.py` as `sigma / sigma_natural`.
- **Taperability curve:** eta vs. resolution. To the **right** of native (coarser): natural +
  UV taper. To the **left** (finer): Briggs robust (± taper). (memos 55, 72, 76.)
- **PSF skirt / "level" / shoulder:** the PSF value at a radius of **one FWHM** from the peak.
  Sculpting target default **≤ 10%** (memo 121, footnote: "a skirt which raises the PSF to a
  level of 10% at a radius of one FWHM"). **This is exactly the `level_*` columns in the
  `memo121artifacts/*Cln.csv` files** — natural weighting gives a large skirt (e.g. 71%); robust
  weighting sculpts it down to ~10% at the cost of higher eta (e.g. 3.47). memo 65 grids robust
  (−2…+2) × taper to map skirt & eta at fixed resolution.
- **Sculptability curve:** skirt level (and eta) vs. robust at fixed target resolution
  (memo 121 Fig 4). The imaging curve is the taperability curve *subject to* skirt ≤ threshold.
- **LAS (memo 67):** measured from disk sims; LAS ≈ 0.6 λ/b_min (SBA, 0.58) up to ~0.85 λ/b_min
  (core). Scales ∝ λ (i.e. ∝ 1/frequency). Assume independent of taper/robust (verify later).
- **Two curves per subarray:**
  - *point-source curve*: min-eta path to each resolution, skirt ignored.
  - *imaging curve*: min-eta path to each resolution s.t. skirt ≤ threshold.

---

## 3. Solution architecture (two phases)

### Phase A — Offline tabulation (expensive, done once per config set)
For each subarray at reference frequency **30 GHz**, tabulate, over a curated grid of
(robust, taper): achieved beam (bmaj, bmin), eta, and PSF skirt level. From this derive:
- point-source curve: eta(resolution)
- imaging curve: eta(resolution | skirt ≤ threshold), plus the (robust, taper) that achieves it
- the subarray's LAS and N_ant (and antenna list, for antenna-hours).

Persist as a compact, versioned data file (CSV/parquet/pkl) — **the tool must not require CASA
at query time.**

### Phase B — Online selection (cheap, pure Python)
Given a request: scale each subarray's reference curve to the requested frequency, filter by
achievable beam (within margin) and LAS, pick the imaging/point-source curve as appropriate,
read off eta + (robust, taper), compute antenna-hours and — via the sensitivity calculator —
integration time to hit the sensitivity goal, then rank by the chosen objective.

---

## 4. Frequency scaling

- Resolution scales ∝ λ ∝ 1/f: `res(f) = res_30 * (30/f)`. So a curve tabulated at 30 GHz maps
  to the requested f by scaling the resolution axis; **eta is assumed invariant** under this
  scaling (curve shape fixed vs. resolution-in-beams). Verify the invariance assumption for a
  couple of subarrays (open question — continuum fractional-bandwidth effects, see notes.txt).
- LAS scales ∝ λ ∝ 1/f likewise.
- Caveat from `notes.txt`: for continuum SGs the curve may depend on fractional bandwidth (uv
  filling). Flag as a known limitation for v1; investigate later.

---

## 5. Curve data: bootstrap then regenerate

**Strategy: two-track to get a working tool fast, then make it Rev F-accurate.**

- **Track 1 (bootstrap, no CASA):** Build the data model and the whole Phase-B selection engine
  off the **existing `memo121artifacts/*Cln.csv`** data (they already contain resolution, eta,
  skirt `level`, robust, taper, N_ant per case). This lets the algorithm, ranking, LAS filter,
  and sensitivity-calculator integration be built and tested immediately. ⚠ These CSVs are
  per-*case*, not clean per-*subarray* curves, and are likely Rev C/D/E-era — treat as a stand-in.
- **Track 2 (authoritative, CASA):** Generate proper point-source + imaging curves for the Rev F
  subarray set by adapting `ngvla-taperability-pipeline/` (which already does the sim + tclean +
  eta measurement) and **adding a PSF-skirt measurement** (the missing "sculpting" piece).

### Rev F subarray set list (DECIDED for v1)
**v1 scope = all 7 non-empty subsets of {Core, Spiral, Mid}.** SBA and Long are **deferred**
(we will come back for them; they may surface relevant issues — e.g. Long's spurious short
baselines, SBA's no-taper/D=6m handling).

The three components are **disjoint** (Core 114, Spiral 54, Mid 46 antennas; distinct station
prefixes `cor`/`spa`/`mda`; 114+54+46 = 214), so subarrays are formed by simply concatenating
the component `.cfg` files. `RevF_Main_xyz.cfg` (214) == Core+Spiral+Mid.

| Subarray | Components | N_ant |
|----------|-----------|-------|
| Core | Core | 114 |
| Spiral | Spiral | 54 |
| Mid | Mid | 46 |
| Core+Spiral | Core, Spiral | 168 |
| Core+Mid | Core, Mid | 160 |
| Spiral+Mid | Spiral, Mid | 100 |
| Main | Core, Spiral, Mid | 214 |

Note: Spiral-only, Mid-only, and Spiral+Mid (no core) are unusual for imaging (central uv hole)
and may behave oddly — keep them but flag/QA. Long-term the tool will cover essentially all
subarrays incl. SBA and Long.

**Ultimately we want all subarrays** — this is just the v1 starting set.

---

## 6. Sculpting: the piece the pipeline is missing

Add to the imaging step a measurement of the PSF value at radius = 1 FWHM (azimuthally
averaged, or the memo-121/65 convention — verify which). Good news (verified 5 Jul 2026):
`analyze_images.py` already extracts NS/EW PSF cuts (`get_psf_cuts`, line ~110) for plotting —
the skirt measurement can build directly on that, and `create_images.py` already sweeps
robust −2…1.6 (10 steps) plus a natural+taper branch. T5 is an extension, not a rewrite
(modulo the numpy/CASA modernization noted in the gotchas). Then for each target resolution the
imaging curve keeps the min-eta (robust, taper) combo whose skirt ≤ threshold. If no combo meets
the threshold at a resolution, record the best achievable skirt (memo 121 notes some cases can't
reach 10% — e.g. bottom out at ~16%) so the tool can report "imaging-infeasible" honestly.

---

## 7. Sensitivity-calculator integration (bonus → do it)

`ngvla-sensitivity-calculator/ngVLA_sensitivity_calculator.py`: `calculate_sensitivity(subarray,
freq, theta, t_obs, delta_v, ...)` and `sigma_ps_fn(...)`. Given the sensitivity goal and the
chosen eta, invert for the integration time to reach that goal at the achieved resolution.
Antenna-hours = integration_time × N_ant. Handle the SBA special case (D=6 m, no taper) and the
Jy/beam-vs-K distinction (K uses brightness temperature). The calculator's subarray names must be
mapped to our subarray set.

**Verified (5 Jul 2026):** `subarray_data.pkl` supports exactly
`{sba, core, spiral, mid, long, main, main+long, spiral+mid, spiral+core, mid+long}` with N_ant
values that **match Rev F** (114/54/46/30/19; main 214; main+long 244) — so the calculator looks
Rev F-consistent, at least in antenna counts (vintage of its eta_w(theta) splines TBD).
**Gap: `core+mid` (160 ants) is missing** from the pkl even though it's in our v1 set.

**Recommended integration approach:** use the calculator only for the *natural-weighting*
point-source rms (call at the subarray's native resolution so its internal eta_w = 1), then apply
**our own eta** from our curves. This decouples us from its spline entirely and means a `core+mid`
entry only needs N_ant/b_min/b_max (computable from the `.cfg`s) in a local pkl copy — no spline
required. Verify by cross-checking one or two cases against the calculator's own eta_w path.

---

## 8. Selection algorithm (Phase B detail)

1. For each subarray: scale reference curve → requested f.
2. Feasibility filters: (a) requested beam achievable within `beam_margin`; (b) `LAS_sa ≥ LAS_req`
   (b_min short enough). Record reasons for any exclusion.
3. Pick curve: imaging (skirt-constrained) if `imaging_project` else point-source.
4. Read off eta and (robust, taper) at the target resolution.
5. Integration time from sensitivity calculator; antenna-hours = t_int × N_ant.
6. Rank by `optimize` objective (min integration time OR min antenna-hours).
7. Return ranked list with full metadata.

---

## 9. Robustness & housekeeping (Phase A)

- Curate (robust, taper) grids per subarray up front to keep PSF count tractable (memo 65 used
  robust −2…+2 step 0.4; taper log-spaced per array scale — see `run_all.py` TA_list presets).
- Wrap each tclean/PSF job so failures are caught, logged, and post-mortem-able; don't abort the
  whole sweep on one bad PSF.
- Delete scratch tclean outputs safely (pipeline already removes `.pb/.sumwt/.model/.residual`);
  keep only what the curve needs. Watch disk: Main/Main+Long need large imsize (15000–25000 px).

---

## 10. Task breakdown, with model/effort recommendations

Per CLAUDE.md: recommend an Anthropic and an OpenAI model + effort for each. "Effort" =
reasoning effort. Bias to capability, don't waste tokens. (Model names per Jan 2026 knowledge;
adjust to whatever is current.)

| # | Task | Anthropic | OpenAI | Effort | Status |
|---|------|-----------|--------|--------|--------|
| T1 | Data model + curve schema (dataclasses/DataFrame), loader | Sonnet 5 | GPT-5-mini | medium | ☑ `sa_select/schema.py`, `curves.py` |
| T2 | Phase-B selection engine + freq scaling + LAS filter + ranking | **Opus 4.8** | GPT-5 (high) | high | ☑ `selector.py`, `heuristics.py` (smoke-tested on synthetic data; validate on real data) |
| T3 | Bootstrap curves from `memo121artifacts/*Cln.csv` (Track 1) | Sonnet 5 | GPT-5 | medium | ☑ `data/{subarrays,bootstrap_curves}.csv` + builder (188 samples; mid & core+mid have none) |
| T4 | Sensitivity-calculator integration → integration time / ant-hrs | Sonnet 5 | GPT-5 | medium–high | ☑ `sensitivity.py` (self-tested; see gotchas §13) |
| T5 | Adapt taperability pipeline + **add PSF-skirt measurement** (Track 2) | **Opus 4.8** | GPT-5 (high) | high | ☑ `curvegen/` (core validated vs memo-121) |
| T6 | Run Rev F curve generation under CASA; QA the curves | Sonnet 5 | GPT-5 | medium (long-running) | ◐ homogeneous set ☑ v2 (6 SAs, 1008 pts, 0 failed, envelope-consistency PASS); core+mid & main deferred |
| T7 | LaTeX memo (algorithm + approach) | Opus 4.8 | GPT-5 | medium | ☐ |
| T8 | Tests + example CLI + validation vs. memo 76/121 numbers | Sonnet 5 | GPT-5-mini | medium | ☑ 25 tests green; `python3 -m sa_select` CLI (exit 0 feasible / 2 not) |

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
Environment: see `casaLocation.md` (modular CASA 6.7.5 venv in `$WORK` + `casapy`
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

### HANDOFF STATE (7 Jul 2026 — read this first)

**Where things stand.** 14 offered subarrays now: the homogeneous set
(core-inner, core, spiral, mid, core+spiral, spiral+mid, main) PLUS the
memo-121 long+outer-core campaign (long, mid+long, spiral+mid+long, main+long,
spiral+core-outer, mid+spiral+core-outer, long+mid+spiral+core-outer). Curves
come from the shared engine (`sa_select/envelope.py`): row+column edge
interpolation PLUS **bilinear cell interiors** (7 Jul 2026), eta–skirt 1:1
trade about skirt 0.10 up to +0.15 span. Report:
`curvegen/reports/revf-curves.html` (dense engine curves, in-page subarray
calculator card). core+mid measured but DROPPED from the offered set (bmason).
62 tests green (`casapy -m unittest discover -s tests -t .`). The homogeneous
set is refined/smooth; the campaign set is coarser (see item 1 caveats).

**In flight / open items (owner: next agent):**
1. **memo-121 campaign: DONE + ADDED TO THE REPORT (7 Jul 2026, Opus).**
   Campaign finished (all 4 heavy long-combos, 0 failed). All 7 new subarrays
   (long, mid+long, spiral+mid+long, main+long, spiral+core-outer,
   mid+spiral+core-outer, long+mid+spiral+core-outer) added to
   `sa_select/data/subarrays.csv` (n_ant/b_min/b_max from the combined
   `.cfg`s; las_coeff 0.8; calc_name blank→donor-rescaled where the pkl lacks
   them, all already in `sensitivity._DONOR_N_ANT`) and to `make_report.ORDER`
   (+7 color slots in `report_template.html`, dataviz-checked for
   normal-vision separation; 14 categorical colors exceed CVD-distinctness so
   the report leans on its existing secondary encoding — labels, legend,
   per-subarray small multiples, data table, interactive highlight).
   `collect.py` → 3206 samples; report regenerated with the bilinear engine.
   **bmason authorized adding them (7 Jul); Long b_min is RAW (spurious ~37 m
   shorts NOT filtered — bmason: "probably not a substantial impact"), so
   Long-family LAS (~45″) is overstated — flagged in the subarrays.csv note;
   apply a ~150 m cut if LAS ever binds.** DATA CAVEATS for the new sweeps
   (they are coarser than the refined homogeneous set, NOT engine issues):
   Long-family imaging curves are steppy at the fine end (main+long worst
   adjacent eta step 0.91, spiral+mid+long 0.50 — relaxation↔trade-cap
   regime transitions with few samples); `long` has ~14 points with eta<1
   (min 0.965, single-noise-realization scatter). Run `refine.py` on the
   long-family to smooth them when compute is available.
2. **Bilinear cell interior: IMPLEMENTED + VALIDATED (7 Jul 2026, Opus).**
   `sa_select/envelope.py` now adds a 2-D bilinear interpolant over four
   lattice-adjacent (robust, taper) corner points (`Cell`, `build_cells`,
   `_cell_candidates`, wired into `_candidates` + `solve`). log(res),
   log(eta), skirt are bilinear in normalized cell coords (s,u); at a target
   resolution the constrained optimum's critical points along the res-locus
   are enumerated analytically (eta-stationary + skirt-stationary +
   skirt=level crossings = closed-form quadratics; penalized eta+skirt
   stationary via deterministic scan + golden refine). Cells form ONLY where
   all four edges are free of intervening measured points, so a cell edge
   coincides exactly with a row/column segment and can never undercut a more
   accurate 1-D fit. Design pre-consulted with codex (gpt-5.5 xhigh:
   confirmed the quadratic reductions; its guards folded in — singularity
   split, skirt-stationary for relaxation, non-unimodal penalized scan).
   **Validation:** brute-force 2-D locus-scan oracle on all 7 Rev F
   subarrays × 161 resolutions → engine J − oracle J = 0.000 (pinned,
   `TestBilinearRealData`); held-out recovery (drop the probe rows → bilinear
   reproduces the admissible interior, median interp error 0.18–2.7% eta,
   ~0.001 skirt in the operating range eta≤3); 58 tests green under casapy
   (+6 new, `TestBilinearCells`). **Current-data impact is small** because
   the probe rows are already measured; the value is generalizing the probe
   (no need to measure every intermediate row) and removing the edge-only
   deficiency for future/coarser sweeps. **main's residual ~9.5-mas step
   (0.255) is NOT interpolation error** — the oracle confirms no admissible
   skirt≤0.25 interior point exists there; it is a genuine trade_max=0.25
   hard-cap frontier feature (a J-lower point sits at skirt 0.253, excluded
   by the cap). Smoothing it needs a trade-policy change (bmason) or a
   targeted measurement, not an engine change.
3. **Calculator verification: DONE — JS VERIFIED (7 Jul 2026, Opus).**
   Replicated the report JS numerically against `sa_select` + the memo-96
   calculator on the report's own embedded DATA (30 GHz, 0.01", imaging,
   1000 MHz, 10 uJy/beam). Three-way agreement:
   | SA | sa_select engine | report JS | old handoff ref |
   |----|----|----|----|
   | main | eta 1.800 | eta 1.808 | eta 1.891 (STALE) |
   | spiral+mid | eta 1.237 | eta 1.242 | eta 1.237 ✓ |
   | mid | eta 1.618 | eta 1.640 | eta 1.618 ✓ |
   - eta selection: JS matches the envelope engine to ≤1.5% (residual =
     report's 0.01-dex dense-grid + the JS's own ±5% window re-min; not a
     logic fork).
   - σ_nat: JS log-log interpolation at 30 GHz matches
     `sensitivity.natural_rms` to <0.05% (main 20.42, spiral+mid 43.80,
     mid 95.79 uJy/beam @ 1h/1MHz).
   - t/ant-hr formula tHours=(eta·σ/S)²/bw, antHr=tHours·N reproduced.
   - **The one mismatch (main 1.891) is a STALE reference number**, not a
     calculator bug: it predates the latest main re-sweep (main.csv
     13:44 Jul 7). Current authoritative main eta @10 mas ≈ 1.80, which the
     JS reproduces. spiral+mid & mid refs match the engine exactly.
4. **Memo**: `memo/ngvla_sa_selection.tex` compiles (8 pp); needs bmason
   read + real figures (placeholders marked).
5. **COMMITTED: v4 (f1a02da)** — bilinear engine + 14-subarray report; and
   the refine sbatch (c8a4bdc). Working tree clean except untracked
   `NEXT_AGENT.md` / `futureDev.md`. 62 tests green.

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

7. **[FUTURE — do not implement now]** Selectable config revisions (revD, revF)
   for both curve generation and the calculator; and per-rev snapshot
   (single-integration) vs 4-h-track sims. Architecture impact to keep in mind:
   curve data keys and the report/selector must become rev- and sim-mode-aware
   (a (rev, sim_mode) axis on subarrays.csv/revf_curves.csv, the report
   dropdowns, and the sensitivity path). Design items 2 & 4's data schema and
   the report DATA layout so adding this axis later is additive, not a rewrite.

**Context for another model/agent**: CLAUDE.md (repo guide) → this PLAN →
`curve_anomaly_postmortem.md` (why the engine is what it is) →
`mstroh_comparison.md` (external validation) → `casaLocation.md` (TACC env:
casapy wrapper, quota/TempLattice gotchas) → `memo/` (the write-up) →
`codex-bridge/` + `tmp/codex/tasks/` (second-model consult/build transcripts).

### Curve-anomaly post-mortem + shared engine (6 Jul 2026, TACC evening)
bmason flagged pop-ups/drop-outs in both curve types (e.g. spiral+mid ptsrc
17.8 mas; mid imaging 8.08 mas; core+spiral imaging 103–118 mas sawtooth).
Post-mortem (`curve_anomaly_postmortem.md`): NOT noise — hard ±5% window +
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

## 11. Milestones

- **M1 — Working engine on bootstrap data:** T1 → T3 → T2 → T4 → T8. Tool runs end-to-end and
  ranks subarrays using stand-in curves. *Proves the design without waiting on CASA.*
  **☑ DONE 5 Jul 2026** — 25 tests green, memo-121 replays validate (e.g. PF3(KSG1).1: main,
  robust −1.81, eta 3.47, skirt 0.10). Run: `/Applications/CASA.app/Contents/MacOS/python3 -m
  sa_select --resolution 0.005 --frequency 80 --sensitivity 1e-6 --imaging`. Tests:
  `... -m unittest discover -s tests -t .` from repo root.
- **M2 — Authoritative Rev F curves:** T5 → T6. Swap bootstrap data for real Rev F point-source
  + imaging curves.
- **M3 — Memo + polish:** T7, tighten defaults, document limitations.

---

## 12. Decisions & open questions

**Resolved:**
- **Sequencing** — bootstrap first (M1 on stand-in data, no CASA), then Rev F curves. ✔
- **Subarray set (v1)** — the 7 subsets of {Core, Spiral, Mid}; SBA & Long deferred (§5). ✔
- **Optimization default** — **antenna-hours** when caller doesn't specify (matches the EOP
  resource-cost framing); overridable per call. ✔ (revisit if user prefers integration time)

**Still open:**
1. ~~Skirt metric convention~~ — **resolved 5 Jul 2026**: memo 65 "metric 2b" = azimuthally
   averaged radial PSF profile (iring + spline), evaluated at r = 1 clean-beam FWHM; memo 121
   adopts ≤10% (Gaussian ≈ 6%). Implemented in `curvegen/measure.py` (numpy annuli +
   CubicSpline, geometric-mean FWHM radius, central-cutout read for big PSFs).
2. **eta-invariance under frequency scaling** — accept as v1 assumption, or verify per subarray?
   (continuum fractional-bandwidth dependence flagged in notes.txt.)
3. **Antenna-hours definition** — simple t_int × N_ant is fine for the {Core,Spiral,Mid} set;
   revisit when Long (small-group structure / partial usage) is added.
4. Bootstrap CSVs are likely pre-Rev-F — acceptable as a temporary stand-in for M1? (assumed yes.)
5. **`core+mid` missing from the sensitivity calculator's pkl** — handle via the
   natural-rms + our-own-eta approach in §7 (recommended) or by adding a pkl entry. Decide in T4.
6. **Adapting to varied/realistic use cases — no known solution yet** (user, 5 Jul 2026):
   mosaics; observation-specific / varying FOV (notes.txt 2jul25: smaller FOV makes robust
   weighting more effective, very large FOV demands a better un-weighted PSF — could change SA
   selection; very small FOV → large uv cells, whole core in one cell, per ccarilli); and
   continuum vs. spectral line (fractional-bandwidth uv filling). **v1 assumes the memo-121
   fixed-FOV single-pointing convention**; document as a known limitation in the memo.
7. ~~Vintage of the calculator's eta_w splines~~ — **resolved 5 Jul 2026**: the calculator's
   internal eta_w is a placeholder formula, never a real spline (see gotchas §13). The §7
   natural-rms approach is implemented in `sa_select/sensitivity.py`; its eta never enters.
8. **Calculator re-centers continuum frequencies to the band midpoint** — should the tool
   surface/track the effective frequency (affects the frequency scaling of resolution/LAS,
   which we do at the *requested* frequency)? For v1 we scale at the requested frequency and
   note the discrepancy; revisit.

---

## 13. Gotchas log

- **Resumable sweeps preserve stale conventions (9 Jul 2026 incident).**
  `run_point` skips any recorded key forever, so when a measurement
  convention changes (here: the adaptive cell rule `cell = max(native,
  taper/OVERSAMPLE/1e3)` added for v2), rows measured under the OLD
  convention silently survive every later re-sweep — including the 8 Jul
  full-grid recompute.  68 v1-era sculpt-block points (robust {-2,-1.5,-1,
  -0.5} x large tapers; core/spiral/mid/core+spiral/spiral+mid) imaged with
  the NATIVE cell had beams up to 35% off their row (Briggs weights depend
  on the gridded uv density = 1/(imsize*cell)) and spuriously low skirts —
  the fake "strict islands" behind the imaging-curve jumps bmason flagged.
  Repaired with `curvegen/repair_stale_cells.py` (archives to
  results/attic-badcell/, strips, re-measures under the current rule);
  `collect.py` now HARD-FAILS on any ok/capped row violating the cell rule
  so mixed conventions can never be published again.
- **TACC (Stampede3):** `$HOME` quota is 14 GB — `curvegen/ms` & `work` are
  symlinks into `$SCRATCH/ngvla_curvegen/`, and sweeps must run with **cwd on
  scratch** because CASA writes multi-GB `TempLattice*` scratch images to the
  process cwd (two quota blowouts on 6 Jul 2026 before this was pinned down;
  invoke as `cd $SCRATCH/... && casapy $repo/curvegen/sweep.py <sa>` — imports
  resolve from the script dir). casatools also clashes with TACC's Intel oneAPI
  `LD_LIBRARY_PATH` — always use the `casapy` wrapper (`casaLocation.md`).
- `.venv/` has **only pip** (no numpy/scipy). Use CASA's Python
  (`/Applications/CASA.app/Contents/MacOS/python3`) or install deps into the venv.
- Git repo initialized 5 Jul 2026 (branch `main`); commit at milestones. `.gitignore` excludes
  `.venv`, caches, and regenerable CASA outputs. First commit = M1 (tests green).
- `ngvla-taperability-pipeline/analyze_images.py` uses `np.float` (removed in modern numpy) and
  Python-2-ish patterns; it targets an older CASA. Will need modernizing when adapted (T5).
- LONG subarray: tiny ~3-antenna groups with ~100 m baselines + multi-1000-km baselines. Filter
  the short baselines (irrelevant to imaging) before computing beam/eta — cf.
  `saUtil.filter_spurious_shorts` (default cut ~150 m). **Treat saUtil as a hint, not gospel.**
- SBA: D = 6 m and the sensitivity calculator does **not** support tapering it.
- `artifacts/saUtil.py` and `assign_eop_sa.py` are unvetted sketches — verify any approach
  before adopting (see memory `sautil-grain-of-salt`).
- **Curve-envelope reduction**: a Pareto-dominance rule is WRONG for taperability curves (it
  collapses the coarse branch — each resolution is its own requirement, not dominated by a
  finer/cheaper one). Correct reduction = min-eta per narrow log-resolution bin
  (`make_report.build_curve`, 0.03 dex). The v1 report's overview curves were quietly
  degenerate because of this; sa_select's window-solver was never affected.
- Config `.cfg` format is CASA XYZ: `X Y Z diam name`, `#`-comments; 214 antennas in Main.
  Rev F counts verified 5 Jul 2026: Core 114, Spiral 54, Mid 46, Long 30, SBA 19, Main 214.
- `subarray_data.pkl` lists `long` with b_min = 36.4 m — i.e. the calculator does **not**
  filter Long's spurious short baselines. Beware when Long's LAS/beam handling is added.
- `create_images.py`'s robust grid is `linspace(-2, 1.6, 10)` — memo 65 used −2…+2 step 0.4;
  reconcile the grid when adapting the pipeline (T5/T9).
- **Sensitivity-calculator internals (found during T4, 5 Jul 2026):**
  - Its internal `eta_w(theta)` is a **placeholder** (`log10(theta_mas*freq/30)`, line ~308) —
    the loaded spline is only used for theta validity bounds, never evaluated. So never use the
    calculator's eta; `sa_select/sensitivity.py` always calls with `theta=-1` (forces eta_w=1)
    and applies our curve-derived eta. (Also resolves former open question 7.)
  - Continuum calls **re-center the frequency to the receiver-band midpoint** (e.g. 30 GHz in
    Band 4 → computed at 27.25 GHz) and use the full band as bandwidth. Callers beware.
  - `theta_nat_30_GHz` in the pkl is in **mas**; calculator applies `*30/nu/1e3`. Units trap.
  - Bad inputs `sys.exit(0)` — wrapper converts to catchable `ValueError`.
  - Brightness-temp prefactor is hardcoded `1.216` (exact RJ value ≈ 1.222, ~0.5% off);
    our `tb_to_jy`/`jy_to_tb` use the exact value.
  - `natural_rms('core+mid', ...)` works via donor rescaling from `main` (σ ∝ 1/√(N(N−1)));
    verified exact for 18-m arrays since per-antenna params are band-keyed, not subarray-keyed.
    Confusion term is 0 at Rev F native resolutions, so the missing core+mid native beam is moot.
  - `integration_time(..., n_ant_actual=...)` supports reduced antenna availability.
- **Bootstrap data (T3, 5 Jul 2026):**
  - memo-121 CSV units confirmed: Resolution/res_nat/TA all **mas** (NGVLA_121.txt ~l.496-501);
    converted to arcsec in `data/bootstrap_curves.csv`.
  - **Calculator pkl's Mid baselines are pre-Rev-F**: computed Rev F mid b_min/b_max =
    10121/1272904 m vs pkl 17147/1068300 m (Mid moved to ~28MOD + GIS optimization, memo 102).
    Antenna counts match Rev F but *baselines don't* for mid/main. `data/subarrays.csv` uses the
    freshly computed Rev F values; the calculator's native-theta for mid/main is slightly stale
    (only affects the natural-rms anchor point marginally).
  - las_coeff: 0.85 for core-containing subarrays (memo 67: LAS_core = 0.85 λ/b_min);
    **0.58 provisional** (SBA value) for spiral/mid/spiral+mid — measure properly in Track 2.
  - `PerformanceCln.csv` is a byte-for-byte subset of `EfficientPlusPerformanceCln.csv`.
  - eta/level = −1.00 in `MainCln.csv` are failed-simulation sentinels (dropped, 6 cases);
    `NGA10` (main, robust −2) has skirt 1.48 (>1, unconverged) — kept but flagged in `note`.
  - Coverage: main 52×2, core+spiral 30×2, core 10×2, spiral 1×2, spiral+mid 1×2, **mid 0,
    core+mid 0** — real gaps until Track 2 fills them.

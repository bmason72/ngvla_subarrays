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
the RevD/snapshot campaigns (campaign_proposal_revd_snapshot.md).  **Now
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
   (mstroh_comparison.md).

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
checkout.  Relaunch commands: `RUN_CAMPAIGNS.md` (step 0 cancels the two
orphaned DependencyNeverSatisfied collect jobs 3299897/3299901).  Memo
updated the same day (scope now 14 subarrays, full-grid + uv-filter + campaign
sections, real figures replacing the three placeholders).

### HANDOFF STATE (7 Jul 2026 — read this first)

**SESSION DELTA (15 Jul 2026, Fable):**
- All four campaign reports EXIST and are FRESH (newer than their curve
  CSVs; the campaign collect stage builds them): `curvegen/reports/`
  revf-curves.html (14 SAs), revF-snapshot-curves.html (14),
  revD-track-curves.html (9), revD-snapshot-curves.html (9).  bmason review
  pending.  QA note: mid+long has only ~53 samples in BOTH snapshot
  reports (vs ~150 track) — consistent across revisions, so probably
  genuine snapshot-uv pruning, but eyeball its heatmap first.
- **Long b_min correction (supersedes the note in item 1):** Rev F Long is
  10 clusters x 3 antennas; intra-cluster baselines span 37–176 m, then a
  clean gap to 515 km.  A ~150 m cut is therefore WRONG (leaves the 176 m
  intra-cluster pair); any cut in (176 m, 515 km) works — use e.g. 1 km.
  The filter must be COMPONENT-AWARE: filter only Long's intra-cluster
  pairs, then b_min(combo) = min over components' legitimate b_min
  (e.g. main+long keeps core's real 42.15 m).  Long-only filtered
  b_min = 515 km (LAS ~4 uas at 30 GHz).  Analysis: single-linkage
  clustering on curvegen/configs/long.cfg, 15 Jul session.
- Queued next: bmason reviews the 3 new reports; long-family refine passes
  (standing caveat) when node-hours are approved; milestone commit of the
  RevD/snapshot campaign state (uncommitted since 74470c0); optional
  cross-revision/mode comparison report (spec deliberately before building).
  **[All four addressed in part 2 below, same day.]**

**SESSION DELTA (15 Jul 2026, Fable — part 2: defect diagnosis + fixes +
combined report + $WORK migration).**  bmason eyeballed the three new
reports and flagged uneven curve quality; full diagnosis, fixes, and staged
follow-ups below.  Codex (gpt-5.6-sol) consulted on the physics/diagnosis
and guard-reviewed the diff; a quantitative "curve census" (subagent,
reproducing make_report.build_curve exactly per campaign) grounded it.

*Diagnosis — every flagged defect mapped to a cause:*
1. **Refine starvation, three ways.**  (a) The campaign refine budget (60)
   was exhausted on the sparse fresh lattices; worst in-band eta steps
   0.36–1.53 survived (revD-track main+long 1.16 double-jump @0.9 mas,
   spiral+mid 2x0.36 staircase, mid+long 0.27 spike; snapshot main+long
   1.42/1.53 @~3.3 mas; etc.).  (b) `refine.samples_from` did NOT apply the
   report's eta<=5 display trim, so budgets were BURNED on invisible eta~5+
   fringe jumps — e.g. snapshot spiral "worst step 0.92" (identical in both
   revisions, suspicious-looking) while its rendered curve was already
   smooth at 0.10.  (c) refine only ever chased the IMAGING curve, so
   point-source steps (revF-snapshot main 0.45, main+long 1.42; even
   revF-track main+long 0.38) were never targets.
2. **One corrupt measurement**: revF-snapshot `long` briggs r=-2 t=6.332mas
   recorded ok with bmaj=bmin=1e-6", sigma=0, skirt=0 (an empty tclean
   product with a sentinel beam).  It alone caused the "LONG = dots" render
   (a lone curve point 324x finer than everything else).  Archived to
   `results-revF_snapshot/attic-degenerate/`, re-collected.
3. **Snapshot sub-natural absence is PHYSICS, not missing data**: with one
   60 s integration each baseline is one uv sample; on the Briggs density
   grid (uv cell = 1/(imsize*cell)) nearly every occupied cell holds <=1
   visibility, so Briggs == natural (core snapshot r=-2 shrinks the beam
   0.5% vs 30% for the track).  Established on the UNTAPERED lattice rows,
   where cell (hence the density grid) is identical across robust — immune
   to the adaptive-cell caveat below.
   Only composites (dense multi-occupancy core cluster) go sub-natural
   (main 0.55x). Verified numerically; codex concurs, with the caveat that a
   REAL snapshot has bandwidth/multi-dump uv filling — a monochromatic
   1-dump sim understates robust's lever (logged as an open control, below).
   Documented in-report (snapshot combos get a header note).
4. **mid+long snapshot ~53 usable points is real cap censoring** (175/228
   lattice points land beyond mid's natural-beam cap) and **LONG snapshot
   fragmentation is honest sparse instantaneous coverage** (plus item 2 in
   revF's case); revD-snapshot long keeps 3 genuine x1.4–2.0 in-window gaps
   (taper grid too coarse where beam(taper) moves fast).

*Fixes implemented (98 tests green):*
- `sweep.py run_point`: degenerate-product guard — fail (never ok) when
  bmin < 1 CELL or sigma<=0 or non-finite; stderr warning below 3 cells.
  (1 cell, not 2: legitimate far-coarse LONG rows fit bmin ~1.6–2.0 cells
  under the adaptive-cell convention — the sentinel sits at 0.001 cells.)
- `collect.py`: same check at publish time (hard fail, like the stale-cell
  guard); provenance `source` tag now rev/mode-aware for non-default combos
  (default stays byte-identical "revf-sim").
- `refine.py`: samples now eta<=ETA_CAP-trimmed EXACTLY like the report;
  chases BOTH imaging and point-source curves (same bracketing generator,
  jumps unioned); res-gap chasing still capped-subarrays-only.
- Campaign plumbing: `submit_campaign.sh --refine-budget N --refine-rounds M`
  -> `NGVLA_REFINE_BUDGET/ROUNDS` -> `campaign_sweep.sbatch` refine call.
- 3 new campaigns re-collected (revf_snapshot_curves.csv is 1 corrupt row
  lighter; labels fixed).
- **Staged for bmason (RUN_CAMPAIGNS.md §1): four POLISH campaigns**
  (budget 200, rounds 8; prep/sweep/fill are resumable no-ops, only refine
  runs).  Order free; revF/track last/optional (its two ptsrc steps).
- **NOT changed on purpose**: mid+long snapshot capping (honest physics),
  LONG snapshot dot/segment rendering (honest gaps — now explained by the
  in-report snapshot note), the fixed-FOV adaptive-cell weighting convention
  (documented trade-off; codex flagged that FOV varies with cell across a
  taper row — acknowledged, deliberate, collector-enforced since 9 Jul).

*Combined all-campaigns report (bmason feature):*
`make_report.py --combined reports/ngvla-curves.html` gathers ONE payload
per registered combo (each built by a subprocess with that combo's env —
config freezes RESULTS_DIR at import) and injects
`{payloads, combos, default}`; the template now has a **campaign dropdown**
(top-right of the header) that swaps DATA and re-renders the whole page.
Template re-architected from render-once to `bindData()` + idempotent
`render*()` functions under `renderAll()`; listeners wired once; s0 choice
survives campaign switches; snapshot combos show the physics note card; the
hardcoded Rev-F profile/QA diagnostic cards hide on other combos (closing
the old "cosmetic limitation").  Per-combo reports build exactly as before;
`campaign_collect.sbatch` now refreshes BOTH.  JS syntax esprima-checked;
subagent logic review of the refactor.  16 MB with all four campaigns.
`--payload-json` is the new subprocess interface.

*MS migration + regeneration insurance (bmason directive):*
- MS stores (the only expensive scratch assets; results CSVs live in git)
  **moved to `$WORK/ngvla_curvegen/`** (8.7 GB rsync, verified 16/16 MSes)
  because $SCRATCH is purged.  `curvegen/ms` symlink repointed; non-default
  combos route via new env `NGVLA_MS_BASE` (default `$WORK/ngvla_curvegen`
  in every campaign sbatch; falls back to NGVLA_SCRATCH for laptops).
  tclean work dirs (TempLattice churn) deliberately STAY on scratch.
  NB an interactive sweep without NGVLA_MS_BASE set still resolves the old
  scratch path for non-default combos — export it (or use the sbatches).
- `curvegen/regen_ms.sbatch` (`sbatch --array=0-3 ...`): one task per combo
  re-simulates any MISSING MS into $WORK; idempotent insurance, a few
  node-hours from nothing.  Old scratch copies left in place (purge will
  reap them).

*Codex guard review of the diff (gpt-5.6-sol, threaded) — adjudication:*
- FIXED per review: NaN/Inf fail-open in both degenerate guards (finiteness
  + positivity on bmaj/bmin/res/sigma/cell, natural-reference row validated
  before eta division); standalone per-combo reports now carry
  `payload.combo` so the snapshot note / per-combo header / Rev-F-reference
  card gating work OUTSIDE the combined report too; refine-budget env vars
  are always exported explicitly (a stale NGVLA_REFINE_* in the submitting
  shell could silently make a default campaign a polish pass) + integer
  validation; refine candidate selection is now severity-ranked round-robin
  per jump (flat sorted-set truncation could let one pathological jump
  starve the rest); collect.py + make_report.py write via tmp+os.replace
  (4 concurrent polish collects share ngvla-curves.html); MS migration
  verified by rsync checksum pass.
- REJECTED with rationale: 2-cell hard floor (legit LONG rows at 1.6-2.0
  cells; codex accepted the 1-cell floor + 3-cell warning split).
- REWORDED per review: the snapshot note no longer claims a "fixed-FOV"
  convention (imsize is fixed, cell adapts to taper, so FOV/density grid DO
  vary along a taper row — a deliberate, collector-enforced convention since
  v2) and states the sub-natural conclusion via the untapered rows; LONG
  fragmentation now "consistent with sparse instantaneous coverage" rather
  than conclusively "honest gaps" (dense diagnostic scans still pending).

*Logged-for-later (codex advisories, not blocking):* dense 1-D taper scans
as a diagnostic for any jump that survives the polish pass (distinguishes
budget artifact / beam-fit lobe switch / constraint-branch transition);
bisection-style direct resolution targeting in refine; a bandwidth+
multi-dump-realistic snapshot control sim (does robust get a lever back?);
reporting bmaj/bmin/axis ratio for snapshot beams (res_geo hides
elongation; data exists in results CSVs, needs schema thought); analytic
eta from gridded weights as a noise-free cross-check; PSF-peak/main-lobe
independent beam sanity checks.

*ASK BMASON (non-blocking, defaults chosen):*
1. Snapshot convention: we ACCEPT "snapshot curves start at ~natural for
   sparse subarrays" as the honest answer under the standard memo-121
   convention (report says so).  If snapshot forecasting fidelity matters,
   the bandwidth-realistic control sim above would tell us how much lever
   real continuum snapshots recover.  OK?
2. Keep offering LONG-family snapshot curves at all (fragmented but
   honest), or drop them from the snapshot registry rows?
3. Eyeball the new combined report (reports/ngvla-curves.html) — the four
   per-combo reports remain but the combined one is intended to be THE
   report going forward.

*Future goal noted (bmason, 15 Jul): per-subarray PSF plots and cuts in the
report for the selected subarrays.*  DESIGNED same day — see the dedicated
section below ("PSF inspector plan").

**SESSION DELTA (16 Jul 2026, Fable — polish crash + relaunch + P3/P4).**
1. *15 Jul polish attempt crashed*: Slurm inherits the SUBMISSION dir as
   cwd; refine.py's big tcleans dumped TempLattice into the repo on $HOME
   until the 14 GB quota filled (casacore "Disk quota exceeded" core
   dumps).  FIXED: all campaign sbatches pin cwd to
   `$NGVLA_SCRATCH/run_<jobid>[_<task>]`; ~9 GB debris deleted; also fixed
   `fill_beam_caps.py` hard-exiting on the default combo (first
   revF/track-through-submit_campaign ever).  Commit 553a765; post-mortem
   in RUN_CAMPAIGNS.md.  Second failure mode found: the per-user
   queued-job LIMIT silently kills later sbatch calls when 3-4 campaign
   chains stack up (cost revD/track its collect job TWICE) — gotcha below.
2. *16 Jul relaunch (bmason, 3 campaigns): DONE.*  All sweeps completed;
   revD/track's collect was run locally (queue limit again).  All three
   campaigns' curve CSVs + reports + PSF payloads are CURRENT.  Polish
   verdict: budget exhaustion is gone (except revD/track `long`, 1.21
   imaging, budget-limited — a resubmit continues it); most flagged
   defects FIXED (revF/snapshot main+long imaging 1.42→0.24; revD/track
   mid+long spike and main ptsrc gone); survivors (residual table in
   RUN_CAMPAIGNS.md) all stopped on CANDIDATES EXHAUSTED — dense local
   sampling didn't move them, which per the polish assumption is now real
   evidence of physics/branch transitions (esp. the snapshot natural-end
   ptsrc cliffs: main+long revD/snapshot 1.58).  Next levers = dense 1-D
   taper scans / bisection targeting in refine (codex advisories), or
   accept + document.  bmason decision point.
3. *P3+P4 BUILT* (see the PSF inspector section): exporter + report panel,
   codex build mode (sandbox works again), commit be0003e.  revF/track
   polish is the one campaign still to launch; P1 (cut capture) next,
   then P2 backfill AFTER revF/track polish lands.
4. bmason wrote two reference notes at repo root (untracked, theirs):
   `ETA_JUMPS.md` (why eta jumps happen; the polish assumption) and
   `POLISH_AND_STORAGE.md` (how polish samples; the $WORK/$SCRATCH
   layout).

**SESSION DELTA (21 Jul 2026, Fable — state audit: revF/track polish LANDED
→ POLISH 4 of 4 DONE).**
1. *revF/track polish ran 16 Jul 16:19–16:39* — bmason launched it minutes
   after commit c643dca, so the committed docs still said "still to
   launch".  Full chain COMPLETED (prep 3318072 → sweep 3318073_0–5 →
   collect 3318074; first revF/track end-to-end through
   submit_campaign.sh).  Outcome (sweep logs): only
   long+mid+spiral+core-outer took new points (+5; ptsrc worst in-band
   step 0.49→0.42; ended round 3 "1 jumps, 0 new points" = CANDIDATES
   EXHAUSTED); main+long ptsrc stays 0.38 (+0, candidates exhausted); ALL
   imaging curves ≤0.19; everything else ≤0.25 on both curves.  **POLISH
   IS COMPLETE (4 of 4).**  Queue empty since 16 Jul 16:39.
2. *Reports are CURRENT — no regen needed*: the 16:39 collect rebuilt
   revF-track-curves.html + the combined ngvla-curves.html + PSF payloads
   (`reports/psf/revF_track`) with HEAD code (c643dca touched only
   planning docs).  revF/track's PSF panel still shows "pending backfill"
   by design until P2.  Survivors table in RUN_CAMPAIGNS.md gained the
   revF/track row.
3. *Milestone commit (this one)*: routed `revf_curves.csv` (4038 samples)
   + `results/long_mid_spiral_core_outer.csv` (+5 refine points) + these
   doc updates (PLAN/NEXT_AGENT/RUN_CAMPAIGNS).
4. Housekeeping: `revDsnapshotIssue.txt` (13 Jul, untracked) predates the
   successful 16 Jul relaunch — resolved/stale.  P2 anchor backfill is now
   UNBLOCKED (polish landed); order stays P1 → P2.  MFS-1/-2 (CASA-free)
   can start any time; MFS-3 pilots still gated on the bmason checkpoint.
   The only re-launch candidate is the optional revD/track polish resubmit
   (continues its budget-limited `long` imaging refine, 1.21; all else
   no-ops) — part of bmason's standing survivors decision (a/b/c above).

**SESSION DELTA (21 Jul 2026, part 2, Fable — curve-quality upgrade:
escalated refine + display smoothing + P1 + P2).**
1. *bmason review of the polished curves: not good enough.*  Flagged: huge
   ptsrc jumps (revF/snap main+long & main; revD/snap main+long 1.58 &
   main); disconnected points (revF/track long low-res point; revD/snap
   long); revD/track main+long imaging jumps + spiral+mid sawtooth; wiggly
   connecting lines (revF/track core & core+spiral imaging; revD/snap main
   imaging).  Decision: FIX, not accept.
2. *Data diagnosis (subagent over all 4 campaigns' displayed curves):*
   the snapshot ptsrc jumps are TAPER-ONSET CLIFFS at the natural-res
   boundary (untapered branch ends at robust +1.4..+1.8, eta~1.0; next
   winner is tapered at eta 1.4-2.6); the sawtooth is the coarse taper
   lattice (x1.52 columns); the disconnected points are interior taper
   transitions on homogeneous LONG (gap-chasing was heterogeneous-only);
   wiggles are 0.01-0.09 envelope zigzags whose worst cases are true BUMPS
   (a winner above its neighbours' chord = branch alternation).
3. *refine.py escalation ladder built* (codex gpt-5.6-sol xhigh design
   consult, adjudicated; opus implementation; Fable review + patches):
   E1 secant resolution targeting (one shot per interval, log-space, same-
   weighting evidence only; cliffs skip to E2) -> E2 staged progressive
   log-midpoint taper scans (SAME rounded taper vector at BOTH endpoint
   robusts — E0 verified singleton probes are INVISIBLE to the envelope,
   so probes must complete segments/cells; classify from measured rows:
   confirmed discontinuity / high-penalty / under-sampled) -> E3 gap
   chasing for ALL subarrays (homogeneous via E2; untapered-robust
   defects fall back to the fixed menu) -> E4 bump regions (eta-scaled
   trigger, top-2/curve, <=25% budget).  Shared sample_from_row now
   enforces the refine==report filter contract structurally.  New flags:
   --scan-points/--bump-min (+ NGVLA_REFINE_SCAN_POINTS passthrough);
   refine_parallel --budget forwarding bug fixed.  Dry-run on real
   revD/snapshot data: cliff scans at both bracket robusts with sub-0.15
   mas tapers, disconnected-LONG scans — exactly the intended probes.
4. *Display-only curve smoothing* (bmason: "more reliably smooth
   connecting interpolations"): make_report smooth_curve — segment at
   drawn gaps (1.055) and real steps (>0.20), RDP knots + forced material
   extrema (>0.05), pure-numpy PCHIP, iterative knot insertion to
   max|smooth-raw|<=0.03 and optimistic<=0.02, raw fallback; payload
   ships parallel imaging_smooth/pointsource_smooth arrays; the JS draws
   them for the LINE only (markers/tooltips/gap-breaks stay raw).  Raw
   curves untouched for refine and sa_select.  Real-build deviations:
   worst 0.028/0.020 over ~70 curves.
5. *P1 axis-cut capture BUILT* (measure.psf_axis_cuts + capture_profile
   beam/cuts fields, CASA-free tests) and *P2 anchor backfill BUILT*
   (backfill_psf.py + sbatch: re-images displayed-curve anchors lacking
   cut-bearing profile lines with the EXACT recorded convention via the
   new single-source sweep.tclean_kwargs; results CSVs byte-identical by
   construction + AST test; resumable).  Scale note: revF/track alone has
   ~949 anchors to image (predates profile capture) — node-days, 47 h
   walltime + resubmits.
6. *Codex guard review (xhigh, full diff): 5 blockers, 4 should-fix, 1
   nit.*  Accepted and fixed: axis-cut SIGN bug (negative RA increment
   reflects the cut line — real geometry error), _classify_scan bypassing
   sample_from_row, backfill success-on-fallback + stale-product reuse,
   E2 pair atomicity at budget edges, point_key -0.00 canonicalization,
   smoother hard-bound final guard, unused hysteresis claim removed, zero
   validation.  REJECTED with rationale: "backfill must cover all skirt
   setpoints" — the s0=0.10+ptsrc+natural scope is bmason's approved P2
   spec AND make_report strips env_keys for non-default setpoints, so the
   report cannot reference them (coupling comment added).
7. *Wave plan* (RUN_CAMPAIGNS.md "21 Jul wave"): revD/track CANARY
   (budget 240, rounds 12) + chained backfill --array=2; inspect
   escalation logs; then revF/snapshot, revD/snapshot, revF/track (200,
   12) serialized vs queue headroom, each + its backfill; final combined
   report rebuild.  Genuine snapshot cliffs will come back CLASSIFIED
   (physics), not smoothed away — expectation to set with bmason.

**SESSION DELTA (21 Jul 2026, part 3, Fable — wave launched; cap question
resolved; adaptive-sampler direction approved + spec).**
1. *Wave launched (canary stage).*  revD/track: prep 3333952 → sweep
   3333953[0-3] → collect 3333954 → backfill 3333958[2], all PENDING at
   hand-off.  Remaining three campaigns + backfills launch after canary
   inspection — NEXT_AGENT.md item 1-2, RUN_CAMPAIGNS.md "21 Jul wave".
   The 09d6d7e milestone commit carries the whole code upgrade (177 green).
2. *Beam-cap question (bmason): resolved as a memo misreading.*  The cap
   binds only the COARSE end; reference = coarsest component (mid+long →
   mid 2.96 mas; spiral+mid+long → spiral+mid 11.1; main+long → main 21.2;
   *+core-outer → 491; main → core 710); measured ranges relay with ~2x
   seam overlap (mid+long 0.51–2.82 mas hands to mid 2.03–54.6, etc.).
   bmason's proposals were both stricter than or equal to what exists;
   memo wording made unambiguous + recompiled (commit 07a144e).  Logged
   nuance: a min-integration-time ranking could in principle want
   beyond-cap mixture offerings (marginal sensitivity edge over the
   standalone subarray); a one-mixture 2x-cap-extension diagnostic
   (mid+long) is the cheap v2 experiment if ever wanted.
3. *Adaptive sampling (bmason proposal → codex xhigh consult → approved):*
   replace regular-lattice+polish with a goal-oriented quadtree/AMR
   sampler — tolerance-scaled hierarchical-residual loss (tau = ln1.05
   res / 0.1 eta / 0.02 skirt ABSOLUTE per bmason), 2-sigma noise
   deadband, exploration floor, envelope/skirt-band goal weighting,
   feature state machine {smooth, step, ridge, noise} with steps scored
   by INPUT-LOCATION bracket (localize cliffs, cut annotations, never
   interpolate across).  Rails demoted to seed-boundary (interior seeds
   mandatory — imaging winners are interior); triangular/scattered mesh
   REJECTED as architecture unless a replay shows ≥30% additional saving
   at p90 (Delaunay simplices across cliffs manufacture nonexistent
   resolutions).  Full spec: `MFS2_ADAPTIVE_SAMPLER_SPEC.md` (supersedes
   MFS scope decision 4; seed ≈56 pts, budget plan 80/map, V1 replay
   gate).  Codex spec-review launched at session end — may need re-run
   (NEXT_AGENT).  bmason's standing bet: the in-flight wave (new
   escalation, not old polishing) may still not fill the holes — if maps
   remain under-converged they become the sampler's retrofit-mode pilot.

**SESSION DELTA (21 Jul 2026, part 4, Fable — adaptive sampler BUILT +
retrofit staged; grid MFS dropped).**
1. *bmason directives:* no grid-style MFS (adaptive from day one); MFS
   initially Ka band only (27±6.75 GHz), nchan an explicit parameter
   bmason sets later; adaptive retrofit ORDERED on all four existing
   campaigns; surrogate framing confirmed (the bilinear cell IS the local
   surrogate; residual-driven refinement everywhere, not just at branch
   points).  bmason's reframing (f: (t,r)->(theta,s,eta); per-theta 1-D
   contour searches; Pareto per theta) adopted — spec v2 carries it.
2. *Spec v2 (commit 250f85e):* executable build contract; all 15 codex
   findings resolved; constants pinned; budget arithmetic honest (fresh
   seed 56, plan 110/audit 140; retrofit plan 40/audit 80 NEW evals).
3. *Sampler core BUILT (commit 8242d08):* curvegen/adaptive.py + 44 tests
   (221 green) — quadtree over the point table, certification retirement,
   feature classification with cut brackets, wave planner, --plan-only
   CLI.  Key validation: revD/snap main+long "cliff" correctly certified
   smooth IN INPUT SPACE (eta climbs continuously while res stalls; the
   res step is 2.3% < the 5% tolerance) — the displayed jump is the
   honest image of a smooth surface; nothing to sample.  Its 16-eval wave
   targets the genuinely under-resolved 4.6-8.2 mas region instead.
4. *Certification pass over all 46 maps:* first wave 1508 evals total
   (F/track 537, F/snap 391, D/track 342-stale-canary, D/snap 238); all
   retrofit-auto, no cap violations; features match every documented
   defect; ONE NEW candidate: revD/snap long second step ~2.6 mas (E_T
   up to 14) + unresolved 0.34-0.49 mas cluster — retrofit will probe.
5. *Measuring driver BUILT (commit 0be5f8c):* wave loop (mode pinned
   across rebuilds; per-process budget window — documented limitation) +
   adaptive_retrofit.sbatch (array 0-3, collect+report+export tail).
   225 tests green.  Dev incident: a placeholder test briefly ran real
   tclean and appended 3 rows to results/core.csv — caught, reverted
   byte-identical, scratch cleaned, test monkeypatched.
6. *Sequencing:* escalation campaigns 2-4 SUPERSEDED by the retrofit
   chain (RUN_CAMPAIGNS "Adaptive retrofit wave"): canary collect ->
   scancel queued backfill 3333958 -> retrofit array 0-3 -> per-task
   backfill chain -> combined report.  Canary early results: spiral+mid
   sawtooth FIXED (1.16->0.18 imaging), mid+long 0.10/0.06 with honest
   classifications.  PHASE 3 (after retrofit wave drains; live-code
   hazard): 2c envelope leaf-cell enumerator + cuts, 2a Ka band axis
   (then Ka MFS wave once bmason supplies nchan).

**SESSION DELTA (17 Aug 2026, Fable — July wave harvested; NEW SCOPE =
WRAPUP.md; live plan = RELEASE_PLAN.md).**
1. *The 21-24 Jul chain COMPLETED unattended* (recovered from sacct + the
   logs bmason archived to /work2/.../oldNgvlaLogs/ on 13 Aug): canary
   sweep/collect (3333953/3333954), adaptive retrofit array 0-3 (3335064),
   all four PSF backfills (3335065-68) — every job exit 0.  Each retrofit
   task's collect tail auto-rebuilt the reports (23 Jul); the queued
   backfill 3333958 was cancelled per plan.  No compute artifacts exist
   after 24 Jul.
2. *Retrofit QA (from logs):* all steps everywhere came back "classified:
   sampled resolution discontinuity" (incl. the flagged revD/snapshot long
   ~2.6 mas candidate — genuine physics).  Snapshot maps mostly CONVERGED
   ("no proposals"); nearly every revF/track and revD/track map stopped at
   the 80-eval AUDIT CAP = wave 1 of ~2-3.  bmason decision (17 Aug): one
   more retrofit wave, tracks only (combos 0 and 2), then reassess.
3. *Harvest (this commit):* 6590 pure row-insertions across 50 CSVs
   (results-*/ + routed sa_select curve tables; headers unchanged), 225
   tests green, combined report rebuilt post-backfill (the run-sheet's
   final step, previously pending).  PSF axis-cut payloads exist for all
   four campaigns (reports/psf/, 23-24 Jul).
4. *NEW SCOPE (bmason, WRAPUP.md 17 Aug — supersedes this file where in
   conflict):* release the calculator web + python prototypes for
   revF/track (ptsrc+imaging), revD/track (ptsrc only), revC/track (ptsrc
   only, NEW campaign).  Snapshots NOT released.  Plan of record:
   `RELEASE_PLAN.md` (T0 harvest ✓ / T1 retrofit wave 2 / T2 revC campaign
   / T3 release page / T4 calculator surface / T5 MStroh formats /
   T6 docs+memo).  bmason launches all Slurm jobs himself now — agents
   prepare command lines only.

**SESSION DELTA (18 Aug 2026, Fable — 17-Aug release wave harvested).**
1. *All 11 jobs of the 17-Aug wave COMPLETED, exit 0* (bmason launched
   17 Aug pm): retrofit wave 2 tracks 3415615_{0,2} + backfills
   3415617_0/3415618_2, and the FIRST revC/track campaign chain — prep
   3415634 → sweep 3415635_0-3 → collect 3415636.
2. *Retrofit wave-2 QA (from logs):* zero failed evals.  Convergence:
   revF/track 6 of 14 maps "no proposals", 8 still at the 80-eval audit
   cap; revD/track 2 of 9 converged, 7 at the cap.  Every wave-2 step
   feature again classified "sampled resolution discontinuity"; ridges
   "locally supported high-penalty interval" — consistent with wave 1
   (physics, not under-sampling).  Both backfills exit 0 = all envelope
   anchors cut-bearing.  Wave 3 is bmason's call (RELEASE_PLAN decision 1
   said reassess after wave 2).
3. *revC/track campaign DONE end-to-end:* 9 subarrays, 2091 result rows
   (results-revC_track/), routed curves (sa_select/data/
   revc_track_curves.csv, 1935 rows) + 3 beam caps filled into
   subarrays_revc.csv by prep.  Residual worst in-band steps: long
   0.74/0.75 both curves and main+long imaging 0.78 / ptsrc 0.30 — all
   refine-budget hits (+60 pts each); every other subarray ≤ 0.22.
4. *revC PSF backfill NOT needed:* `backfill_psf.py --dry-run` audit =
   586/586 anchors already cut-bearing (fresh campaigns capture axis
   cuts natively, feature P1).  The run-sheet `--array=4` line is
   superseded; reports/psf/revC_track/ payloads (9 files) exported by
   collect.
5. *Reports + tests:* combined internal report rebuilt (5 campaigns) and
   release page rebuilt (3 tracks; revC curves now live; revD+revC
   imaging "Omitted" markers present).  253 tests green (1 skipped;
   count grew from 225 with the T2-T5 test additions).

### PSF inspector plan (15 Jul 2026 — designed; P3+P4 BUILT 16 Jul; P1+P2 BUILT 21 Jul)

**Status 16 Jul 2026:** P3 (`curvegen/export_psf_data.py` + collect-stage
wiring + `tests/test_export_psf.py`) and P4 (the report's "PSF inspector"
card) are BUILT — implemented by codex (gpt-5.6-sol, build mode — its TACC
sandbox works again; probe before relying on it) to Claude's specs, then
Claude-reviewed line-by-line + subagent-QA'd + esprima-gated.  31 payload
files (~5.3 MB) exported for the three combos with profiles; revF/track
correctly skips until its profiles exist (polish refine points + P2
backfill).  Entry points wired: subarray dropdown, heatmap-cell click,
small-multiple-mark click, calculator per-row "PSF" button
(nearest-measured-key resolution).  P1 (axis-cut capture) and P2 (anchor
backfill) were BUILT 21 Jul — see the 21 Jul part-2 delta; backfill runs
ride the 21 Jul campaign wave (RUN_CAMPAIGNS.md).

bmason's decisions (AskUserQuestion, 15 Jul): **(1)** azimuthal profiles AND
major/minor-axis cuts (cuts need a capture extension; they expose the
snapshot elongation the azimuthal average hides); **(2)** display scope =
FULL lattice, lazy-loaded (report no longer one self-contained file — the
`reports/psf/` payload dir travels with the HTML); **(3)** anchors-only
backfill; **(4)** polish campaigns launch now, PSF work proceeds in
parallel.

**Data situation:** results-{revF_snapshot,revD_track,revD_snapshot}/
profiles/*.jsonl already hold an azimuthal radial profile for EVERY measured
point (~7.2k profiles; capture feature v11).  revF/track has NONE (its
points predate v11).  Axis cuts exist nowhere yet.

**Sequencing constraint (important):** the polish campaigns MOVE the
envelope anchors, so the anchor backfill (P2) must run AFTER polish lands.
Polish refine points get azimuthal profiles automatically (CAPTURE_PROFILES
is on everywhere — this also starts populating revF/track's empty
profiles/); the post-polish backfill then adds cuts at the settled anchors.
If P1 happens to land before bmason submits polish, polish points carry
cuts natively — a bonus, not a dependency.

**P1 — capture extension** (`curvegen/measure.py`, `sweep.capture_profile`).
New pure-numpy `psf_axis_cuts(cutout, center, cell_arcsec, bpa_deg, r_max,
n=81)`: bilinear-sample the PSF along the fitted-beam major & minor axes,
signed radius ±r_max (= 3 x res_geo, matching the radial profile).  JSONL
line gains `bmaj_arcsec, bmin_arcsec, bpa_deg, cut_r_arcsec, cut_maj,
cut_min`; old lines stay valid (missing cut fields => "azimuthal only").
CASA-free unit test alongside tests/test_measure_profile.py.
[Sonnet 5 / GPT-5, medium]

**P2 — anchor backfill** (`curvegen/backfill_psf.py` + `backfill_psf.sbatch`,
job array over the 4 combos; run AFTER polish).  Anchor set per subarray =
env_keys of the s0=0.10 imaging curve + the ptsrc curve (build_curve over
collected samples, exactly like refine) + the natural point.  For each
anchor lacking a cut-bearing JSONL line: re-image with the EXACT recorded
convention (weighting/robust/taper; imsize; **cell from the results row's
cell_arcsec**, NOT recomputed; uvrange from config) with results-CSV
recording DISABLED — backfill must never touch curve data — then append the
profile+cuts line (loader: last line per key wins).  Resumable by skipping
cut-bearing keys.  Covers revF/track profiles+cuts and the other three
combos' anchor cuts in one pass; a few node-hours.
[Opus 4.8 / GPT-5, high — the convention-reuse details are where bugs live]

**P3 — payload export** (`curvegen/export_psf_data.py`).  profiles JSONL ->
`curvegen/reports/psf/<rev>_<mode>/<sa>.js` script files:
`window.PSF_REGISTER("<combo>/<sa>", {key: {...}})` — script-tag JSONP, NOT
fetch(), because Chrome blocks fetch() on file:// and these reports open as
local files.  ~0.2-0.5 MB per (combo, subarray).  Wire into
campaign_collect.sbatch (per-combo) and the --combined build (all combos).
[Sonnet 5 / GPT-5-mini, medium]

**P4 — report UI panel** (`report_template.html` + make_report).  New "PSF
inspector" card: subarray dropdown + point selection three ways — (a) a
"show PSF" affordance on each calculator result row (its chosen operating
point, nearest measured anchor), (b) CLICK any heatmap cell or
small-multiple mark, (c) default = natural point.  Plot: azimuthal profile
+ both cut arms (major/minor) vs radius; annotate r=1 FWHM vertical, the s0
threshold horizontal, the measured skirt dot; text line with bmaj x bmin @
bpa, axis ratio, eta, skirt.  Lazy-load via injected <script> per
(combo, subarray), cached; graceful states: "cuts pending backfill"
(azimuthal-only line) and "no PSF captured for this point" (revF/track
non-anchors until backfill/full pass).  Re-render-safe like every other
panel (renderAll clears it; pending loads guarded against stale combo).
[Fable/Opus 4.8 / GPT-5, high — fiddly SVG/JS, follow the renderAll rules]

**P5 — docs + QA.**  README/RUN_CAMPAIGNS notes (psf/ dir must travel with
the HTML), PLAN update, spot-check elongated snapshot beams (mid+long) and
a relaxed imaging point.  [any small model, low]

Build-time defaults (flag if changed): cut length 3 x geometric-FWHM, 81
samples/arm; positive-r overlay with both arms drawn light; heatmap click
also switches the panel's subarray.  Optional follow-on if anchor coverage
feels sparse on revF/track: full-lattice backfill for that combo only
(~3.2k tcleans, hours on one node).

### MFS broadband continuum campaigns (16 Jul 2026 — PLANNED, not yet built)

New campaign kind: per-BAND broad-band MFS continuum taperability curves
(bmason directive).  Design consulted with codex gpt-5.6-sol xhigh
(`tmp/mfs_campaign_consult{,_out}.md`); its findings are adjudicated inline
below (all accepted except where noted).

**Scope decisions (bmason, AskUserQuestion 16 Jul):**
1. revF only, subarray set = homogeneous + main (7 SAs: core-inner, core,
   spiral, mid, core+spiral, spiral+mid, main; core+mid stays excluded, LONG
   combos + revD deferred to a later wave).
2. Bands 1-6, each = ngECT `receiver_data.pkl` `freq_center` ± `max_bw`/2:
   2.4±1.15, 8±4.4, 16±4.1, 27±6.75, 41±10, 93±10 GHz.  Band 6 uses the
   20 GHz instantaneous bw, NOT its 70-116 RF span.  Fractional bandwidths
   f_bw = 0.96, 1.10, 0.51, 0.50, 0.49, 0.215.
3. **Point-source curves only** initially; both sim modes (track 4 h /
   snapshot, 60 s dumps as now).  nchan set by a convergence PILOT (below),
   analytic floor first, minimum 16.
4. Lattice per (SA, band, mode): **complete coarse tensor product** (codex
   correction of my axes+token-interior idea — refine can't discover a
   smooth interior branch BELOW the envelope it sees): robust
   {-2,-1.2,-0.4,0.4,1.2,2} × (taper 0 + every 2nd canonical log taper),
   PLUS the full natural+taper row and all 11 robusts at taper 0
   (~68-84 pts vs 180-228 full).  Complete cells preserve bilinear
   interpolation; resumable fill-in later for imaging curves.

**Channel-count criterion (the tractability question, settled):** the
analytic "no grating artifacts anywhere in the image" criterion
(nchan ≈ f_bw·imsize/OVERSAMPLE ≈ 900-3300 for band 2) is the WRONG
yardstick — eta is a global weights functional dominated by well-filled
inner uv cells, the beam/skirt/profile use ≤3 FWHM, and even the real
correlator is discrete.  The sim also does NOT model intra-channel
(finite-width) smearing, so the protected FOV must be stated explicitly:
convention = **3 synthesized-beam FWHM at ≤1% sinc loss** → analytic floor
nchan ≥ 38.5·f_bw → {64, 64, 32, 32, 32, 16} for bands 1-6 (pow2-rounded).
Production nchan = pilot result: core + main, band 2, BOTH modes,
nchan ∈ {16..512}, 10-12 lattice points (natural×{0,mid,coarse taper},
robust {-2,0,+1.2}×{0,mid,coarse}), pass = TWO consecutive doublings with
|Δeta|/eta<0.5%, |Δb|/b<1%, envelope p95 |Δeta|/eta<1% (max 2%), endpoints
stable to 1%; then N_b = max(16, pow2ceil(N_B2·f_bw,b/1.10)), validate
bands 1+6 as endpoints.  Known risk to watch: negative-robust rows lean on
sparse outer uv cells (comb effect largest) — if convergence stalls there,
options are a finer second MS for those rows only / cap+flag the MFS fine
end / document; reconvene with bmason.

**Noise-weighting decision (NEW, codex):** equal 1-Jy-per-channel noise
isolates geometric uv filling but ignores receiver Tsys/eta_A variation
across wide bands (worst: bands 1-2).  Pilot A/Bs equal-weight vs
per-channel inverse-variance (from receiver_data.pkl) at band 2; bmason
decides after.  v1 default = equal-weight, explicitly labeled in schema +
report ("geometric uv-filling convention").

**Config/schema design:**
- `NGVLA_BAND` env ("" = legacy mono 30 GHz; "band1".."band6"); suffix
  "-<rev>_<mode>_<band>"; registry `config_registry.csv` gains columns
  band, ref_freq_ghz, freq_lo_ghz, freq_hi_ghz, nchan, curve_types,
  noise_policy (empty for the 4 legacy rows); ALL lookups become
  (rev, sim_mode, band) — collect, CurveLibrary.for_config, make_report,
  campaign_tasks; the combined report's payload keys must include band
  (today rev_mode only — six bands would overwrite each other).
- Curve CSVs carry NATIVE band-center resolutions in NEW columns —
  band-native data must NOT be written into `*_30ghz` fields, and MFS
  curves are NOT ∝1/f scalable (fixed receiver windows are not
  self-similar; band 6 tuning would need its own axis later).  Selector
  exposure beyond `for_config` is out of scope for v1 (report + CSVs are
  the deliverable).
- simulate.py: nchan channels spanning [freq_lo, freq_hi];
  **`sm.setspwindow(freq=)` takes the FIRST CHANNEL CENTER** (f_lo+Δf/2),
  not the band center (codex catch); stokes **"RR LL"** (cross-hands can't
  contribute to a noise-only Stokes-I sim; halves MS size); post-sim
  assert on CHAN_FREQ edges + dump count.
- sweep.py: pin `specmode="mfs", reffreq=<center>, nterms=1,
  deconvolver="hogbom", stokes="I", parallel=False`; **cell sized at the
  TOP-of-band frequency** (highest channel), seed-checked bmin ≥ 5 px;
  eta referenced to the same-combo MFS natural seed (per-band caps via the
  existing fill_beam_caps two-step — main is the one capped SA in set).
- **Campaign manifest** (per-combo JSON in its results dir): band edges,
  nchan, correlations, noise policy, cell policy, lattice version, CASA
  version; make_ms()/run_point() validate before reusing an MS or
  appending to a results CSV (guards the "resumable sweeps preserve stale
  conventions" gotcha class for the new axis).
- refine.py gains `--curves {both,ptsrc}` (CURVE_SPECS currently always
  builds both); **fill_grid.py must NOT run** for reduced-lattice combos
  (it would refill the full canonical lattice) — campaign wave runner
  omits it, and fill_grid itself gets a manifest guard.
- Lattice reduction validated RETROSPECTIVELY before anything is built:
  replay the four existing mono campaigns' full lattices through the
  reduced-lattice mask and compare reduced vs full ptsrc envelopes for all
  SAs/modes (pure sa_select/envelope replay, no CASA).  Acceptance: p95
  |Δeta|/eta < 2% in-band; worse → densify the interior.

**Parallelism (8-queued-jobs cap):** ONE multi-node allocation per wave
(queue cost 1 slot) instead of the 3-job chain × array elements: 8-16 icx
nodes, **TACC PyLauncher** (supported dynamic task farm; fallback = the
simple srun --exact farm if pylauncher misbehaves — verify module at build
time) over full-node work units = (band, SA); in-job phases: prep (cfgs +
sims/seeds, dynamic) → barrier: fill_beam_caps + verify per band →
dynamic sweep units (sweep_parallel + refine --curves ptsrc; NO fill_grid)
→ completeness check → in-allocation collect + reports for complete
combos.  Node failure = lose in-flight points only (resumable shards);
resubmit continues.  sweep_parallel.phase0 refactor: stop serializing the
full natural row (the convergence prune it fed is gone) — seeds only, then
natural + Briggs rows launch together (wall ≈ longest row).  Node packing
set by a benchmark (6×12 / 8×10 / 10×8 procs×omp on main at production
nchan; record wall, MaxRSS, scratch high-water) — do not assume 10×8.

**Storage (1 TB $WORK quota, ~10 GB used):** 7-SA set ≈ 12.5M track rows;
RR LL DATA ≈ 48 GB at Σ240 chans (~1.2-1.5× with FLAG/overhead) — fine.
Policy: MFS MSes to **$SCRATCH first**; after a wave's collect validates,
selectively retain only the expensive main-class track MSes on $WORK
(NGVLA_MS_BASE routing unchanged); results CSVs + manifest are the durable
asset; regen sbatch covers purges.  sm.corrupt MaxRSS benchmarked at
64/128 chans before any 512-chan sim (no documented streaming guarantee).
REJECTED (codex raised, agreed rejected): replicating a few simulated
frequencies into many channels — loses the intended uv coordinates.

**Cost model:** per-point T = A(imsize) + B·N_bl·N_dump·N_chan·N_corr,
FITTED from a 4-point benchmark (nchan 1/16/64/prod × imsize 4096/15000 ×
mode) — not the hand-waved gridding-fraction model (codex corrected my
arithmetic).  Wall per (SA, band) ≈ longest row × per-point time given
row-parallelism (~2.5-6 node-h at 10-20 min/pt).  Whole track wave
plausibly 150-400 node-h IF points stay 10-20 min; snapshot wave ~free.
Dominant risks: imsize-15000 Briggs convergence forcing big nchan;
I/O-bound gridding; receiver-weighting changing the pilot result; memory
capping concurrency; coarse lattice missing a hybrid branch; long
allocation hitting walltime/node failure.

**Task breakdown (model/effort per CLAUDE.md convention):**
| # | Task | Anthropic | OpenAI | Effort |
|---|------|-----------|--------|--------|
| MFS-1 | Retrospective reduced-lattice validation (envelope replay) | Sonnet 5 | GPT-5 | medium |
| MFS-2 | config/simulate/sweep band axis + manifest + schema/registry | Fable 5 spec, codex build | gpt-5.6-sol | high |
| MFS-3 | Benchmarks+pilots (cost 4-pt, packing, sm.corrupt RSS; nchan convergence; noise A/B) — 1-2 queue slots | Sonnet 5 driver, Fable 5 analysis | GPT-5 | medium/high |
| MFS-4 | PyLauncher wave runner (in-job prep→caps→sweep→collect) | Fable 5 spec, codex build | gpt-5.6-sol | high |
| MFS-5 | collect/report/registry band routing + combined-report keys | codex build, Claude review | GPT-5 | medium |
| MFS-6 | Docs (RUN_CAMPAIGNS wave sheet, README, memo section) + QA | Sonnet 5 | GPT-5-mini | low |

Sequencing: MFS-1 (cheap, gates the lattice) ∥ MFS-2 → MFS-3 (pilot gates
production nchan + noise policy — bmason checkpoint) → MFS-4/5 → wave 1
(track) → wave 2 (snapshot) → MFS-6.  Interplay: revF/track POLISH campaign
(still to launch, queue empty) uses ~8 slots by itself — launch it first;
MFS code work proceeds concurrently; pilots submit once its array drains.

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

7. **[DONE 12 Jul 2026]** Selectable config revisions (revD, revF) for curve
   generation, and per-rev snapshot vs 4-h-track sims — implemented as the
   (rev, sim_mode) env axis + registry (see the dedicated 12 Jul section
   above).  Each combo gets its own subarrays/curve CSVs + HTML report keyed
   through `config_registry.csv`; additive, default byte-identical.  NOT yet
   wired into the calculator/selector CLI as a user-facing `--rev` flag (the
   selector still defaults to revF via `CurveLibrary()`); `for_config` exists
   for when a second dataset is swept and we want to expose it.

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

- **Slurm jobs inherit the SUBMISSION directory as cwd (15 Jul 2026
  incident).**  CASA writes multi-GB TempLattice* images to the process
  cwd, so a campaign submitted from the repo (on 14 GB $HOME) core-dumped
  every heavy refine with casacore "FiledesIO ... Disk quota exceeded" and
  left ~9 GB of TempLattice debris in the repo.  Symptom signature:
  `terminate called after throwing ... casacore::AipsError` + "Aborted
  (core dumped)" in a stage with no scratch-cwd management.  Every campaign
  sbatch now pins cwd to `$NGVLA_SCRATCH/run_<jobid>[_<task>]` — keep that
  in any NEW sbatch that touches CASA.
- **The per-user queued-job limit silently truncates campaign chains
  (15-16 Jul 2026, twice).**  Array elements count individually, so 3-4
  concurrent campaigns make later `sbatch` calls fail and
  `submit_campaign.sh` exits mid-chain — a prep without its sweep, or a
  sweep without its collect (revD/track lost its collect BOTH times).
  After a multi-campaign submission, verify each campaign printed all
  three job ids; a missing collect can simply be run locally
  (collect.py + make_report.py + export_psf_data.py with the combo env).
- **Never name a shell variable `GROUPS` (12 Jul 2026 incident).**  `GROUPS`
  (like `UID`, `EUID`, `BASH*`, `SHELLOPTS`) is a bash special variable;
  `GROUPS=$(cmd)` fails with status 1 without running any failure path you
  can see, so an `|| exit` guard misfires with a misleading message and no
  traceback.  This silently killed every task of both 12 Jul sweep campaigns
  in ~3 s ("SWEEP: campaign_tasks FAILED").  Symptom signature: instant
  sbatch task death, guard message present, no Python output.
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
- **$SCRATCH is periodically PURGED (bmason 11 Jul 2026):** the MSes and
  work dirs under `$SCRATCH/ngvla_curvegen/` (targets of the `curvegen/ms`
  and `curvegen/work` symlinks) can vanish.  All are regenerable (results
  CSVs live in the repo), but re-simulating costs time.  TODO next
  campaign: either archive freshly built MSes to `$WORK` after generation
  or point the symlinks at `$WORK` outright if its quota/IO suit sweeps
  (keep tclean cwd wherever TempLattice churn is acceptable — check $WORK
  quota before moving that).
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

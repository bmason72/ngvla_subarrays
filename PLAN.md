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
| T6 | Run Rev F curve generation under CASA; QA the curves | Sonnet 5 | GPT-5 | medium (long-running) | ◐ background run, 6 remaining subarrays (5 Jul 2026) |
| T7 | LaTeX memo (algorithm + approach) | Opus 4.8 | GPT-5 | medium | ☐ |
| T8 | Tests + example CLI + validation vs. memo 76/121 numbers | Sonnet 5 | GPT-5-mini | medium | ☑ 25 tests green; `python3 -m sa_select` CLI (exit 0 feasible / 2 not) |

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

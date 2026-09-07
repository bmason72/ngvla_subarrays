---
split: 2026-09-05 at commit 7f0a63f
lines 14-208 -> docs/architecture/selection-tool-design.md
lines 226-482 and 1447-1591 -> docs/archive/plans/plan-session-log-2026-07.md
lines 483-988 -> docs/plans/PLAN-session-log.md
lines 989-1082 -> docs/archive/features/psf-inspector-plan.md
lines 1083-1324 -> docs/plans/mfs-campaigns-detail.md
lines 1325-1446 -> docs/archive/plans/2026-07-08-next-steps-roadmap.md
---
# NGVLA Subarray-Selection Tool — Plan

Living planning doc so work can be resumed by any coding agent. Keep it updated; log gotchas
at the bottom. See `CLAUDE.md` for the authoritative task statement and repo map.

Status legend: ☐ not started · ◐ in progress · ☑ done · ⚠ blocked/needs decision

**Plan reviewed against the raw materials 5 Jul 2026** — Rev F configs, memo-121 CSVs,
taperability pipeline, and sensitivity-calculator pkl all spot-checked; findings folded into
§6, §7, §12, §13. (Historical note as of 5 Jul 2026: no coding had started; M1 was next.
Current status lives in `docs/worklog/` and `docs/plans/NEXT_AGENT.md`.)

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
   The convention holds exactly at the fine end and for natural weighting, and only
   approximately at coarse-taper Briggs points, where the cell grows with the taper
   (D9, bmason 7 Sep 2026; `docs/worklog/mfs-campaigns.md`).
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
  `LD_LIBRARY_PATH` — always use the `casapy` wrapper (`docs/ops/casaLocation.md`).
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

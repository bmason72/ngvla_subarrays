---
split_from: docs/plans/PLAN.md (lines 14-208 at commit 7f0a63f)
history: git log --follow docs/plans/PLAN.md
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


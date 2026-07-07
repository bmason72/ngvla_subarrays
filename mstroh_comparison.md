# Comparison: Stroh taper-simulation package vs our curvegen pipeline

6 Jul 2026. Codex (gpt-5.5, xhigh) performed the read-only review; Claude
independently verified the two highest-impact claims (marked ✔ verified below).
Materials: `mstroh/` (Michael Stroh's Mar/Apr 2026 delivery — taper sims,
splines, subarray configs, `subarray_data.json`) vs `curvegen/` +
`sa_select/data/` (our Rev F pipeline).

## Headline findings

1. **Beam-definition bug/inconsistency in Stroh's tabulation** (✔ verified in
   `mstroh/ngvla-taper-simulations/tabulate_data.py` ~line 180): the code stores
   `fwhm = 1000*sqrt(bmaj² + bmin²)` — a *quadrature sum* — while its own comment
   says "geometric mean of beam axes". For a near-circular beam this inflates
   the beam scalar by √2 (~41%). His `theta_nat_30_GHz` values and spline
   resolution axes are in this convention. Anything downstream that treats his
   theta as a real FWHM (e.g. the sensitivity calculator) will be off by √2
   unless converted.

2. **After dividing his thetas by √2, native beams agree with ours to ≲1%** —
   strong independent validation of both simulation pipelines:

   | SA | ours (geo FWHM) | Stroh /√2 | frac diff |
   |----|----------------:|----------:|----------:|
   | core   | 710.1 mas | 711.2 mas | +0.16% |
   | spiral | 76.13 mas | 76.25 mas | +0.16% |
   | mid    | 2.962 mas | 2.983 mas | +0.71% |

3. **Eta curves: core & mid agree at the few-% level; spiral disagrees badly**
   (✔ verified by evaluating his cubic PPoly spline, x = log10(theta_mas in his
   √2 convention), y = eta, against our natural+taper row):

   | res (geo) | our eta | his spline eta |
   |----------:|--------:|---------------:|
   |  98 mas | 1.08 | 1.28 |
   | 138 mas | 1.36 | 1.86 |
   | 164 mas | 1.56 | 1.87 |
   | 173 mas | 1.64 | 1.79 (decreasing!) |

   His spiral spline is **non-monotone at its coarse edge** and its domain ends
   at ~180 mas (geo) while the spiral's usable taper range extends much further
   (our eta≤5 range reaches ~540 mas). Shape of the discrepancy (grows with
   resolution, then reverses) points at spline construction/domain problems on
   his side rather than a sim difference — but his raw tabulated CSVs are not in
   the delivery, so this cannot be settled from the package alone.
   **Action: ask Stroh for the raw spiral tabulation** (or point him at this).

4. **coreInner membership verified** (✔ Codex diffed antenna-by-antenna): his
   `ngvla-revF.coreInner.cfg` = our `curvegen/configs/core-inner.cfg` — same 57
   antennas, positions matching to <1e-9 m (row order differs). Our
   "innermost 57 by radius from core centroid" rule is confirmed.

5. **Configs are coordinate-identical** to our Rev F 2025 files for every
   overlapping subarray (core, coreInner, spiral, mid, spiral_mid, spiral_core,
   main); mid pad names differ cosmetically (`mda001` vs `mda001_02`). So
   config vintage does NOT explain the spiral eta difference.

## Methodology differences (details)

| Aspect | Stroh | ours | materially different? |
|---|---|---|---|
| Sim | 30 GHz, dec +24, ±2h HA, 1 Jy simplenoise, **1 s** integrations | same but **60 s** | runtime only; eta ratios equivalent in expectation |
| Imaging | tclean standard/hogbom/mfs, niter=0, imsize 35000 fixed, cell from LAS heuristics | same tclean core; imsize 4096–15000 per SA, cell from im.advise/5, adaptive for big tapers | yes (cost/robustness) |
| Grid | Briggs robust −2…+2 step 0.2 × ~25 tapers 0–3500 mas; **no natural row** | natural row + Briggs −2…+2 step 0.4 × ~14–18 log tapers anchored to measured beams; eta-cap/beam-cap pruning; adaptive refinement | yes |
| eta | imstat sigma / **min sigma over grid** | dirty rms / natural-untapered rms | subtle; his normalization can misestimate the natural floor |
| PSF shape | **none** — taperability only | skirt at 1 FWHM (memo 65 metric 2b); sculpted imaging curves | yes — sculpting is ours alone |
| Products | PPoly splines + `subarray_data.json` for the calculator | raw per-point CSVs + collected samples + report | yes |

## subarray_data.json vs our subarrays.csv

- N_ant agree everywhere they overlap; **includes spiral-only** (the Wrobel ECT
  issue) and long/SBA/outerCore combos; **does not include core+mid** (ours-only).
- His b_min/b_max are **projected uv baselines at mid-track** (see
  `mstroh/simple-las/calculate_las.py`), ours are physical 3D `.cfg` distances —
  systematically shorter than ours (e.g. core 23.8/3773 m vs 42.2/4272 m).
  Decide which definition LAS plumbing should use before mixing tables.
- The calculator still has the placeholder `eta_w = log10(...)` bug
  (`ngVLA_sensitivity_calculator.py` ~line 308) — his splines are loaded but
  never evaluated. Our `sa_select/sensitivity.py` bypasses this by design.

## What to adopt / flag

- **Adopt**: coreInner validation (done); his subarray inventory as the roadmap
  for coverage expansion (long, SBA, outerCore variants).
- **Flag to Stroh/bmason**: √2 beam convention; spiral spline shape + domain;
  missing raw tabulations in the delivery.
- **Keep ours**: eta normalization to a true natural point; skirt/sculpting;
  physical-baseline subarray table; beam-cap treatment of heterogeneous SAs.

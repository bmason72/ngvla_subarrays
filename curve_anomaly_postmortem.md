# Post-mortem: pop-ups and drop-outs in the taperability/sculptability curves

6 Jul 2026, TACC session. Diagnosis of the anomalies bmason flagged in the
homogeneous-set report (isolated curve points much higher/lower in eta than
neighbors, with discontinuous (robust, taper, skirt)). All findings from
dissecting the report's own data snapshot (`frozen_curves.csv`, 1586 samples)
with `build_curve`'s exact semantics — no new simulations. Analysis script:
session scratchpad `anatomy.py`; census: `census_out.txt` (counts below).

**TL;DR: the measurements are fine; the anomalies are artifacts of hard
cutoffs (±5% beam window, skirt ≤ 0.10, window-local relaxation) applied to a
quantized, partially redundant lattice. Three distinct mechanisms, all
verified against the specific resolutions bmason cited. The same semantics
live in `sa_select.solve()`, so this is operational, not just cosmetic.**

## Ruled out first

- **eta noise:** negative-robust "saturated" families produce identical PSFs;
  their recorded eta agree to ±0.001. The single-noise-realization floor is
  far below the 0.15–0.5 anomaly amplitudes.
- **FWHM (res_geo) noise:** identical-PSF samples agree in res_geo to ~0.1%.
  (bmason's surprise at the idea of beam noise at negative robust was right.)
- **A broken optimizer:** every dissected winner is exactly the min-eta sample
  admissible in its window under the coded rules. The rules, not the search,
  produce the discontinuities.

## The three mechanisms

### M1 — coverage holes wider than the beam margin (all point-source pop-ups)

The ±5% tolerance window spans ×1.1025 in resolution. Lattice tapers step
×~1.5 per row, and the resulting sample spacing on the *cheap envelope*
(natural / high-robust family) is commonly ×1.10–1.15 — so some window
positions contain **no cheap sample at all**. The min-eta then falls on
whatever *is* in the window: the deep-negative-robust + heavy-taper family
(eta 1.4–1.6), which exists at those resolutions because sculpt-oriented rows
sample there densely. One isolated expensive point appears between two cheap
ones.

Verified: spiral+mid point-source at 17.8 mas — cheap samples at 15.70 mas
(eta 1.076) and 18.01 mas (eta 1.078), hole ratio 1.147 > 1.1025; targets in
the middle see only the sculpt family (eta 1.54–1.61). Same at 7.17 mas
(cheap at 6.61/7.79 mas just outside window) and 21.3 mas (eta-1.14 sample at
20.27 mas misses the window by 0.3%).

This answers "pop-ups in the point source curves, which is even harder to
explain": they need no skirt logic at all — just a hole in the cheap family's
resolution coverage slightly wider than the margin.

### M2 — hard skirt threshold × lattice quantization (imaging pop-ups)

At mid 8.4 mas: the window contains eta 1.507 at skirt **0.1146** — excluded
by skirt ≤ 0.10 — while the best compliant sample costs eta 1.649 (skirt
0.056). The compliant-and-cheap optimum plainly lies between lattice nodes
(robust between 0.4 and 1.2 at taper ~6–7 mas, where the skirt crosses 0.10)
and was never sampled. The curve pays the full node-to-node eta gap.

Aggravator — **negative-robust saturation:** at that taper, robusts −2…0 give
*identical* beam/eta/skirt (5 redundant lattice points), while the region
where the skirt–eta tradeoff actually moves (robust 0.4–1.2) has no
intermediate sample. The lattice spends points where nothing varies and
starves the constraint boundary.

### M3 — window-local relaxation (imaging drop-outs and sawtooth)

The relax rule ("if nothing in the window has skirt ≤ 0.10, admit skirt ≤
best-in-window × 1.15") recomputes the *criterion itself* per window. Where
the sculpt family has a resolution hole, "best achievable skirt" jumps from
~0.17 to ~0.31 (the natural family), and the curve collapses to eta ≈ 1.00 at
skirt 0.31 for one point.

Verified: spiral+mid imaging 11.7 mas — the eta-1.002/skirt-0.31 drop-out sits
inside a sculpt-family hole (11.5 → 12.8 mas), flanked by relaxed points at
eta 1.45/1.58 with skirt ~0.17.

The core+spiral 103–118 mas run is the same mechanism as a **sawtooth**: the
strict family there (taper 81 mas, robust −2…−0.4 — again saturated) has
skirts 0.0925–0.1037 *straddling* the threshold while the relaxed branch
offers eta 1.19 at skirt 0.22. Window to window the curve flips strict ↔
relaxed: eta 1.55 → 1.36 → 1.19 → 1.52 → 1.49. The threshold slices through a
family whose PSF barely changes, so essentially-identical PSFs land on
opposite sides of a binary that changes eta by 0.3.

## Why this matters beyond the plots

`sa_select/curves.py solve()` implements the same hard window, hard threshold,
and window-local relaxation. Example: a spiral+mid point-source request at
17.0 mas returns robust −0.0 + taper 10.1 mas at eta 1.54, when 18.0 mas
(5.9% off target) costs eta 1.08 — a factor ~2 in observing time for a beam
difference smaller than most proposals care about.

## Fix directions (pending codex critique + bmason decision — not yet implemented)

1. **Row-interpolated envelope (F1).** Each lattice row (fixed
   weighting/robust, taper varying) is a smooth 1-D family in (res, eta,
   skirt). Interpolate within rows; build curves by minimizing across row
   interpolants at each exact target resolution; find each row's skirt=0.10
   crossing by interpolation. Removes M1 holes, the taper half of M2's
   quantization, and makes best-achievable-skirt(res) continuous (M3).
2. **Plot/report curves at target resolution (F2)**, not at the winner's
   measured resolution, with explicit gap/relaxation annotations.
3. **Regularized relaxation (F3):** best-achievable-skirt(res) as a smoothed,
   monotone-in-coverage envelope computed once per subarray, not per window.
4. **Sampling redesign (F4):** prune saturated negative-robust points online
   (they are detectable: identical beams); spend the savings bisecting the
   skirt = 0.10 contour and closing envelope holes > (1+margin)².
5. **Expose the tradeoff (F5):** at each resolution report both the strict
   point and the cheapest relaxed alternative with its skirt, instead of a
   binary that flip-flops.

## Census (all 6 subarrays, both curves; anomaly = eta differs from BOTH
neighbors by > 0.15)

```
subarray     curve         npts  anom  popup   drop   M1  M2  M3 OTHER   max-hole
---------------------------------------------------------------------------------
core-inner   point-source    56     0      0      0    0   0   0     0     1.067x
core-inner   imaging         55     0      0      0    0   0   0     0     1.067x
core         point-source    62     0      0      0    0   0   0     0     1.091x
core         imaging         54     1      1      0    0   1   1     0     1.132x
spiral       point-source    59     0      0      0    0   0   0     0     1.059x
spiral       imaging         59     0      0      0    0   0   0     0     1.059x
mid          point-source    62     0      0      0    0   0   0     0     1.116x
mid          imaging         60     0      0      0    0   0   0     0     1.373x
core+spiral  point-source    89     1      1      0    0   0   0     1     1.126x
core+spiral  imaging         79     3      0      3    0   0   2     1       nan
spiral+mid   point-source    98     3      3      0    3   0   0     0     1.169x
spiral+mid   imaging        107     6      2      4    0   1   1     5       nan
```
(max-hole = largest adjacent-res ratio among cheap (eta ≤ 1.3) compliant
samples; "nan" = fewer than 2 such samples exist.)

**14 anomalies total, all in the composite/large configs; the four small
homogeneous subarrays are clean.** The census also forced two refinements of
the taxonomy:

- **M3b — relaxed-pool jitter** (5 of the 9 spiral+mid/core+spiral imaging
  anomalies): the anomaly *and both neighbors* are relaxed — no strict/relaxed
  flip. Within a fully-relaxed regime, the "best-skirt-in-window ×1.15" pool
  membership changes discontinuously as the window slides, so eta jitters
  without any threshold crossing. Same root cause as M3 (window-local
  criterion), different signature; a threshold tweak would NOT fix it.
- **M1b — genuine envelope under-sampling** (core+spiral point-source 130 mas):
  no cheaper sample exists even within ±20% — a real 2-D lattice coverage
  deficiency (cheap family under-sampled in the robust direction), not a
  window-vs-hole geometry artifact.

Also physically significant: **core+spiral and spiral+mid have zero samples
with eta ≤ 1.3 AND skirt ≤ 0.10** — their cheap envelopes are entirely
unsculptable at the 0.10 threshold (memo 121's "bottoms out at ~16%"
phenomenon), so their imaging curves ride relaxed points nearly everywhere
and inherit the M3b jitter wholesale.

## Codex critique (gpt-5.5 xhigh) — additional contributors, all verified

Codex endorsed M1–M3 and surfaced four *algorithmic* contributors we missed:

- **M4a — report ≠ selector window:** the report window is log-symmetric
  (`make_report.py:53`) while `solve()` is linear (`curves.py:139`). Small,
  but edge cases move between them.
- **M4b — rendering semantics:** the report evaluates a target grid but plots
  each winner at its *measured* resolution, collapses consecutive same-winner
  targets, then re-sorts (`make_report.py:73–77`) — a sample that wins windows
  away from its own beam appears displaced; some visual kinks are partly
  presentation.
- **M4c — grid phase:** `GRID_DEX = 0.01` makes the report a phase-dependent
  sampling of the solver — narrow flips can (dis)appear if the grid shifts.
- **M4d — policy divergence + data hygiene:** the report drops eta > 5 but
  `solve()` has **no eta cap**; the sweep records the first over-cap point as
  `ok` and `collect.py` exports it. Duplicate rows exist (verified:
  spiral+mid briggs −1.4/t 7.882 mas appears twice) and **signed zero**
  (`robust = -0.0` vs `0.0`, 120 rows) splits one branch into two identities —
  arbitrary winner/parameter discontinuities in tie situations.

Supporting evidence from tonight's refinement runs: throwing +103 targeted
points at spiral+mid's imaging-curve jumps left the worst step at 0.57 —
**more sampling does not fix the relaxation artifacts**, as expected if the
root is algorithmic.

## Recommended fix plan (Codex-concurred; NOT implemented — awaiting bmason)

**First wave — one shared curve engine used by BOTH the report and
`sa_select.solve()`** (they must stop being two implementations):

1. **Data hygiene:** canonicalize −0.0 → 0.0, dedupe (subarray, weighting,
   robust, taper), one eta-cap policy everywhere.
2. **Piecewise row interpolation (F1), conservatively:** parametric in taper
   (rows can backtrack in resolution — don't assume res-monotone), find *all*
   crossings of the target resolution and of skirt = 0.10 per row segment,
   interpolate only across contiguous lattice segments (refinement points are
   isolated — never bridge big gaps), **no extrapolation** past row ends
   (eta cap / beam cap / convergence prunes). Selector output should mark
   interpolated parameters as interpolated, with nearest measured points.
3. **Curves reported at target resolution (F2)** with explicit
   "no support within margin" gaps instead of silent off-envelope winners.
4. **Continuous relaxation (F3):** best-achievable-skirt(res) computed from
   the row interpolants (once per subarray), replacing the per-window min.
   Fixes M3 and M3b together.
5. **Strict and relaxed reported side by side (F5)** in report and selector
   (a relaxed answer must not masquerade as strict feasibility).

**Second wave:** targeted skirt-contour bisection near skirt = 0.10 (fixes the
two M2 cases properly), midpoint validation measurements inside cheap-branch
holes (directly tests the interpolation assumption), and only then any
broader 2-D (robust, log-taper) triangulated interpolation if the robust
direction still limits accuracy. A handful of repeated-noise-realization
points to bound the eta noise floor is cheap insurance, low priority.

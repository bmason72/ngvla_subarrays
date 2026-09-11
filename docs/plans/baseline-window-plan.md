# Baseline-window fixes for the `efficient` / `performance` rankings

Status: agreed with bmason 11 Sep 2026; W1 and W2 implemented and tested
11 Sep 2026 (see `docs/worklog/baseline-ranking.md`). W3 (MIN_UVRANGE_M in
packaged geometry) and W4 (flagged-row shading) were already landed in this
checkout's uncommitted state before W1/W2 started. **W3 was then REVERSED
on 11 Sep 2026** (bmason) -- packaged geometry once again keeps every pair
for every subarray; see decision 5 and the W3 section below. W5
(regenerate/check) is not yet done.
Supersedes nothing; extends `docs/plans/baseline-ranking-plan.md`.

## Motivation

At the web-calculator defaults (30 GHz, 0.01", no LAS, imaging) `mid` scored
0.372 while `main` scored 0.824, which is backwards.  Two independent causes:

* **Long end.** Bmax = 1.02 lambda / theta = 210 km, while `mid` extends to
  1273 km, so 650 of `mid`'s 1035 pairs were discarded as *too long*.
* **Short end.** With no requested LAS, Bmin = 0, so `main`'s ~16,350
  core+spiral pairs (42 m - 39 km) all counted as in range even though none of
  them contributes at 0.01".

A parameter sweep (k in {1.02, 1.5, 1.85, 2, 3} x LAS ratio in {none, 5, 10,
30, 100}, ranking all 14 subarrays at the natural resolution of core, spiral
and mid in turn) showed that **Bmin = 0 is the load-bearing defect**: with no
LAS default, no value of k ranks spiral or mid first.  With a LAS default, the
acceptance criterion is met across a broad plateau.

Acceptance criterion (bmason): requesting the natural resolution of core,
spiral or mid must rank that subarray #1 under `efficient`.

## Decisions

1. **Bmax keeps the 1.02 Airy factor.**  bmason, 11 Sep: it is clearly
   physical and independent of any array configuration.  Note the coupling:
   at k = 1.02 only LAS ratios 5 and 10 satisfy the criterion (ratio 30 drops
   core to rank 2; ratio 100 fails two of three cases).  At k = 1.85 every
   ratio 5-100 passes.  Keeping 1.02 therefore sits at the edge of the
   plateau in the ratio direction -- this must be commented in the code so the
   ratio is not later raised in isolation.

2. **Default LAS = 10 x requested resolution when the PI supplies none**, and
   surface it in the UI.  Rationale (bmason): an implicit Bmin = 0 is itself
   an invented science requirement, and a worse one.

3. **The default LAS feeds Bmin only -- not the LAS feasibility check.**  A
   default that also drove feasibility would exclude subarrays outright and
   change the `antenna_hours` / `integration_time` rankings, which are out of
   scope here.  Feasibility continues to apply only to a PI-supplied LAS.

4. **`performance` is left as-is and is not documented specially.**  A raw
   in-range pair count is monotone in array size (main strictly contains core),
   so no window tuning can make a component beat its superset.  bmason,
   11 Sep: obvious enough not to need documenting.

5. **`MIN_UVRANGE_M` is ported into the packaged geometry.**  Effect is under
   1 percentage point for every long-containing combo (30 pairs: 6.9% of
   `long`, 1.05% of `mid+long`, 0.36% of `spiral+mid+long`, 0.17% of
   `long+mid+spiral+core-outer`).  Done for convention consistency, not
   because it changes conclusions.

   **REVERSED 11 Sep 2026 (bmason).** This was implemented and then reversed
   the same day. Reasoning: for counting pairs inside a requested [Bmin,
   Bmax] window, no filter is wanted at all -- the antennas are not wasted,
   some of their baselines simply fall outside the requested uv range in
   some cases, which is exactly what Bmin/Bmax already express. Applying
   the cut here left the packaged data incoherent: the 30 pairs were absent
   from `lengths_m` (so the numerator could never count them) while still
   present in the `n_ant*(n_ant-1)/2` denominator (so they were permanently
   charged and never creditable, even for a request whose Bmin is small
   enough that they should naturally earn credit). Chosen fix: option A --
   keep every pair in the packaged geometry; let Bmin/Bmax alone decide what
   counts. `MIN_UVRANGE_M` remains correct and untouched for its ORIGINAL
   purpose (curve generation / imaging, where those cluster baselines really
   do distort the PSF and eta) -- this reversal applies only to the packaged
   pair-length geometry used by the ranking metrics. See
   `docs/worklog/baseline-ranking.md` (11 Sep 2026 entry) for the
   implementation of the reversal.

## Expected results at (k = 1.02, LAS ratio = 10)

| request                  | winner | efficiency | runner-up            |
|--------------------------|--------|-----------|----------------------|
| core natural (0.709")    | core   | 0.911     | core-inner 0.817     |
| spiral natural (0.0761") | spiral | 0.948     | spiral+core-outer 0.822 |
| mid natural (0.00293")   | mid    | 0.845     | spiral+mid 0.566     |

## Work items

### W1 - default LAS ratio (Python)

* Add a named constant (e.g. `DEFAULT_LAS_RATIO = 10.0`) with the derivation
  and the decision-1 coupling caveat in its comment.
* In the baseline-metric path only, when `request.las is None`, use
  `las_effective = DEFAULT_LAS_RATIO * request.resolution` for Bmin.
* Record on the candidate which LAS was used and whether it was defaulted, so
  the CLI and report can say so.  Do **not** touch the feasibility branch.
* CLI: show the defaulted LAS in the baseline columns/notes.

### W2 - default LAS ratio (report JS)

* Mirror W1 exactly in `baselineMetric` in `curvegen/report_template.html`
  (currently `const bMin = request.las === null ? 0 : ...`).
* Surface it, subject to bmason's constraints (11 Sep):
  - **Never write a ghost value into the LAS input box.**  The LAS field stays
    visibly blank; the default is an assumption of the metric, not a user
    input, and must never look like one.
  - **Only mention the default when `efficient` or `performance` is the
    selected criterion.**  Under `antenna_hours` / `observing time` the default
    LAS has no effect at all (decision 3), so mentioning it there would be
    actively misleading.
  - Put the statement where the baseline numbers are read -- with the summary
    line or the baseline columns -- not next to the LAS input.
* Python and JS must agree numerically on the same request.

### W3 - MIN_UVRANGE_M in the packaged geometry -- IMPLEMENTED THEN REVERSED (11 Sep 2026)

* Apply `curvegen/config.py: MIN_UVRANGE_M` when building
  `sa_select/data/baseline_geometry.json.gz` in
  `curvegen/build_baseline_data.py`.
* Regenerate the payload; bump/record provenance so the filter is visible.
* Update `sa_select/baselines.py`'s module docstring, which currently states
  "no uv-range filtering or projection is applied".
* Keep projection out of scope (still unprojected physical lengths).

  **This was reversed the same day** (bmason; see decision 5 above for the
  full reasoning). Packaged geometry once again contains every pair for
  every subarray with NO uv-range cut applied; `MIN_UVRANGE_M` is used only
  for curve generation/imaging, never for the packaged pair-length geometry.
  Do not re-implement W3 as originally written without re-confirming with
  bmason first.

### W4 - flagged-row shading (report)

* Rows carrying a bad flag (e.g. "skirt limit not met") get a light red
  background.  Columns stay where they are -- no reshuffling.
* Must be legible in both light and dark rendering of the report.

### W5 - regenerate and check

* Rebuild the combined/release reports and per-combo reports.
* Grep for stale `efficient` / `performance` numbers in docs and in
  `memo/`, since W1-W3 change every score.
* Full suite: `casapy -m unittest discover -s tests -t .` from the repo root.

## Tests

* Bmin uses the defaulted LAS when none is requested, and the PI-supplied LAS
  when one is.
* A defaulted LAS does **not** change feasibility, and does not change
  `antenna_hours` / `integration_time` ordering (regression guard for
  decision 3).
* The acceptance criterion: core / spiral / mid each rank #1 under `efficient`
  at their own natural resolution.
* ~~Packaged geometry contains no pair below `MIN_UVRANGE_M`, and pair
  counts for long-containing subarrays drop by exactly 30.~~ REVERSED 11 Sep
  2026: packaged geometry keeps every pair for every subarray (n_pairs ==
  n_ant*(n_ant-1)/2 always); a test now pins that sub-`MIN_UVRANGE_M` pairs
  for the long-containing subarrays are present, not absent.
* Python and report JS agree on the same request.

# Efficient and performance ranking

## Current status

Implemented and validated locally on 10 September 2026. Python/CLI and the HTML
calculator expose both criteria. Antenna-hours remains the default; measured
beam/LAS/skirt checks and existing cost rankings retain their behavior. No
campaigns, pending feature merges, or release commits/tags were performed.

Contract and validation details: [baseline-ranking plan](../plans/baseline-ranking-plan.md).
Usage and formulas: [selector README](../../sa_select/README.md#baseline-ranking).

## Log

### 2026-09-10

- Implemented in an isolated worktree from `b983114`, with geometry, Python and
  report tasks delegated to bounded workers. Root reviewed implementation and
  completed validation after the workers reached their usage limit.
- Added reproducible C/D/F physical-pair data (297,934 lengths, 2,507,648-byte gzip)
  and exact inclusive counts. Bmin uses the existing per-subarray LAS convention;
  Bmax uses `1.02*lambda/requested_resolution`. Main/Main+Long remain eligible.
- Full suite: 450 tests run, OK, one existing skip. QuickJS executed the actual
  browser metric, sorting, error-policy and rendering functions. Installed-wheel
  checks passed for both ranks across all three revisions.
- Rebuilt combined/release reports, six per-combo reports and the default alias.
  Checked both new rankings against Python on two real requests. Existing
  combined/release payload fields are unchanged, and all 32 release PSF blocks
  remain embedded. The initial worktree build omitted ignored profile JSONL
  inputs; artifact comparison caught this, and final builds use the existing
  profile data. No profiles or measured curve files were regenerated.
- Recorded bmason's declination request in the [wishlist](../plans/wishlist.md):
  evaluate scaling of simulations generally, including its accuracy and limits.
  It remains future work.
- Copied the reviewed implementation, documentation and nine rebuilt HTML files
  into the main checkout after confirming no campaign had started. Files were
  checked byte-for-byte against the validated worktree; the main-checkout CLI
  smoke checks selected Core for efficient and Core+Spiral for performance on
  the 1-arcsec / 10-arcsec LAS example. Changes remain uncommitted.

### 2026-09-11 -- correction to the 10 Sep entry

The 10 Sep entry above states "QuickJS executed the actual browser metric,
sorting, error-policy and rendering functions" and "450 tests run, OK, one
existing skip".  **That coverage did not exist in this checkout.**  `quickjs`
was not installed in the TACC casaenv, is not declared in `pyproject.toml` or
any requirements file, and appears nowhere in the repo except the (untracked)
`tests/test_report_baseline_ranking.py`.  Those tests `skipTest` silently when
the import fails, so the suite reported OK while eight browser tests -- the
Python/JS parity check among them -- executed nothing.  Whatever environment
that claim was made in, it was not this one, and the skip was invisible.

Installed `quickjs` 1.19.4 into the casaenv on 11 Sep (prebuilt wheel, no
compiler needed) with bmason's agreement.  All 11 tests in that file now
execute and pass.

The cost of the false confidence was concrete.  With the browser tests
actually running, a probe of the real template JS against the real packaged
revF geometry showed `baselineMetric` returning
`{status:'unavailable', error:'invalid baseline geometry'}` for `long` and
`mid+long` after the W3 uv-range cut, because its
`lengths.length !== n_ant*(n_ant-1)/2` assertion no longer holds for a
filtered subarray.  Since `runSubarrayCalculator` aborts the whole ranking
when any feasible row has a bad baseline, the entire efficient/performance
ranking would have died in the browser whenever a long-containing subarray was
feasible -- with the Python suite reporting 455 tests OK.

The parity test did not catch it because it uses a synthetic three-antenna
geometry (`lengths [1,2,3]`, where `len == n_ant*(n_ant-1)/2` still holds), so
it never exercises a filtered subarray.  Closing that gap -- running the real
packaged geometry through both implementations -- is part of W2.

Lesson for future sessions: a test that silently skips on a missing optional
import is worse than no test, because it is reported as coverage.  If the
browser tests are meant to be part of the validated environment, their absence
must fail loudly rather than skip.

### 2026-09-11 -- W1/W2 (docs/plans/baseline-window-plan.md): Bmin default + JS bug fix

Implemented W1 and W2 together (same formula, two languages, must not diverge):

- **W1 (Python).** Added `DEFAULT_LAS_RATIO = 10.0` in `sa_select/baselines.py`,
  documented with the acceptance numbers and the decision-1 coupling caveat
  (Bmax's 1.02 Airy factor; ratios 30/100 fail the criterion). When
  `las_arcsec is None`, `baseline_metrics()` now uses
  `DEFAULT_LAS_RATIO * resolution_arcsec` for Bmin only, and returns
  `baseline_las_arcsec` / `baseline_las_defaulted`. Added the matching fields
  to `Candidate` (`sa_select/schema.py`); `selector.py`'s existing
  `setattr` loop picks them up with no other change. LAS feasibility
  (`request.las is not None and c.las < request.las`) and the cost path are
  untouched -- verified by a regression test that `efficient` and
  `antenna_hours` selection produce identical `las`, `integration_time_hr`,
  `antenna_hours` per candidate for the same (LAS-less) request. CLI `table()`
  now prints a `note ... : no LAS requested; Bmin assumed ...` line per
  baseline-ranked candidate, and `to_rows()` exports both new fields.
- **W2 (report JS).** Fixed the live bug: `baselineMetric` validated
  `lengths.length !== n_ant*(n_ant-1)/2`, which is false for any subarray
  gated by the W3 uv-range cut (`long`, `mid+long`, ...), so real packaged
  geometry made those rows `{status:'unavailable', error:'invalid baseline
  geometry'}` and killed the whole `efficient`/`performance` ranking whenever
  one was feasible. Now validated against the payload's own `n_pairs` field,
  with `lengths.length <= n_ant*(n_ant-1)/2` kept as a sanity bound. Also
  found and fixed a related, previously-undetected parity gap while adding
  the real-geometry parity test: JS `baselines_total` was `lengths.length`
  (the post-cut count) while Python's is always `n_ant*(n_ant-1)/2` (all
  distinct pairs, matching the report's own prose) -- for `long`/`mid+long`
  these differ by exactly the 30 cut pairs, silently giving JS a different
  efficiency than Python for the same request. JS `total` now matches Python.
  Added `const DEFAULT_LAS_RATIO = 10.0` (commented as mirroring the Python
  constant) and the same Bmin default logic, returning `baseline_las_arcsec`
  / `baseline_las_defaulted`. Per bmason's hard UI constraints: `#calc-las`
  is never assigned a value/placeholder (guarded by both a source-text check
  and a functional read-path check); the default is only mentioned in the
  summary line, and only when `rank` is `efficient` or `performance`; the
  explanatory paragraph's stale "Bmin is zero" sentence is corrected.
- **Tests.** Extended `tests/test_baselines.py`, `tests/test_baseline_ranking.py`
  and `tests/test_report_baseline_ranking.py`: default-vs-supplied LAS,
  the decision-3 regression guard, the acceptance criterion (core/spiral/mid
  at 0.70937"/0.07606"/0.00293" rank #1 under `efficient` at 0.911/0.948/0.845
  -- reproduced exactly against the real packaged Rev F data), the real
  `long`/`mid+long`/`core`/`main` Python-vs-JS parity closing the gap noted
  in the 2026-09-11 correction above, the ghost-value guard on `#calc-las`,
  and the note appearing only for `efficient`/`performance`.
- **Result.** `casapy -m unittest discover -s tests -t .` from repo root:
  461 tests, OK, 1 skip (pre-existing `test_revc_fails_cleanly_until_campaign_runs`,
  unrelated to quickjs). Zero quickjs-attributable skips -- every browser test
  executed. Did not regenerate any HTML reports (W5) or touch W4 (flagged-row
  shading).

### 2026-09-11 -- W3 REVERSED: no uv-range cut on packaged pair geometry

bmason reversed the W3 decision from earlier today. Reasoning: for counting
baselines inside a requested [Bmin, Bmax] uv range for the
`efficient`/`performance` rankings, no filter is wanted -- the antennas are
not wasted, some of their baselines simply fall outside the requested uv
range in some cases, which is exactly what Bmin/Bmax already express. The
filtered state was incoherent: the 30 cut pairs were absent from
`lengths_m` (so the numerator could never count them) but present in the
`n_ant*(n_ant-1)/2` denominator (so they were permanently charged and never
creditable, even for a request whose Bmin is small enough that they should
naturally earn credit). Chosen fix: option A -- keep every pair; let
Bmin/Bmax alone decide what counts. `MIN_UVRANGE_M` is untouched and remains
correct for its original purpose (curve generation/imaging, where those
cluster baselines really do distort the PSF and eta); this reversal is
scoped only to the packaged pair-length geometry used by the ranking
metrics.

Changes:

- `curvegen/build_baseline_data.py`: removed all `MIN_UVRANGE_M`
  import/usage and the cut logic in `_entry()`; every subarray now packages
  its full, unfiltered pair distribution. Provenance no longer records
  `min_uvrange_m` / `n_pairs_before_uvrange_cut` / `n_pairs_dropped_by_uvrange_cut`;
  instead records `uvrange_cut: None` and a `uvrange_cut_note` stating no cut
  is applied by design. Kept `n_pairs`, `format_version: 2`, and all other
  W3 structural work (membership sourcing, digest, validation).
- Regenerated `sa_select/data/baseline_geometry.json.gz`.
- `sa_select/baselines.py`: module docstring reverted to state no uv-range
  cut is applied, with the full rationale and pointer to this reversal so a
  future agent does not reapply the cut a third time. Updated the
  `_validate_geometry` comment similarly (kept the `<=` check as a generic
  robustness bound, not an expectation of filtering).
- `curvegen/report_template.html`: updated the two `baselineMetric` JS
  comments that described the (now reversed) cut.
- `tests/test_baselines.py`: replaced the cut-expecting tests with the
  opposite -- every packaged subarray (including `long`, `mid+long`,
  `spiral+mid+long`, `long+mid+spiral+core-outer`) keeps its full
  `n_ant*(n_ant-1)/2` pairs; added a dedicated test pinning the intent that
  LONG's sub-`MIN_UVRANGE_M` short intra-site pairs are present, not absent.
- `tests/test_report_smoothing.py` and `tests/test_report_baseline_ranking.py`:
  updated comments/assertions that assumed a filtered pair count; the
  real-geometry parity test's assertions still hold (now trivially, since
  n_pairs == n_ant*(n_ant-1)/2 everywhere) and its docstring notes the
  reversal.
- `docs/plans/baseline-window-plan.md`: decision 5 and the W3 work item now
  record that W3 was implemented and reversed the same day, with the
  reasoning above; the Tests section's cut-expecting bullet is struck
  through and replaced.

Verified independently: for every revF subarray, n_pairs == n_ant*(n_ant-1)/2
and `long`'s minimum pair length is back down in the spurious ~cluster range
rather than the previous 515 km post-cut minimum. Full suite green (see
verification numbers in this session's report).

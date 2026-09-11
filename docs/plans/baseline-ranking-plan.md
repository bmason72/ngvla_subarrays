# Efficient and performance ranking

Status: implemented and validated, 10 September 2026; user review pending.
Scope: add two optional ranking criteria to the Python selector/CLI and HTML
calculator, using ngVLA memo 121 section 2.3 as supplied by bmason.
bmason approved proceeding after the LAS, Bmax and full-array policies below
were settled. Scope remains these two criteria and their documentation; no other
features, pending feature merges, or new input controls.

## Assessment

Relatively safe to develop in a separate worktree, with low simulation/data risk
and moderate selector/report integration risk. This is more than adding two sort
keys: baseline distributions are not currently carried by the selector or report,
and ranking availability is coupled to sensitivity-cost availability.

Evidence checked on 10 September:

- Main is at `b983114`; no tracked modifications. Existing untracked files include
  user memo edits, scratch material, and a campaign manifest; preserve them.
- Slurm `squeue -u bmason72` showed only interactive allocation `3486611`
  (`idv16765`), with no queued/running campaign jobs. This checks scheduler state,
  not processes inside the interactive allocation. Recheck before implementation
  or merging; the campaign freeze rule still applies if another campaign starts.
- The MFS snapshot campaign was harvested on 8 September. Its PSF export fix is
  already on main. Additional campaigns and curve-product refactoring are proposed
  or parked, not prerequisites for this feature.
- `feature/curve-limits` and `feature/spiral-plus` worktrees contain **uncommitted
  implementations**; both branch tips are still `a659a74`. A branch-only diff
  would miss these changes. A4 in `docs/ACTION_ITEMS.md` records their pending merges.
- Curve limits directly overlaps `curvegen/make_report.py`,
  `curvegen/report_template.html`, library plumbing, tests and documentation.
  Its feasibility exclusions must run before either new ranking.
- Spiral-plus overlaps configuration membership, metadata and selector tests.
  Exact baseline generation must use its selected antennas once integrated;
  metadata-only subarrays must not become selectable without measured curves.
- The memo editorial pass/release tag remains pending (A2). Avoid editing the
  memo during implementation; supply a proposed methods paragraph for final review.

If the pending features land independently, reconcile against that base; neither
merge is a prerequisite for these two criteria. A future implementation should
use its own worktree and avoid touching the other feature worktrees. Their status
is assessed here only to identify overlap, not to propose additional work.

## Scientific contract

For the science interval `[Bmin, Bmax]` in meters, count each distinct
antenna pair once, without autocorrelations:

```
Ntotal = Nant * (Nant - 1) / 2
Nin = count(Bmin <= baseline_length_m <= Bmax)
efficient = Nin / Ntotal       # descending
performance = Nin             # descending
```

Confirmed decisions (bmason, 10 September 2026): reuse the existing per-subarray
LAS calculation and coefficient; derive the ranking upper bound from
`theta = 1.02 * lambda / Bmax`; include all matching subarrays, including Main
and Main+Long, in performance ranking. Other proposals are identified below.

- Use physical, unprojected pair lengths from the correct revision's antenna
  coordinates. This counts baselines, not time/channel visibility samples or
  weighted uv samples. Do not approximate interval counts from b_min/b_max or
  histogram bins. Projection and asymmetry are future considerations, as discussed
  below; this feature uses the physical geometry.
- **LAS convention confirmed:** `SubarrayInfo.las_arcsec()` already computes
  `las_coeff * lambda_m / b_min_m * 206264.8`. The coefficient is already stored
  per subarray; current metadata uses 0.8. Reuse this calculation and metadata
  for LAS feasibility; do not add a new coefficient setting or hard-code 0.8.
  For the ranking lower bound, invert the same convention using the requested
  LAS: `Bmin = las_coeff * lambda_m * 206264.8 / requested_las_arcsec`.
  With today's uniform coefficient this gives one common lower bound. If existing
  per-subarray coefficients differ later, honor each coefficient consistently
  in Python and HTML rather than silently replacing it with a global value.
- Use the requested frequency, not the sensitivity calculator's recentered band
  frequency. Metric bounds depend on the science request, not the candidate's
  achieved beam, robust or taper.
- **Bmax convention confirmed:** use
  `Bmax_m = 1.02 * lambda_m * 206264.8 / requested_resolution_arcsec`,
  with `lambda_m = 0.299792458 / frequency_ghz`. This is the science interval's
  upper bound, not the longest physical baseline of a candidate subarray.
  Use the requested resolution, not the achieved beam or a beam-margin endpoint.
- **Feasibility precedes ranking:** the selector already evaluates measured
  curves and supplies weighting/robust/taper parameters that meet the requested
  beam under the existing tolerance and skirt policy. Preserve that check.
  Memo 121 section 2.2/Table 7 used natural-beam factors to avoid false geometric
  feasibility assignments. Do not import those factors, rescale pair lengths,
  or add a geometric resolution-feasibility gate here. The simple Bmax formula
  defines the baseline-count metric only; it does not assert that any candidate
  can achieve the requested beam from its longest baseline alone.
- Recommended request behavior: derive bounds from the existing angular inputs
  as above; absent LAS means Bmin=0. No additional user
  inputs or advanced controls are proposed. Validate finite, nonnegative,
  ordered derived bounds; report an inverted interval instead of clamping it.
  (Superseded 11 Sep 2026: an absent LAS now defaults Bmin to
  `DEFAULT_LAS_RATIO * resolution` instead of 0 -- see
  `docs/plans/baseline-window-plan.md` decision 2 and W1/W2.)
- Denominator includes all physical antenna pairs, including LONG's short pairs.
  Existing imaging/LAS short-baseline cuts remain separate. Changing the denominator
  to post-cut pairs would be a different metric and needs an explicit decision;
  this feature does not resolve or alter A8's future LONG-combination rules.
- Keep the existing feasible pool and imaging strict-first policy. Rank within
  each policy group; `strict_first=False` keeps its current Python meaning.
- **Full-array inclusion confirmed:** keep all matching subarrays in performance
  ranking, including Main/Main+Long. The memo selected a single alternative;
  this tool returns a ranked list, so no full-array exclusion is needed.
- Proposed ties: efficient -> larger Nin -> fewer antennas -> canonical name;
  performance -> larger efficiency -> fewer antennas -> canonical name.
  Preserve existing time/antenna-hour tie behavior.
- A measured zero count is a valid score, distinct from missing geometry. Display
  zero explicitly; do not invent an integration time from 1/Nin. Actual modeled
  time continues to use the existing sensitivity/eta calculation.

Projection and asymmetry (future considerations only): physical pair lengths
are not projected uv distances, which depend on source direction and observing
time; a scalar requested resolution also does not encode beam ellipticity or
directional coverage. Note these limits in the metric documentation. Do not add
projection calculations, directional metrics, inputs, or simulations in this
feature. The measured-curve feasibility checks remain in force within their
existing simulation assumptions. bmason's broader request to evaluate declination
scaling of the simulations is recorded in `docs/plans/wishlist.md`; it is not
part of this implementation.

## Implementation sequence and ownership

The root agent owns the contract and integration review; bmason and root perform
final science/UI validation. Delegate bounded implementation after the contract
is settled. The available OpenAI roles below match `AGENTS.toml`; Anthropic
alternatives are listed for another runner, not assumed available here.

| Step | Deliverable | OpenAI role / effort | Anthropic alternative / effort |
| --- | --- | --- | --- |
| 1 | Validate numerical examples against the confirmed bound formulas and full-array policy; review denominator and tie proposals | root architect | senior architect / high |
| 2 | Baseline geometry product, loader and exact count helper with focused tests | terra_worker / medium | sonnet_worker / medium |
| 3 | Python schema, selector, heuristics, CLI and serialization integration | terra_worker / medium | sonnet_worker / medium-high |
| 4 | Report payload, controls, score display and JS count/sort logic | terra_worker / medium | sonnet_worker / medium-high |
| 5 | Shared parity fixtures, targeted/full checks, local report builds and documentation edits | luna_worker / high | sonnet_worker / medium |
| 6 | Inspect results, review integration and validate science examples with bmason | root architect | senior architect / high |

Steps 3 and 4 can run in parallel after step 2's data/interface contract is fixed.
Assign shared files to one worker and have the integrator reconcile changes.

### Baseline data

Add a small CASA-free module (proposed `sa_select/baselines.py`) and a reproducible
generator. Produce a package-local, revision/subarray-keyed geometry product from
the authoritative config membership, with sorted pair lengths, antenna count,
source/membership digest and convention/version. Reuse existing membership rules,
including inner/outer core and spiral-plus; avoid a new conflicting set of rules.
`curvegen/build_subarrays_csv.py:91` already computes the pair lengths but
discards them after extracting extrema; reuse the verified geometry calculation.
Do not require runtime imports of environment-selected `curvegen/config.py`,
untracked generated configs, or the entire configuration checkout in an installed
Python package. Include generated data in package distribution configuration.

Verify unique stations, membership and Ntotal for every supported subarray. Use
binary searches on unrounded sorted lengths for inclusive interval counts. The
report embeds the same lengths once per revision/subarray where practical; measure
the size increase and use existing compression mechanisms if needed. No CASA
simulation, curve regeneration, or new campaign is necessary.

Custom `CurveLibrary.from_tables` and Stroh imports need an explicit way to supply
geometry. Never infer it from a familiar subarray name when revision/membership is
unknown. Missing geometry leaves old ranking modes usable; the requested new mode
must report unavailable scores/ranking clearly rather than silently discard a
possibly winning candidate or substitute zero.

### Python

Extend `sa_select/schema.py` with metric result/provenance
fields; keep existing constructors backward compatible. Attach evaluated metrics
in `sa_select/selector.py`, expose them in result dictionaries/JSON/table output,
register `efficient` and `performance` in `sa_select/heuristics.py`, and extend
`sa_select/cli.py` choices/help. Preserve `antenna_hours` as the default.

Separate the selected heuristic's score requirements from absolute-cost
availability. New modes should work when an implicit fiducial cost is unavailable
but geometry is valid; retain diagnostics and blank cost columns. Preserve the
existing explicit-sensitivity failure policy and old ranking behavior. Do not
broaden this change into a general selector/cost refactor. Add precise diagnostics
for missing baseline scores, and make `best`/`ranking_available` reflect the
selected mode. Check the custom-callable override path as well.

### HTML

Extend `curvegen/make_report.py`'s payload and
`curvegen/report_template.html`'s calculator. Add `efficient` and `performance`
to Rank by, explain their definitions, display Nin/Ntotal and efficiency, and
show the resolved science bounds. Preserve the existing HTML `time` value and
Python `integration_time` interface. Update request validation, sorting, best-row
summary, table and unavailable-result rendering together.

Apply the same interval, tie and missing-score rules as Python. Preserve existing
beam/LAS/skirt/manual-limit checks and MFS-specific feasibility behavior. Reuse
physical geometry across track/snapshot/MFS views of the same membership; do not
add broadband visibility/channel counting or expand Python's current MFS API.
Rebuild per-combo, combined and standalone release reports from the common source;
never hand-edit generated HTML. Keep builds on a dev node as the hand-off requires.

## Validation and completion criteria

- Hand-computable pair geometries: boundaries inclusive; all/none/some in range;
  repeated equal lengths; no autocorrelations; fewer than two antennas rejected.
- An example where efficient and performance disagree, and one where performance
  and modeled integration-time ranking disagree, demonstrating all four criteria.
- Exact ties, missing geometry, zero counts, invalid bounds, no LAS,
  and frequency conversion. Identical JSON numerical fixtures run through
  Python and executed JavaScript, not just template-string assertions.
- Verify the current 0.8 LAS calculation and a synthetic differing per-subarray
  coefficient, including inversion to Bmin. Confirm Main/Main+Long remain listed
  whenever feasible in performance mode.
- Verify the 1.02 Bmax conversion and arcsec/radian units. Changing achieved beam
  within the accepted tolerance must not change the ranking interval for the same
  request. A candidate rejected by measured-curve feasibility must remain excluded
  regardless of its geometric score; no Table 7 correction factors are applied.
- Regression coverage for strict/relaxed imaging groups, custom heuristics,
  unchanged default/time/antenna-hour results, explicit and implicit cost failures,
  JSON/CLI output, and old custom libraries without geometry.
- Cross-revision membership checks (C/D/F), LONG denominator checks, and spiral-plus
  counts after that feature lands. Curve-limit rejection precedes metric ranking.
- Existing report calculator/release/standalone/provenance tests pass, plus relevant
  MFS tests. Full repository suite once after integration; record actual counts,
  skips and environment. Validation results will be recorded below.
- Root/bmason inspect at least two real requests and a tied case, verifying displayed
  interval, counts, order and modeled times in both Python and a local HTML report.
- Update selector README and methods documentation; provide memo wording for the
  separate editorial review. Record data generation command and payload size change.

Rollback is the feature code/data/report commit set. Measured curve CSVs, PSF
payloads, campaign configuration and existing ranking defaults should be unaffected.

## Implementation log

10 September: created isolated worktree `/tmp/ngvla-baseline-ranking` on branch
`feature/baseline-ranking` from `b983114`. Slurm still shows only interactive
allocation 3486611; this session runs on its dev node c455-003. Delegated geometry
and Python integration to `terra_worker` agents. Root owns the scientific contract,
documentation, integration review and final validation. Other feature worktrees
and bmason's untracked files remain untouched.

Root numerical review (Rev F track, point-source, 30 GHz, 5% beam tolerance,
no explicit sensitivity):

| Requested resolution / LAS | Baseline interval (m) | Efficient first | Performance first |
| --- | --- | --- | --- |
| 0.1 arcsec / omitted | 0–21024.4546729 | core+spiral: 13770/14028 = 98.1608% | main: 13788/22791 = 60.4976% |
| 1 arcsec / 10 arcsec | 164.8976837–2102.4454673 | core: 5127/6441 = 79.5994% | core+spiral: 5313/14028 = 37.8743% |

The 0.1-arcsec request also distinguishes performance from modeled time within
the ranked list: long+mid+spiral+core-outer has 5908 in-range pairs versus 5878
for mid+spiral+core-outer, but takes longer under the existing eta-based model.
These are ranking checks against the existing feasible pool; missing rows are
still governed by measured-curve availability and beam/LAS constraints.

Validation completed:

- `PYTHONPATH=/tmp/ngvla-ranking-testdeps casapy -m unittest discover -s tests -t .`:
  450 tests run, OK, one existing skip (the obsolete pre-Rev-C-data CLI case).
  QuickJS was installed only in temporary test storage; executed JavaScript tests
  cover metrics, sorting, sensitivity/MFS failure policy and rendered results.
- The first full run exposed an expected payload-key assertion after adding
  `baseline_geometry`. Updated the additive payload contract and added a test
  that checks displayed revision, antenna counts and pair counts. The final full
  suite passed. No measured curves or feasibility algorithm changed.
- Actual release HTML data and actual calculator functions agree with Python
  on the full ordered lists and integer counts for both requests above and both
  new criteria. A 0.005-arcsec request also checks Main+Long remains eligible.
- Built a wheel, verified its geometry bytes against the source artifact, and
  exercised both ranks from the installed wheel outside the checkout for C/D/F.
  System Python built the wheel (the CASA environment lacks setuptools);
  CASA Python ran the installed selector checks.
- Geometry generation is byte-reproducible: 297,934 pair lengths across C/D/F,
  gzip size 2,507,648 bytes; SHA256
  `05dfca0422f7da5cb52f28ca6664d628ac121c66bac2e69800b545840c9450bf`.
- Rebuilt release and combined reports from the shared template. The isolated
  worktree needs read-only access to the original ignored profile JSONL files
  as well as exported PSFs; an initial artifact comparison caught missing
  `psf_metrics`, and final builds use those existing profiles. Verified every
  pre-existing payload field is identical in both release and combined reports;
  only `baseline_geometry` was added. All six per-combo reports and the default
  alias were rendered from the verified payloads using the existing renderer.
  Release HTML grew from 46,988,827 to 52,784,479 bytes; combined HTML grew from
  15,686,152 to 26,638,651 bytes because they carry exact baseline distributions.
  The release still embeds all 32 existing PSF blocks.
- Actual fixed-window MFS calculator execution at its reference frequency,
  0.1-arcsec resolution and 10 microJy/beam: efficient selects core+spiral
  (13897 in-range pairs); performance selects main (13921). Existing confusion
  and beam checks ran with the real report payload.
- Worker usage limits interrupted the last validation pass. Root completed the
  remaining tests, reviewed fixes, built reports and handled integration.

Proposed memo wording for the separate editorial review (the memo and bmason's
comments were not edited): After measured-curve beam and LAS feasibility checks,
subarrays may be ranked by the fraction (efficient) or number (performance) of
physical antenna pairs in the inclusive interval from `las_coeff*lambda/LAS`
to `1.02*lambda/requested_resolution`, with angles in radians and a zero lower
bound when LAS is omitted. All matching subarrays remain eligible. These metrics
do not replace the eta-based sensitivity/time estimate; source projection and
beam asymmetry are future extensions.

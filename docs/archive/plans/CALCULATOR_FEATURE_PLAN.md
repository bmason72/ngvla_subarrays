# Calculator ranking, controls, and portability plan

Status: revised after critical review and implemented, 21 August 2026.

Implementation verification: the full repository suite passes (224 tests,
35 environment-dependent skips); the packaged natural-sensitivity kernel
matches the original upstream calculator in continuum and line parity tests;
wheel and source distributions build; and the wheel was installed and run
outside the checkout. `RANKING_TRANSITION_AUDIT.json` compares 798
representative 30-GHz cases across all registered campaigns and both metrics,
with no ordering differences from the retired relative-cost score.

## Goals and decisions

This plan treats the requested changes as one calculator feature tranche. It
does not require new CASA simulations. All requested skirt thresholds, beam
margins, ranking changes, sensitivity-unit conversions, and portability work
can use the existing robust--taper samples and natural-sensitivity backing
data. Rebuilding the static report payload is required, but re-running a curve
campaign is not.

Recommended policy decisions:

1. Fix the current sensitivity-failure bug without conflating geometric
   feasibility with cost availability. A failed user-requested sensitivity
   goal is fatal; a failed implicit fiducial leaves beam/LAS feasibility intact
   but disables cost ranking and is reported structurally.
2. When no explicit sensitivity is supplied, use the natural, untapered MAIN
   sensitivity in one minute at the same frequency and spectral setup as a
   common fiducial goal. This gives meaningful, moderate time and antenna-hour
   values. It should reproduce the current flux-density ranking order for
   ordinary cases in the present all-18-m registry, but parity must be measured,
   not assumed; exact natural-rms anchors include tiny effects omitted by the
   ideal relative formula. A future heterogeneous-dish registry may
   legitimately rank differently.
3. For imaging requests, make strict-first an engine policy: partition feasible
   candidates into skirt-met and skirt-relaxed groups, apply the selected
   heuristic within each group, and emit the skirt-met group first. Provide an
   explicit opt-out for custom policies that intentionally compare the groups.
4. Add a result-level structured warning when no candidate meets the requested
   skirt.
5. Keep Python thresholds and margins numeric; expose a small fixed set of
   controls in the static web report.
6. Turn `sa_select` into an installable package whose runtime data are loaded
   with package resources, without a required TACC or repository-relative
   environment.

Review disposition: the four principal review amendments are adopted in this
revision: degraded no-goal behavior, the heuristic/strict-first contract, an
explicit web fiducial mode, and the antenna-class condition on ranking parity.
The review's stronger claim of exact current-registry parity is intentionally
softened: a direct audit found a tiny nonzero confusion term for the backing
core entry, so parity is a regression measurement rather than an algebraic
guarantee. The schema-consumer and pickle round-trip checks are also adopted.
The suggestion
to reject negative beam margins is modified to honor the requested interface:
negative means exact, but produces a structured normalization warning so a
probable sign typo is not silent.

## Antenna-count audit

The current sensitivity calculation does **not** double count antenna count.
The upstream Memo-96 equation is

```text
sigma_nat = SEFD / [eta_c sqrt(n_pol delta_nu t N(N-1))].
```

`sa_select.sensitivity.natural_rms()` calls this expression using the antenna
count stored in `subarray_data.pkl`. The wrapper then does one of the following:

- Rev F/Rev D calculator entry: `n_ant_actual` equals the stored count, so the
  correction factor is exactly one.
- Known calculator entry with a different campaign count, such as Rev C core:
  rescale stored `N_nominal` to campaign `N_actual` once.
- Missing calculator entry: rescale MAIN's natural rms to a declared donor
  target count; if the campaign count differs, rescale that target to the
  actual count. The product telescopes to the single MAIN-to-actual ratio.

The subsequent multiplication `antenna_hours = integration_time * N_actual`
is resource accounting, not another sensitivity correction.

The no-goal fallback writes the same physics explicitly:

```text
relative time          = eta^2 / [N(N-1)]
relative antenna-hours = eta^2 / (N-1).
```

Replacing this fallback with a fiducial sensitivity will make the presentation
simpler, but it cannot remove antenna count from the physics: the count will be
inside each subarray's natural-rms anchor instead of appearing explicitly in a
relative formula.

Before merging any cost-model change, add a parameterized algebra test covering
direct Rev F, direct Rev C, donor Rev F, and donor-with-revision-override paths.
For each path, compare the wrapper result with a direct analytic
`1/sqrt(N(N-1))` ratio and verify that MAIN-to-final-count is applied exactly
once.

## Current capability and gaps

| Request | Current state | Work needed |
|---|---|---|
| Python skirt threshold | Already arbitrary through `ObservingRequest.skirt_threshold`, `--skirt-threshold`, and batch CSV | Preserve; add range/finite validation and focused documentation/tests |
| Web skirt threshold | Imaging plots already provide 5%, 10%, 15%, 20%; the calculator implicitly follows the plot's global selector | Put an explicit, synchronized selector in the calculator form so the active requirement is unambiguous |
| Strict imaging results first | Per-subarray solve is strict-first, but cross-subarray cost sorting mixes strict and relaxed candidates | Add structured skirt status and a strict-first group key |
| Warn when none meet skirt | Per-candidate relaxed flags exist; no result-level warning | Add Python result warning/status and a visible web calculator banner |
| Python beam tolerance | Already arbitrary through `beam_margin` and `--beam-margin`; zero works as exact, negative is not normalized or validated | Normalize non-positive values to exact, warn structurally for negative input, and validate finite margins below 1; document 0--10% as recommended |
| Web beam tolerance | Hard-coded at 5% | Add fixed exact, 1%, 5%, and 10% choices |
| Python sensitivity units | Jy/beam and K already supported | Preserve and add regression coverage with the new fiducial path |
| Web sensitivity units | MicroJy/beam only | Add microJy/beam versus K selector and candidate-beam conversion |
| Web no-goal/fiducial mode | The form currently requires a sensitivity value and defaults to 10 microJy/beam | Make the goal optional or add an explicit one-minute-MAIN fiducial mode, with clear labeling |
| Outside-TACC execution | Already works from a checkout with `sa_select/` and sibling `ngvla-sensitivity-calculator/`; verified with `python3 -m sa_select.sensitivity` | Add normal packaging and package-owned runtime data so sibling layout is unnecessary |

## Phase 1: make candidate state explicit and fix the feasibility bug

1. Extend `Candidate` with structured imaging fields, for example:
   `skirt_required`, `skirt_met`, and `skirt_relaxed`. Do not infer these from
   warning strings.
2. Preserve `Envelope.Choice.relaxed` through `CurveSample` or return a small
   solve-result object containing both the sample and structured status.
   Prefer the solve-result object so measurement samples remain measurement
   data rather than query outcomes.
3. Extend `Candidate` with a separate structured cost state, such as
   `cost_status=available|unavailable|failed`, so beam/LAS feasibility need not
   be overloaded to mean costability.
4. Extend `SelectionResult` with structured result-level diagnostics, for
   example `warnings: list[SelectionWarning]` and
   `any_subarray_meets_skirt: bool | None`, `ranking_available: bool`, and a
   result-level cost error. Ensure `to_rows()` exposes the per-candidate fields;
   provide a small `to_summary()` mapping for batch/API consumers. If ranking
   is unavailable, `best` must be `None` rather than the first metadata row.
5. Reorder `select_subarrays()` so feasibility and cost state are finalized
   after all required calculations. A failed user-supplied sensitivity goal
   makes the affected candidate infeasible. A failed implicit fiducial leaves
   beam/LAS-feasible candidates feasible, but disables cost ranking for the
   entire result. Neither case may enter the relative-cost fallback.
6. Add regression tests that force both sensitivity-module import failure and
   `integration_time()` failure under explicit-goal and no-goal requests. For
   an explicit goal, assert exclusion and no possibility of becoming `best`.
   For a no-goal request, assert preserved beam/LAS feasibility,
   `ranking_available=False`, `best is None`, and a structured cost error.
7. Inventory additive schema consumers explicitly: `cli.py`, `stroh.py`,
   `export_ngect.py`, `make_report.py`, batch row serialization, and their
   tests. Keep compatibility fields where practical and update each consumer
   deliberately.

Acceptance criteria:

- No candidate containing a fatal reason has `feasible=True`.
- Imaging status can be consumed without parsing English text.
- Existing human-readable warnings and exclusion messages remain available.
- Absolute and relative costs can never be mixed in one sort. If any required
  implicit cost is unavailable, the result is explicitly unranked.

## Phase 2: replace the no-goal relative score with a one-minute MAIN fiducial

Define the implicit goal, when the user supplies no sensitivity, as

```text
g_fid = natural_rms(MAIN, request frequency, 1 minute, request spectral setup).
```

For every candidate, calculate

```text
t_i = 1 hour * [eta_i sigma_nat,i(1 hour) / g_fid]^2
A_i = N_i t_i.
```

For the web report, whose sensitivity table is normalized to one hour and
1 MHz, use the request bandwidth consistently:

```text
g_fid = sigma_MAIN(1 hour, 1 MHz) * sqrt(60 / bandwidth_MHz).
```

This makes an untapered natural MAIN request one minute by definition. At a
different requested beam, MAIN's eta raises its time in the expected way. For
the current registry, every offered subarray uses the same 18-m antenna class,
so a common Jy/beam fiducial should normally change only the scale and display
of the current relative rankings. This is not an exact theorem: the backing
core entry has a tiny nonzero native-resolution confusion term (about
0.000083 microJy against 0.367 microJy total in the current 30-GHz audit), and
the exact model can carry other anchor-specific details. Adding SBA or another
antenna class can produce materially different rankings because the exact
natural-rms model includes real per-antenna sensitivity. Such explainable
changes are improved physics, not regressions, but every ordering change must
be reported and reviewed before the default changes.

Implementation details:

1. Centralize goal resolution in a cost-model function returning
   `(goal_jy, goal_origin, sigma_nat, integration_time, antenna_hours)`.
2. Mark candidates/results with `goal_origin="user"` or
   `goal_origin="main_natural_1min_fiducial"` and report the fiducial value and
   observing setup.
3. Use Jy/beam internally for the fiducial even when the UI display preference
   is K. A user-supplied K target remains candidate-specific after conversion
   with each achieved beam.
4. Do not silently revert to the old relative formula when the sensitivity
   backend fails. With a user goal, mark the affected candidate infeasible.
   With the implicit fiducial, retain beam/LAS-feasible candidates but set
   `ranking_available=False`, leave all costs unset, preserve metadata order
   only as a presentation order, and return `best=None` plus a structured
   result-level cost error. This preserves useful beam-only selection while
   refusing to present a false cost ranking.
5. If one candidate's implicit cost fails after the MAIN fiducial succeeds,
   disable the whole cost ranking rather than ranking a partial pool.
6. Keep the relative helper functions temporarily for tests/comparison, then
   deprecate them once the transition comparison and any ordering changes are
   reviewed and accepted.

Acceptance criteria:

- An exact natural MAIN operating point reports one minute under the implicit
  fiducial.
- Compare old and new Jy/beam orderings over a representative resolution grid
  for every registered all-18-m campaign. Produce a machine-readable change
  report; require review of every difference rather than asserting exact
  parity. Add a separate heterogeneous-antenna fixture showing that a different
  ordering is allowed and correctly explained.
- Displayed implicit times are finite, physically interpretable, and carry an
  explicit fiducial label.
- Removing or breaking the sensitivity backend does not destroy no-goal
  beam/LAS feasibility and never produces a fallback ranking.

## Phase 3: strict-first imaging ranking and no-strict warning

Strict-first belongs to the selection engine, outside the individual heuristic.
For an imaging request with the default policy, the engine partitions feasible
candidates and calls the selected heuristic separately on each group:

```text
rank(skirt_met candidates) + rank(skirt_relaxed candidates).
```

The built-ins therefore continue to rank only by their documented cost keys,
and a custom heuristic's contract becomes ``rank within one policy group.''
For point-source requests there is one group. Add an explicit request option,
for example `strict_first=False`, that passes the original mixed pool to a
custom heuristic when cross-group tradeoffs are intentional. This policy leaves
the existing per-subarray curve choice unchanged and requires no simulations.

If at least one candidate meets the skirt, all such candidates appear first and
are internally ordered by antenna hours or integration time. Relaxed candidates
remain visible below them with flags. If none meets it:

- Python: set `any_subarray_meets_skirt=False` and append a typed warning such
  as `NO_SUBARRAY_MEETS_SKIRT` containing the requested threshold.
- CLI: print a concise warning and retain the relaxed ranked table.
- Batch/API: expose the summary warning without requiring stderr parsing.
- Web: show a warning banner above the result table and keep the relaxed rows,
  all visibly flagged.

Add tests for multiple strict candidates, mixed strict/relaxed candidates, no
strict candidates, point-source requests, both cost metrics, a custom heuristic
under the default grouped contract, and the explicit mixed-pool opt-out.

## Phase 4: expose skirt, beam-margin, and Kelvin controls

### Python

- Retain numeric `skirt_threshold`; validate that it is finite and physically
  meaningful. A range of 0--1 is sufficient and does not constrain normal use.
- Retain numeric `beam_margin`. Normalize `beam_margin <= 0` to exact, but emit
  a structured normalization warning when the supplied value is negative so a
  probable sign typo is visible. Reject non-finite values and require the
  effective margin to be below 1. Document 0--0.10 as the normal operating
  range without breaking wider diagnostic tests.
- Confirm exact mode through measured-point, edge-interpolation, and bilinear
  cell tests. The envelope already supports a zero-width interval.
- Preserve `sensitivity_unit="K"` and test that conversion uses the achieved
  candidate beam.

### Web report

1. Add calculator-form skirt choices 5%, 10%, 15%, and 20%. Reuse the curves
   already emitted in `DATA.imaging`; synchronize this control with the imaging
   plot selector in both directions.
2. Add beam-margin choices exact, 1%, 5%, and 10%. Pass the selected value to
   both the lookup window and beam-cap test, and generate messages using the
   selected percentage rather than hard-coded `+/-5%` text.
3. Add sensitivity-unit choices microJy/beam and K. For K, convert the requested
   brightness temperature to microJy/beam separately for each candidate using
   its achieved beam and the request frequency, then calculate time normally.
4. Make sensitivity optional in the web calculator, or add an explicit
   ``one-minute natural MAIN fiducial'' goal mode. When selected, derive the
   fiducial at the requested frequency and bandwidth, display its value and
   origin, and do not imply that it is a user science requirement. Preserve the
   current explicit-goal mode and its default value for backward-compatible UI
   behavior unless product review chooses the fiducial as the new default.
5. Make the result table and summary state the selected units and skirt/margin
   policy. Retain the original input value; do not replace it with the
   candidate-specific converted flux goal.
6. When switching campaigns, preserve a control value only if the new payload
   supports it; otherwise select that campaign's default and announce the
   change accessibly.

Add JavaScript-facing golden fixtures generated from Python for several
30-GHz cases, including explicit-Jy, explicit-K, and no-goal fiducial modes.
They should compare chosen subarray, strict/relaxed state, achieved beam, eta,
and ranking group. This guards against drift between the raw-envelope Python
query and the report's pre-gridded curve lookup.

## Phase 5: package the calculator for use outside TACC

The current runtime is already CASA-free and was successfully exercised in the
repository's ordinary Python environment. Its remaining portability weaknesses
are repository-relative data loading, pickle-backed upstream tables, and lack
of standard Python packaging.

1. Add `pyproject.toml` with an installable `sa_select` distribution, declared
   NumPy/SciPy dependencies, package data, and a `sa-select` console entry point.
2. Move or export the required Memo-96 runtime tables into a package-owned data
   namespace and load them with `importlib.resources`. Prefer a documented,
   non-executable format such as JSON plus NumPy arrays over pickle. Keep the
   original upstream files for provenance if redistribution permits. The
   export tool must round-trip every nested NumPy scalar/array and compare the
   converted representation numerically with the original pickle tables.
3. Remove `_in_calculator_dir()` and all dependency on a sibling directory or
   current working directory. Either vendor the small upstream calculation
   kernel behind a private module or reimplement the explicitly used natural-rms
   equations with parity tests. Do not use the upstream placeholder eta spline.
4. Record data schema/version, upstream provenance, checksum, units, and the
   supported receiver/subarray keys. Check redistribution/license status before
   publishing a wheel or external bundle.
5. Ensure all registered subarray metadata and curve CSVs are package data.
   Add a command that reports available campaigns and data version.
6. Build both a wheel and source distribution. In a clean temporary virtual
   environment outside the checkout, install the wheel and run:
   imports, a no-goal fiducial request, Jy and K goals, line and continuum
   requests, every registered campaign, batch CSV, and CLI help.
7. Keep the documented sparse-checkout route as a developer option, but make
   `pip install <wheel>` the handoff path for collaborators.

Target bundle size is modest: the current `sa_select` tree is about 2.5 MB and
the upstream sensitivity directory about 56 KB.

## Suggested implementation order and review gates

1. **State and bug fix:** structured solve/candidate/result status; fatal cost
   failures; regression tests.
2. **Cost model:** one-minute MAIN fiducial, degraded no-goal behavior, current-
   registry ordering comparison, and antenna-count algebra tests. Review
   numerical examples and every ordering change before changing defaults.
3. **Ranking policy:** strict-first partition and no-strict result warning.
4. **Python controls:** validation and exact-mode tests.
5. **Web controls:** synchronized skirt selector, margin selector, K conversion,
   explicit no-goal/fiducial mode, warning banner, and Python/web parity fixtures.
6. **Packaging:** package resources, stable data format, clean-wheel tests, and
   handoff documentation.

After each gate, run the existing selector, envelope, CLI, report, export, and
portability tests. Before release, regenerate the static report from the same
committed curve tables and manually inspect one mixed strict/relaxed case and
one no-strict case at 30 GHz. No curve-generation campaign should be submitted
for this tranche.

# Review of CALCULATOR_FEATURE_PLAN.md

Reviewer: Claude (Fable 5), 21 August 2026. Every factual claim in the plan was
checked against the current working tree; code references below are to the
files as of this review.

## Verdict

The plan is sound and ready to implement, with four amendments recommended
before Phase 1 starts (see "Issues"). Its factual claims about the codebase are
accurate — I verified each one directly, including the two most consequential:
the feasibility bug is real, and the antenna-count audit's "no double counting"
conclusion is correct. The phase ordering is sensible and the "no new CASA
simulations" scoping claim holds. The main weaknesses are policy edges the plan
does not pin down: what a fiducial-cost failure does to a no-goal request, how
the strict-first partition interacts with the pluggable-heuristic contract, and
an unstated web-form change implied by Phase 2.

## Claims verified against the code

- **The feasibility bug (Phase 1) is real and worse than the plan states.**
  `selector.py:152` sets `c.feasible = not c.reasons` *before* the sensitivity
  block (lines 155–177). A sensitivity import or calculation failure appends a
  reason but never flips `feasible`, so the candidate stays in the feasible
  pool with `integration_time_hr=None` — and `heuristics.py:43–44,53–54` then
  silently rank it by the *relative*-cost fallback while every healthy
  candidate is ranked by absolute cost. So the current behavior is not just
  "failure is non-fatal": a broken candidate is sorted on an incommensurable
  key against working ones and can plausibly land at rank 1. `to_rows()` and
  `table()` compound this — `table()` only prints reasons for infeasible
  candidates, so the failure text is invisible in the summary view. The
  regression tests proposed in Phase 1 item 5 are exactly right.

- **The antenna-count audit is correct.** `sensitivity.py` confirms every step:
  the donor rescale in `natural_rms()` (lines 196–200), the nominal→actual
  rescale in `integration_time()` (lines 240–244) using `_n_ant_for()`, which
  returns the donor *target* count for donor names — so the product does
  telescope to a single MAIN→actual ratio. `antenna_hours = t * N` at
  `selector.py:175` is indeed pure resource accounting. The proposed
  parameterized algebra test over the four paths is a good gate; the module
  self-test already covers pieces of it but not the donor-with-override path.

- **The Phase 2 fiducial algebra is right.** For MAIN at its natural operating
  point (eta = 1), `t = 1 hr × [σ(1 hr)/ (σ(1 hr)·√60)]² = 1 minute` — the
  acceptance criterion follows by construction. The web-side formula
  `g_fid = σ_MAIN(1 hr, 1 MHz) · sqrt(60 / bandwidth_MHz)` is the correct
  radiometer scaling given the payload's 1-hour/1-MHz normalization, which the
  template confirms (`report_template.html:842` divides the squared ratio by
  bandwidth in MHz).

- **The current-capability table is accurate.** Spot checks: `skirt_threshold`
  and `beam_margin` are arbitrary numerics in `ObservingRequest`
  (`schema.py:76–77`) with matching CLI flags and batch-CSV columns
  (`cli.py:74,77,20`); K is supported via `--unit` and `tb_to_jy` using the
  achieved candidate beam (`selector.py:162–164`); the web calculator
  hard-codes `CALC_BEAM_MARGIN = 0.05` (`report_template.html:623`) and a
  literal "±5%" message (line 738); the form takes µJy/beam only (line 230);
  the skirt selector already offers 5/10/15/20% and the calculator implicitly
  reads the selected `DATA.imaging[s0]` (lines 256–260, 728). Cross-subarray
  ranking indeed mixes strict and relaxed candidates: a relaxed skirt is only a
  warning (`selector.py:143–144`), never a sort key. `Envelope.Choice.relaxed`
  exists (`envelope.py:141`) and is currently flattened into a message string
  by `CurveLibrary.solve` — the plan's "structured status is lost" diagnosis is
  correct.

- **Portability facts check out.** `_in_calculator_dir()` exists
  (`sensitivity.py:54`) and chdirs into the sibling directory on *every* call
  (it's also process-global and not thread-safe — one more reason Phase 5 item
  3 is right to remove it). Both upstream tables are pickles. The quoted sizes
  match (`sa_select/` 2.5 MB, calculator 56 KB).

- **"No new simulations" is correctly scoped.** Python skirt thresholds filter
  raw samples at query time (`curves.py:164–179`); the web payload already
  carries the four skirt setpoints; margins, K conversion, and ranking are all
  post-hoc. Only the static-report payload rebuild is needed, as stated.

## Issues and recommended amendments

**1. Decide what a fiducial-cost failure means for a no-goal request (Phase 1
rec. 1 × Phase 2 item 4).** Today, `select_subarrays` imports the sensitivity
module only when a goal is given, so beam/LAS feasibility queries work with no
calculator present. After Phase 2 the backend is needed on *every* request, and
the plan's combined policy — "sensitivity failures always make a candidate
infeasible" plus "do not revert to the relative formula" — means a missing or
broken backend turns a pure beam-feasibility question into "no feasible
subarray", which is wrong as an answer to that question. Recommend
distinguishing the two cases: a *user-supplied* goal that cannot be costed →
candidate infeasible (the plan's rule); a *fiducial* cost failure on a no-goal
request → candidates stay feasible with `integration_time_hr=None`, cost-based
ranking is disabled, and a result-level structured error says so. That keeps
the Phase 1 invariant ("no fatal reason with `feasible=True`") without
overloading feasibility to mean "costable". This also softens the sequencing
coupling with Phase 5 (between Phases 2 and 5, a checkout without the sibling
calculator directory would otherwise lose no-goal selection entirely).

**2. Specify where the strict-first partition lives relative to the pluggable
heuristic (Phase 3).** CLAUDE.md makes heuristic pluggability a hard
requirement, and today the *entire* ranking is the heuristic callable
(`heuristics.resolve` at `selector.py:112,181`). The proposed sort key
`(skirt_met, cost, N_ant, ...)` must go somewhere: inside the built-ins (then
every custom heuristic silently loses strict-first and must reimplement it) or
in the engine as a pre-partition (then a custom heuristic can no longer trade
strictness against cost, which is a legitimate strategy). Recommend the engine
partition the feasible pool and apply the heuristic *within each group*,
documenting that a heuristic ranks within a policy group — and provide an
escape hatch (e.g. `strict_first=False` on the request, or an engine-level
policy hook) for heuristics that want the mixed pool. Either choice is
workable; the plan should just make it, because it changes the heuristic
interface contract.

**3. Phase 2 implies an unstated web-form change.** The web calculator
currently *requires* a sensitivity value (`calc-sens`, default 10 µJy/beam);
there is no no-goal path in the report at all. The plan's web fiducial formula
therefore entails making that field optional (or adding a "no goal / fiducial"
mode) with UI messaging about what the displayed times mean — but Phase 4's web
control list never mentions it. Add it explicitly to Phase 4 (or drop the web
side of Phase 2 and keep the fiducial Python-only), and include it in the
Python/web golden fixtures.

**4. The "ranking order is preserved" claim is conditional — state the
condition and guard it.** The old relative formula assumes equal SEFD; the new
fiducial uses each subarray's real natural rms. These orderings agree exactly
only because every offered subarray uses 18-m antennas, making σ_nat ∝
1/√(N(N−1)) exact (confusion is 0 at these resolutions per the module
self-test). That is true of all 14 rows of `subarrays.csv` today — no SBA — but
the calculator knows the 6-m SBA, and CLAUDE.md's task statement includes it
long-term. Recommend the parity test assert order-agreement over the *current
registry* rather than in the abstract, plus a comment that adding a
non-18-m subarray legitimately changes relative rankings (a feature of the new
model, not a regression).

Minor points:

- **Negative `beam_margin` (Phase 4):** silently normalizing `<= 0` to exact
  treats a probable typo (−0.05 for 0.05) as the strictest possible request.
  Recommend: 0 → exact, negative → `ValueError`. Cheap and less surprising.
- **Schema-change ripple:** Phase 1's `Candidate`/`SelectionResult` extensions
  touch consumers beyond the selector — `export_ngect.py`, `stroh.py`,
  `make_report.py`, and their tests. The per-gate test-suite runs cover this,
  but it's worth a one-line inventory of consumers in Phase 1 so additive-only
  changes are checked deliberately rather than discovered by test failure.
- **Phase 5 pickle conversion:** the plan is right to prefer JSON + arrays;
  note the two pkls hold nested numpy scalars/arrays, so the export script
  should round-trip-compare against the originals, and the provenance/license
  check (upstream is V. Rosero's code and data) should happen before any wheel
  leaves the repo, as the plan says.
- **Fiducial choice (1 minute on MAIN):** arbitrary but well-justified — it
  pins natural MAIN to a memorable value and keeps implicit times moderate.
  The mandated `goal_origin` labeling is the right defense against readers
  mistaking fiducial times for physical requirements. No change requested.

## Order-of-work assessment

The suggested gates are in the right order: the structured-status work (gate 1)
is a prerequisite for both the ranking policy (gate 3) and honest web flags
(gate 5), and doing the cost model (gate 2) before ranking means the
strict-first tests exercise real costs. If amendment 1 above is adopted, gate 2
should also land the degraded no-goal mode so gate 6 (packaging) is a hardening
step rather than a functional dependency. The closing discipline — regenerate
the static report from committed tables, inspect one mixed and one no-strict
case at 30 GHz, submit no campaigns — is consistent with RELEASE_PLAN practice
and needs no change.

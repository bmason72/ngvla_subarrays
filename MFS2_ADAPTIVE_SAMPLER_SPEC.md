# MFS-2 adaptive sampler — design spec v2.1 (build contract)

**Status: v2.1, reviewed against the worktree 1 Sep 2026.**  This remains the
normative MFS build contract, now with the mono-sampler work completed since the
original 21 Jul v2 separated from the MFS work still to be implemented.  Every
target rule is meant to be coded without guessing; pinned numbers are in
"Constants".  Supersedes v1 + its two appendices (codex review + bmason addendum
folded into the body).  Companion: `MFS_CAMPAIGN_PLAN.md` (bands, nchan pilots,
noise A/B, PyLauncher wave, storage — unchanged except where cited).

**Operational rule (live-code hazard, updated 1 Sep).**  Campaign tasks import
the checkout when each task starts, and later collect/report tasks import it
again.  While any campaign chain is queued or running, documentation-only work
is safe; **do not edit live-path modules**, including `curvegen/config.py`,
`simulate.py`, `sweep.py`, `adaptive_support.py`, `refine.py`, `make_report.py`,
`adaptive.py`, or `sa_select/envelope.py`, nor their schemas/registry, until the
chain has drained or its exact import boundary has been verified.  In
particular, `sweep.py` and `refine.py` now import `adaptive_support.py`, so that
helper is not isolated sampler code.  Do not launch, cancel, requeue, collect,
or rewrite result tables as part of MFS implementation review.  The MFS build
may start only after bmason confirms the active non-MFS campaign work has
drained.

## Current implementation baseline (4 Sep 2026)

The repository now has the first **Ka MFS implementation layers** plus the
working mono-campaign adaptive retrofit foundation:

- **Built:** MFS-2b's point-table/quadtree planner and MFS-2e's measuring loop
  and retrofit sbatch; deterministic restart, residual/dominance retirement,
  classification, budget admission, and conservative per-point report status
  (`residual-validated`, `not-residual-validated`, `not-assessed`).  The sbatch
  combo map now also includes **revC/track** at array index 4.
- **Built 4 Sep:** MFS-2a's Ka band/manifest/registry axis and `nchan`
  fail-fast. `config.py` routes band4 into isolated combo paths, `simulate.py`
  lays out and validates the 20.25--33.75 GHz channel centers with RR/LL only,
  `sweep.py` pins the MFS tclean convention and seed sampling check, and an
  immutable per-combo manifest guards artifact reuse. The selector's existing
  `(rev, mode)` registry view deliberately filters band rows so fixed-window
  native curves cannot enter its legacy 30/f scaling API.
- **Built/hardened 4 Sep:** repeat-derived per-map jitter with component
  fallback, repeatability-gated `smooth` labels, full capped-resolution
  censoring in ranges/cuts/interior evidence, pre-proposal rejection of
  key-degenerate stencils, normalized cut widths + fine/coarse side labels,
  the dominated loss weight, fresh-attempt budget accounting, and manifest-
  enforced fresh mode for MFS restarts.
- **MFS-2c foundation built 4 Sep:** `sa_select.envelope.build_leaf_families`
  consumes explicit adaptive leaves, registers measured hanging nodes as split
  edge segments, excludes capped resolution geometry, and suppresses bilinear
  interiors for cut leaves. The legacy `build_cells()` path is unchanged.
  Full per-edge cut sets and the global limiting-envelope freeze test remain.
- **MFS-5 foundation built 4 Sep:** collection uses an incompatible native
  fixed-window schema, standalone reports reconstruct adaptive topology from
  result rows, and internal combined-report keys include `band`. MFS reports
  are point-source only. The report calculator now pins the registered MFS
  window, keeps native angles unscaled, uses thermal-only observing-time
  arithmetic, and applies measured-PSF confusion only as an MFS feasibility
  floor. It remains dormant until collected MFS curves/profiles exist.
- **Not built:** MFS-2d/V1 retrospective replay and the MFS-4 PyLauncher wave
  runner. The unresolved MFS-2b/2c deltas below remain deployment blockers.

The worktree audit also found that tracked modules import
`curvegen/adaptive_support.py` while that helper is currently **untracked**.
It must be reviewed and added to the implementation change set (without
discarding the present user-owned file) before claiming a reproducible clean
checkout.  The code's `SPEC_VERSION` intentionally remains
`MFS2-adaptive-sampler v2 (21 Jul 2026)` until the v2.1 obligations are
implemented; changing a documentation version alone must not relabel the
existing algorithm.

### Known code/contract deltas to resolve during MFS implementation

These are implementation obligations; the target semantics later in this file
remain authoritative unless bmason explicitly changes them:

1. **Resolved 4 Sep:** pooled within-point repeat variance now estimates each
   per-map jitter component, falling back component-by-component to
   `SIGMA_DEFAULT`; `smooth` requires repeatability evidence.
2. **Partial 4 Sep:** a cell still records only its strongest detected cut and
   freezes by the local proxies `t_hi/t_lo <= 1.05` or
   `r_hi-r_lo <= 0.10`, not the global limiting-envelope stability test.
   Strongest cuts now carry fine/coarse side labels and normalized `u`/`v`
   widths; per-edge cut sets and global freezing remain.
3. Balance closure currently schedules full stencils on coarser neighbors.  It
   does not implement the lower-cost hanging-node registration/segmented-edge
   consumer described in v2. **Partial 4 Sep:** the consumer now segments a
   coarser edge at every measured hanging node, while the sampler retains the
   conservative full-stencil closure fallback and accounts for every proposal.
4. The implemented goal test uses corner skirt values in `[0.05,0.20]` and a
   point-source envelope proximity test. **Partial 4 Sep:**
   `W_GOAL_DOMINATED=0.25` is applied and the immutable per-combo manifest pins
   `nchan`, spectral window,
   batch/freeze/localization constants, seed/topology policy, jitter estimator,
   and float canonicalization. Scaled mono cliff priors still need a reviewed
   data source before they can be pinned or used.
5. Non-dyadic legacy rows currently assist cut classification and the global
   point-cloud envelope used for goal/dominance decisions; the
   residual/certification calculation uses exact dyadic corners and stencil
   probes.  Failed keys remain occupied even after process restart, whereas v2
   intended them to be re-proposable in a later run.
6. **Resolved 4 Sep:** capped probes and corners are excluded from resolution
   residual/range prediction, cut detection/filling, adaptive edges/cells, and
   interior resolution evidence; eta/skirt remain usable.
7. **Resolved 4 Sep:** reconstruction and proposal generation both reject a
   cell unless bisection produces a distinct 3x3 stored-key grid.
8. `--plan-only` reports only the immediate next wave, not a forecast of the
   complete retrofit/new-evaluation total required by the pre-submission
   certification gate.
9. Fresh MFS audit accounting is now reconstructed from all durable attempted
   keys, including failures, so a restart cannot replenish its total cap.
   Retrofit audit accounting is still new-evaluations-per-process, so a killed and
   resubmitted process can spend another audit allowance.  The table/topology is
   resumable, but a durable per-run budget ledger is required if the audit cap
   is to remain a hard cross-restart bound.
10. The refactor shares constants and proposal helpers through
    `adaptive_support.py`, but the actual classifiers remain separate
    (`refine._classify_scan` and `adaptive.Sampler._classify_cell`).  MFS-2b must
    either establish one tested classifier or explicitly specify and test the
    intended semantic differences.
11. **Resolved for MFS 4 Sep:** the immutable campaign manifest pins
    `run_mode=fresh`, and `Sampler` enforces fresh mode for MFS even after the
    table is populated; an explicit MFS retrofit request fails closed.

## Scope (bmason, 21 Jul — supersedes conflicts)

1. **No grid-style MFS.**  The adaptive sampler IS the MFS engine from day one.
2. **MFS = Ka band only** initially: the calculator's 27 GHz band (band 4),
   **27 ± 6.75 GHz = 20.25–33.75 GHz**, fractional bandwidth **0.50**
   (`MFS_CAMPAIGN_PLAN.md` scope decision 2, `receiver_data.pkl`).  revF,
   homogeneous + main set (7 subarrays: core-inner, core, spiral, mid,
   core+spiral, spiral+mid, main), **point-source goal first**.  Skirt is
   still always measured and recorded on every point; imaging curves derive
   later from the same table (no re-measurement).
3. **`nchan` is REQUIRED and bmason-set** — a registry/manifest field + env
   (`NGVLA_NCHAN` / registry `nchan` column).  The machinery **fails fast with
   a clear message** if `nchan` is unset for an MFS combo; it is never derived
   or defaulted silently.  Analytic floor, as GUIDANCE only:
   `nchan ≥ 38.5·f_bw → 19.25 → 32` for Ka (pow2-rounded).
4. **Mono retrofit history/scope.**  The certification-first retrofit was
   deployed after the July revD/track canary on revF/track, revF/snapshot,
   revD/track, and revD/snapshot.  The shared retrofit array now supports
   revC/track as a fifth combo.  These mono runs validate and warm the sampler
   foundation; they do not constitute an MFS campaign or waive the MFS gates.

## Surrogate framing (the mental model)

bmason: build surrogates for `θ(t,r)`, `s(t,r)`, `η(t,r)` — bearing in mind
multiple branches — and sample where they change quickly, not just at branch
points.  Concretely: the **piecewise-bilinear cell model IS the local
surrogate** (per leaf, `(ln res, η, skirt)` are bilinear in the normalized cell
coordinates — the validated `Cell` in `envelope.py`); the **tolerance-scaled
hierarchical residual is its measured error** (below); **refinement triggers
wherever that error exceeds tolerance** — fast-variation regions generally, not
only branch points — with goal weighting concentrating effort near the
deliverable loci.  **Branch multiplicity is handled globally**: the deliverable
per resolution contour is the minimum over ALL leaves covering that resolution
— never assume a single branch.  `f` is **piecewise smooth**: the snapshot
taper-onset cliffs (θ jumping 3.00→3.07 mas with no interior at 8-level scan
density, revD/snapshot main+long) are measured facts, so the step/cut machinery
is not optional.  Predictor-corrector *contour continuation* was considered as
the pure form of this reframing and **rejected** (brittle at branch switches
and cliffs, poor resumability, misses disconnected branches); AMR + goal-weight
+ an exploration floor is its robustified equivalent.

**Deliverable loci (goal region), stated geometrically.**  1-D loci in the 2-D
input space: (a) the point-source minimizer `argmin η | θ`; (b) the
constrained-locus FAMILY where the skirt constraint binds across the WHOLE
offered `s₀` range **[0.05, 0.20]** (not only 0.10 — the report ships four
setpoints 0.05/0.10/0.15/0.20 via `make_report.SKIRT_SETPOINTS`); (c) the
discontinuity fronts.  Tolerance semantics: `dη` on the envelope VALUE along
the loci; `dθ` as contour localization; `ds` only near the binding band
`s ∈ [0.05, 0.20] ± noise` — elsewhere skirt needs only feasible/infeasible
classification, which licenses relaxing global skirt accuracy (the noisiest
output) for a real budget saving.

## Architecture (3 layers)

1. **Point table = source of truth.**  The per-(subarray, combo) results CSV
   (`sweep.FIELDS` schema, keyed by the shared
   `adaptive_support.point_key`), append-only, resumable.
   Combo routing = `-<rev>_<mode>_<band>` per `MFS_CAMPAIGN_PLAN.md`.  Every
   existing table is a valid warm start.
2. **Topology = derived view**, reconstructed deterministically from the table
   on every restart — **no pickled sampler state**.  A 2:1-balanced quadtree
   over normalized `(u, v)` (below) whose vertices are dyadic bisections of the
   seed cells; leaves are rectangles with 4 measured corners.  The taper=0
   column and natural row are 1-D families glued to the edge, never quadtree
   coordinates.
3. **Features = recomputed annotations** (never stored).  The target is ONE
   shared implementation of the E2 rim-classification semantics labeling leaves
   and cut edges from the rows at build time.  The mono code currently has
   separate refine/adaptive classifiers; this must be reconciled as delta 10.

### Coordinates and the taper=0 / natural seam (finding #6)

- **Normalized inputs:** `u = (robust + 2)/4 ∈ [0,1]`;
  `v = log10(t/t_min)/log10(t_max/t_min) ∈ [0,1]`.  `t_min` = smallest positive
  seed taper = `TAPER_LO_X·res_fine` (0.3× the robust=−2 beam); `t_max =
  TAPER_HI_X·res_nat` (20× natural).  "Dyadic" = repeated bisection of a SEED
  cell in `(u,v)` (seed nodes need not be globally dyadic).  Area `A_T` in `(u,v)`.
- **The quadtree domain starts at `t_min`.**  The **taper=0 column** and
  **natural row** stay 1-D families handled by the EXISTING
  `envelope.build_segments` machinery; they never join the quadtree.  The strip
  **`(0, t_min)`** is covered by the existing column-segment interpolation
  between the taper=0 and `t_min` points at each matching robust (via
  `ZERO_TAPER_RES_STEP`).  The **natural row** participates via the existing
  natural-as-robust-2.0 convention for PROPOSALS only (matching
  `refine.candidates_between`), never as a quadtree coordinate.

### Seed design and budget arithmetic (finding #2)

**Budget = TOTAL evaluations per map, including seed.**  Fresh-map seed
(exactly **56**, includes the two canonical `SEEDS`):

| block | count |
|---|---|
| briggs quadtree grid: 6 robusts {−2,−1.2,−0.4,+0.4,+1.2,+2} × 7 positive taper levels | 42 |
| untapered seam column: 6 briggs robusts at taper 0 | 6 |
| natural row: taper 0 + 7 positive levels | 8 |
| **seed total** | **56** |

The 6×7 briggs grid = a **5×6 = 30-leaf** seed quadtree.  A refinement of one
leaf emits a **5-point stencil** (center + 4 edge midpoints); shared edges are
deduped within a wave.  Arithmetic (honest, worst case = no sharing):

- Fresh: **plan = 110, hard audit = 140.**  Refinement headroom under plan
  = 110 − 56 = **54** evals ≈ 10–11 isolated stencils; under audit
  = 140 − 56 = **84** ≈ 16 stencils.  First minimum wave B=8 → 56+8·5 = **96**
  (< plan ✓); B=16 → 56+16·5 = **136** (< audit ✓).
- **Whole-cell, balance-aware admission:** a refinement is admitted only if
  ALL its stencil points **plus any 2:1-balance closures** (below) fit under
  the **hard audit cap**.  Never buy half a stencil.  The implementation packs
  up to `B_MAX=16` whole units and skips a unit that does not fit the remaining
  room; the resulting unit count naturally shrinks near the cap.  `B_MIN=8` is
  retained as planning guidance, not an enforced lower bound.
- Retrofit maps: **seed cost = 0** (existing rows); plan/audit count **NEW
  evals only**: **plan 40, audit 80 per map**, subject to the per-map
  certification estimate reported before any Slurm submission.

Expected fresh yield ≈ 110/(165–209 full lattice) = **53–67%**, goal-concentrated.

## Cell lifecycle & residual ownership (finding #1)

A leaf moves through states; the residual is owned unambiguously by the PARENT:

1. **untested leaf** → **stencil emitted** → **measured**: a 4-corner leaf
   queues its 5-point stencil (center + 4 edge midpoints) at its dyadic `(u,v)`
   coordinates, then all five are measured.
2. **residual computed on the PARENT** — for each of the parent's 5 new probes
   `p`, compare the measured model vector `m(p)` to the parent's bilinear
   prediction `m̂(p)` from its 4 corners; the parent's residual is

       E_T = max over p in {center,4 midpoints} of
             max_k ( |m_k(p) − m̂_k(p)| − κ·σ_k )_+ / τ_k      (L∞ over k)

   with `m = (ln res, η, skirt)`.
3. **children CERTIFIED or ACTIVATED** — if `E_T < 1` (and dominance does not
   demand more, below) the 4 children are **CERTIFIED**: they inherit `E_T` and
   are marked converged, with **no further tests**.  Otherwise they are
   **ACTIVATED**: each becomes an untested leaf eligible for its own stencil.

**Restart reconstruction.**  From the point table: rebuild the 30 seed leaves;
for each leaf, test whether all 5 stencil probes are EXACT `point_key` hits at
its dyadic coordinates.  All 5 present ⇒ the leaf was refined ⇒ compute `E_T`,
materialise the 4 children, recurse.  Corners-only ⇒ untested leaf.  This is
deterministic and needs no state file.  Bisection also requires a distinct 3×3
grid at stored `point_key` precision (three robust keys × three taper keys).
If either midpoint aliases an endpoint, the cell is terminal: no further
measurement can encode four distinct children in the source-of-truth table.

## Loss, constants, retirement

Per-leaf priority (input axes normalized, so `A_T`, `√A_T`, `λ`, thresholds and
step widths are unit-free):

    L_T = w_goal(T) · min(E_T, E_max) · sqrt(A_T)  +  λ·A_T

**Constants (manifest-pinned, finding #10):**

- model vector `m = (ln res, η, skirt)`; `τ = (ln 1.05, 0.1, 0.02)`; `κ = 2`;
  `σ` = per-map jitter from repeat rows where available, else defaults
  `σ_lnres = 0.005, σ_η = 0.02, σ_skirt = 0.005`.  Inputs `u,v` per Coordinates.
- `λ = 0.05` (exploration floor: an undiscovered interior ridge or disconnected
  contour branch cannot hide forever); `E_max = 4` (caps a step's residual so it
  cannot monopolise the queue).
- `w_goal = 3` for cells on/adjacent to a deliverable locus or the skirt binding
  band `[0.05, 0.20]`; `1` default; `0.25` for dominated cells after coverage
  (never zeroed before coverage).  The `0.25` branch is a target requirement;
  the mono implementation currently defines but does not apply it.
- wave batch `B_MAX = 16` whole units, with fewer admitted as the cap fills
  (`B_MIN = 8` guidance only); tie-break = lexicographic `point_key`.

**Two-way retirement (finding #8 half + dominance).**  A leaf retires when
EITHER (a) **residual** `E_T < 1`; OR (b) **dominance** — its optimistic bound
(corner values minus the empirical residual estimate) cannot improve any
per-contour `η` minimum by more than `τ_η = 0.1`, i.e. dominance margin
`(optimistic_η − envelope_η)/τ_η > 1` across the leaf's whole res range, with
skirt feasibility not placing it on a binding locus.  Most of the domain retires
by dominance, cheaply — "every leaf below threshold" (v1) was stronger than
needed.

## Feature classes vs scheduling state (finding #8)

Keep three orthogonal axes, reclassifiable as evidence accumulates:

- **Feature class** {smooth, step, ridge, unresolved} from the rows via the
  shared classifier (ported `refine._classify_scan`): `smooth` = interior probes
  fill within tolerance; `step` = "confirmed" (no display-eligible interior
  resolution across the edge at this density); `ridge` = "high_penalty"
  (interior probes above the rim chord); `unresolved` = insufficient evidence.
- **Evidence/confidence** — repeat-row variance vs the `κσ` deadband; a cell is
  called `smooth`/noise-consistent only with a repeatability estimate, never
  from a single-probe deadband hit.
- **Scheduling state** {untested, active, converged, frozen, dominated-retired,
  budget-stopped}.  **Precedence for multi-feature cells: step > ridge > smooth.**

## Steps and cuts (findings #4, #9)

**Cuts live on cell EDGES.**  A cut annotation is the set of leaf edges the
front crosses; each edge carries a **bracketed crossing interval** (in
normalized `u` or `v`) plus **side labels** (which corners are fine-side, which
coarse-side).  The crossed-edge axis IS the front orientation; `δ_edge` = the
bracket width along that axis, in normalized units.

**Envelope consumer rule.**  A leaf with ANY cut edge contributes **NO interior
bilinear interpolation.**  Instead it contributes its two rim sub-regions via
**LIMITING envelopes**: the corners on each side, extended to the bracket
boundary, give an upper and a lower envelope bound.  The report draws the step
at the **bracket midpoint**, with the full bracket recorded in the payload.

**Target step stopping test (finding #9; not yet implemented).**  Freeze a cut
when the two limiting
envelopes — cut placed at bracket-low vs bracket-high — differ by **less than
tolerance on every affected resolution bin** (`dη ≤ 0.1`, `d ln res ≤ ln 1.05`,
`ds ≤ 0.02`).  This is the global "envelope-stable bracket", not a bare
bracket-width test.  Localization proposals reuse the ported E1 secant / E2
progressive log-midpoint machinery along the crossed axis.

## Hanging nodes — conforming closure (finding #7)

The target is **conforming closure**: when a leaf is refined, any neighbor
sharing a hanging node must at least **register that node as a measured point on
its edge** (it is one of the refined leaf's stencil midpoints, so this is the
SAME measurement, deduped — no extra tclean).  The envelope consumer treats an
edge carrying a measured interior point as **TWO segments**.  This is the
smaller change vs re-teaching the bilinear solver.  The mono planner currently
adopted the documented fallback: **full conforming refinement of the coarser
neighbor** (costlier, simpler).  MFS-2c must either implement segmented edges
and return to the lower-cost rule, or retain full closure and account for it
explicitly in the replay/budget results.

## Point-table determinism (finding #11)

- **Effective-row rule:** the LAST `ok`|`capped` row per canonical `point_key`
  (matching the profiles convention).  `failed` rows count as "attempted" and
  are not re-proposed within a run.  Target MFS policy is re-proposable across
  runs; the current point-table reconstruction keeps them occupied across
  restarts, so MFS-2b hardening must add explicit run provenance/retry policy or
  document and approve permanent occupation.
- **Censoring:** `capped` rows are res-censored — usable for η/skirt residuals,
  but the **res residual is skipped beyond the cap** (a cap-clipped resolution
  must not manufacture a residual or step).
- **Manifest pins** (so "same table → same next wave" holds across software
  changes): spec version, classifier/loss version, all constants above, seed
  definition, band priors, `nchan`, tie-breaking (lexicographic `point_key`),
  float canonicalization (`point_key` rounding), and the distinct-3×3-key-grid
  topology floor.  This is the target MFS manifest; the current mono manifest
  is only a subset (see Current implementation baseline).

## Retrofit / warm-start mode (findings #5, #13; addendum)

Warm start = **certification-first mode**, same code path, different entry state.
With an existing map (~230–500 rows per (subarray, combo)):

- **Non-dyadic legacy rows are auxiliary evidence ONLY** (finding #5): they
  may inform classification and, once the residual model is extended to accept
  auxiliary probes, certification — but never become topology vertices.  The
  current mono code uses them for cut classification and the global envelope
  behind goal/dominance decisions; residuals use the exact five-point dyadic
  stencil.  New AMR vertices are seed-grid dyadics exclusively.
- **Retrofit seed = the fixed coarse canonical dyadic grid:** every-other of
  `ROBUST_LIST` {−2,−1.2,−0.4,0.4,1.2,2} plus every-other canonical taper, with
  the coarsest rim force-included.  Existing exact `point_key` hits cost zero;
  missing seed vertices are the first wave.  First-level dyadic midpoints land
  on the skipped step-0.4/canonical-taper lattice and are usually warm too;
  deeper refinement produces new evaluations.  The grid is not dynamically
  chosen from the union of measured/non-dyadic rows.
- The seed STAGE is skipped; build topology, run the certification pass, and
  only the unretired remainder — loci neighborhoods, cliff brackets, uncertified
  pockets — generates new evals (plan 40 / audit 80 new evals/map).
- **Gate status (finding #13):** V1 replay gates DEPLOYMENT of fresh-seed MFS
  waves; implementation is not scientifically gated, but shared-code edits are
  operationally blocked while current campaigns are live.  The July mono
  retrofit deployment was bmason-ordered and superseded V1 for retrofit only.

**Target priors (finding #14; not yet in the manifest).**  Scaled cliff
locations from the mono campaigns (∝ λ)
and the skirt goal band `[0.05, 0.20]` are **immutable manifest INPUTS per
run**, not reconstructible from the rows.  Bands are independent per-band maps
(band is NOT a third continuous axis); Ka is the only band in scope now.

## Envelope consumer changes (2c)

`sa_select/envelope.py` must gain a **leaf-cell enumerator**: the validated bilinear
`Cell` solver is reused VERBATIM per leaf; row/column segments become leaf edges
(segmented where a hanging node sits on them); cut edges emit limiting envelopes
instead of interior interpolation.  Display trims (`eta ≤ ETA_CAP`, ok+capped,
cap-clipping via `make_report.sample_from_row`) are unchanged.  The
global-lattice enumerator STAYS for legacy tables (a regular lattice is the
degenerate quadtree), so all existing campaigns keep working unmodified.  This
touches the validated solver and must be replay-guarded.  As of 1 Sep it has not
been implemented; the existing `build_cells()` point-cloud enumerator remains
the only consumer.

## Invocation & cases

**One entry point: `curvegen/adaptive.py`** (library + CLI).

    casapy adaptive.py <subarray> [--plan-only] [--budget N] [--waves N]
                       [--warm-start | --fresh]

- Combo routing now uses `NGVLA_REV` / `NGVLA_SIM_MODE` / `NGVLA_BAND` and the
  registry fields `band, ref_freq_ghz, freq_lo/hi_ghz, nchan, curve_types,
  noise_policy`. MFS combos MUST have `nchan` set via `NGVLA_NCHAN` or the
  registry (and the two must agree when both are present), else config fails
  fast before any artifact is touched.
- **Mode auto-detect:** empty table → **fresh seed**; populated table →
  **certification-first**.  Overrides: `--warm-start` / `--fresh`.
- `--plan-only` currently emits the reconstructed certification state and the
  immediate next wave without measuring.  Before MFS deployment it must also
  provide the complete expected-new-evaluation forecast required by the gate,
  or the gate must define an explicit iterative dry-run procedure.

**Run matrix:**

| combo(s) | mode | style | when |
|---|---|---|---|
| revF/track, revF/snapshot, revD/track, revD/snapshot (mono) | retrofit (warm) | `adaptive_retrofit.sbatch` indices 0–3 | deployed July; further runs only by current run sheet/bmason direction |
| revC/track (mono) | retrofit (warm) | `adaptive_retrofit.sbatch` index 4 | supported; coordinate with any active campaign chain |
| Ka MFS: 7 subarrays × {track, snapshot} (revF) | fresh seed | PyLauncher wave (MFS-4) | **not runnable: 2c/2d/MFS-4 absent and `nchan` unset** |

The old v2 examples using `submit_campaign.sh --adaptive` or setting only
`NGVLA_BAND`/`NGVLA_NCHAN` were aspirational and are not valid current launch
commands.  Mono retrofit uses explicit sbatch array indices documented in
`RUN_CAMPAIGNS.md`.  A copy-paste Ka command must not be published until MFS-2a,
MFS-2c, MFS-2d, and MFS-4 pass and bmason pins `nchan`.

## Validation gates

**V1 — retrospective replay (required, not yet implemented)** (extends MFS-1,
pure `sa_select`, no CASA).
Replay each map's full point table through the sampler policy as a simulated
acquisition (each "measurement" = a lookup).

- **Oracle (finding #3):** acceptance metrics are computed on **exact
  `point_key` hits only.**  A policy request with no exact hit = an
  **"unsupported request"**, counted and reported; fallback-to-nearest is
  allowed ONLY to keep the simulation moving, always flagged, and **never
  scored**.  **Budget exhaustion in replay = failure.**
- **Fixed stratified 10-map suite (finding #12):** revD/snapshot {main+long,
  long, main}; revF/snapshot {main+long, l+m+s+c-o}; revD/track {long,
  main+long, spiral+mid}; revF/track {long, core+spiral}.
- **Per-map metrics:** normalized sample fraction (against that map's own
  full-lattice denominator, not raw counts); pass/fail on (envelope η regret
  ≤ 0.1 per res bin; no false cuts; no missed cuts vs full-table truth; skirt
  feasibility mistakes = 0 at the four setpoints within noise).
- **Acceptance:** ALL maps pass AND p90 of the normalized sample fraction
  ≤ 0.6.  Budget exhaustion = fail.

**V2 — analytic harness (partially implemented in `tests/test_adaptive.py`).**
Required tests (finding #15): non-dyadic retrofit rows; taper=0 / natural seam;
hanging-node segmented-edge enumeration; capped / failed / retried points;
balanced-refinement budget admission (cannot cross the audit cap); cut-cell
limiting envelopes; exact-hit replay behaviour; classifier transitions
(smooth↔step↔ridge as evidence grows); deterministic ties; restart-determinism
(same table → same next wave); cell-completeness of every emitted batch.  The
current CASA-free suite covers the sampler/driver, hanging-node segmented
edges, cut-interior suppression, MFS fail-fast/routing, repeat-derived
jitter/confidence, complete capped-corner semantics, and restart-stable MFS
mode. Exact-hit V1 replay and full limiting-envelope comparisons remain. Add a
fresh-run kill/resubmit integration test that omits an in-memory mode pin and
verifies the persisted manifest prevents a topology switch.

## Task breakdown (1 Sep implementation order)

| # | Task | Status / depends |
|---|------|------------------|
| MFS-2a | Ka band axis + manifest + registry/schema (`nchan` required, fail-fast) | **built and CASA-free tested 4 Sep 2026**; no simulation launched |
| MFS-2b | Sampler core: quadtree/point-table view, residual+lifecycle, loss, feature/state machine, wave scheduler | **substantially hardened 4 Sep**; remaining deltas: per-edge/global cut freezing, failed-key cross-run retry policy, forecast/retrofit ledger, classifier reconciliation, reviewed cliff priors |
| MFS-2c | Envelope leaf-cell enumerator + cut/limiting-envelope + segmented edges | **foundation built 4 Sep** (explicit leaves, hanging segments, cut-interior suppression); full limiting envelopes remain; replay-guarded |
| MFS-2d | V1 replay harness + report (joint with MFS-1) | **not built**; depends on 2b/2c |
| MFS-2e | Retrofit-mode driver (warm start, certification estimate, sbatch glue) | **built and used for mono campaigns**; retain as regression surface, not the MFS production wave runner |
| MFS-4 | PyLauncher fresh-MFS wave runner | **not built**; depends on 2a–2d and pilot decisions |

**Implementation sequence after the active campaigns drain:** first make the
worktree reproducible (`adaptive_support.py`) and implement MFS-2a (**done 4
Sep**); next harden MFS-2b against the listed deltas; implement MFS-2c;
build/run MFS-2d/V1; only
then implement/integrate MFS-4.  These steps do not authorize simulation
submission.  Ka pilots/production remain gated by V1, the MFS-3 pilot/checkpoint,
and bmason's explicit `nchan` and noise-policy choices.

---

## v2.1 review delta (1 Sep 2026)

- Recorded the actual boundary: mono MFS-2b/2e foundation built; MFS-2a/2c/2d
  and MFS-4 absent.
- Added revC/track retrofit support and the report's conservative per-point
  adaptive validation projection.
- Added the stored-key topology floor that prevents recursive aliasing below
  the 0.01-robust / 0.001-mas `point_key` precision.
- Replaced obsolete canary and aspirational launch text with the current
  operational gate; expanded the live import surface after the
  `adaptive_support.py` refactor.
- Enumerated eleven code/contract deltas that must be closed or explicitly
  adjudicated before fresh MFS deployment.
- Marked the untracked shared helper as a reproducibility prerequisite.  No
  simulation, queue, result-table, or implementation-code change is part of
  this documentation revision.

## Original v2 changelog (finding → target resolution)

- **#1 residual ownership** → PARENT owns `E_T` (its 5 stencil probes vs its
  bilinear corner prediction); children certified (inherit) or activated;
  deterministic restart reconstruction from the table.
- **#2 budget** → seed pinned **56** (shown); fresh plan 110 / audit 140;
  retrofit plan 40 / audit 80 new-only; whole-cell balance-aware admission
  under the hard cap; B shrinks 16→8.
- **#3 V1 oracle** → exact-hit scoring only; unsupported requests counted;
  fallback flagged, never scored; replay budget exhaustion = failure.
- **#4 cut geometry** → cuts on EDGES (bracketed crossing + side labels); cut
  leaves emit limiting envelopes, no interior interp; step at bracket midpoint.
- **#5 non-dyadic rows** → auxiliary evidence only; new vertices are seed
  dyadics; retrofit seed = coarsest all-hit dyadic grid.
- **#6 seam** → quadtree starts at `t_min`; seam column + natural row stay 1-D
  families; strip `(0,t_min)` via existing column segments; natural-as-2.0 for
  proposals only.
- **#7 hanging nodes** → conforming closure (node registered as a measured edge
  point; consumer reads a two-segment edge); fallback = full neighbor refine.
- **#8 class vs state** → separate feature class / evidence / scheduling state;
  reclassifiable; precedence step > ridge > smooth; dominance retirement added.
- **#9 step stopping** → freeze when the two limiting envelopes (bracket-low vs
  -high) differ < tolerance on every res bin; `δ_edge` normalized, front =
  crossed-edge axis.
- **#10 constants** → `(ln res,η,skirt)`; `τ=(ln1.05,0.1,0.02)`, `κ=2`, `σ`
  defaults, normalized `u,v`, `λ=0.05`, `E_max=4`, `w_goal∈{3,1,0.25}`,
  `B=8–16`, retire at `E_T<1` or dominance margin >1 — all pinned.
- **#11 determinism** → effective-row = last ok|capped; failed=attempted;
  capped res-censored; manifest pins spec/classifier/loss/constants/seed/
  priors/nchan/ties.
- **#12 V1 metrics** → fixed 10-map suite; per-map normalized fraction; numeric
  pass/fail; acceptance = all pass AND p90 ≤ 0.6; exhaustion = fail.
- **#13 gate scope** → V1 gates fresh-wave DEPLOYMENT, not implementation;
  retrofit bmason-ordered (certification-first, estimate before Slurm).
- **#14 priors** → scaled cliff locations + skirt band [0.05,0.20] are
  immutable manifest inputs per run.
- **#15 V2 tests** → seam, hanging nodes, non-dyadic rows, capped/failed/
  retried, budget admission, cut limiting envelopes, exact-hit replay,
  classifier transitions, deterministic ties (listed above).

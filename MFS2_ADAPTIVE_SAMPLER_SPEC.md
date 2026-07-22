# MFS-2 adaptive sampler — design spec v2 (build contract)

**Status: v2, executable (21 Jul 2026).**  Build contract for three
implementation agents — **sampler core** (2b), **envelope enumerator** (2c),
**band axis** (2a).  Every rule is meant to be coded from without guessing;
numbers are pinned (see "Constants").  Supersedes v1 + its two appendices (codex
review + bmason addendum folded into the body; a finding→resolution changelog
closes the file).  Companion: `MFS_CAMPAIGN_PLAN.md` (bands, nchan pilots, noise
A/B, PyLauncher wave, storage — unchanged except where cited).

**Operational rule (live-code hazard).**  Campaign jobs `import` the repo at
execution time, so **do not edit `sweep.py`, `config.py`, `simulate.py`, or
`envelope.py` while any campaign job is queued or running.**  The sampler ships
as a NEW module (`curvegen/adaptive.py`) plus additive-only, replay-guarded
changes to `envelope.py`; retrofit deployment waits for the in-flight revD/track
canary (see Tasks).

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
4. **Retrofit ("backfill") is ORDERED on all four mono campaigns**
   (revF/track, revF/snapshot, revD/track, revD/snapshot) as a
   certification-first warm start — but only AFTER the in-flight revD/track
   canary campaign completes.

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
   (`sweep.FIELDS` schema, keyed by `sweep.point_key`), append-only, resumable.
   Combo routing = `-<rev>_<mode>_<band>` per `MFS_CAMPAIGN_PLAN.md`.  Every
   existing table is a valid warm start.
2. **Topology = derived view**, reconstructed deterministically from the table
   on every restart — **no pickled sampler state**.  A 2:1-balanced quadtree
   over normalized `(u, v)` (below) whose vertices are dyadic bisections of the
   seed cells; leaves are rectangles with 4 measured corners.  The taper=0
   column and natural row are 1-D families glued to the edge, never quadtree
   coordinates.
3. **Features = recomputed annotations** (never stored): the classifier — the
   ONE shared implementation ported from `refine.py`'s E2 rim classification —
   labels leaves and cut edges from the rows at build time.

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
  the **hard audit cap**.  Never buy half a stencil.  `B` shrinks from 16→8→…
  as the running total approaches the cap.
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
deterministic and needs no state file.

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
  (never zeroed before coverage).
- wave batch `B = 8–16`, shrinking to fit the cap; tie-break = lexicographic
  `point_key`.

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

**Step stopping test (finding #9).**  Freeze a cut when the two limiting
envelopes — cut placed at bracket-low vs bracket-high — differ by **less than
tolerance on every affected resolution bin** (`dη ≤ 0.1`, `d ln res ≤ ln 1.05`,
`ds ≤ 0.02`).  This is the global "envelope-stable bracket", not a bare
bracket-width test.  Localization proposals reuse the ported E1 secant / E2
progressive log-midpoint machinery along the crossed axis.

## Hanging nodes — conforming closure (finding #7)

Adopt **conforming closure**: when a leaf is refined, any neighbor sharing a
hanging node must at least **register that node as a measured point on its
edge** (it is one of the refined leaf's stencil midpoints, so this is the SAME
measurement, deduped — no extra tclean).  The envelope consumer treats an edge
carrying a measured interior point as **TWO segments**.  This is the smaller
change vs re-teaching the bilinear solver.  **Documented fallback** if that
proves heavy: full conforming refinement of the neighbor (costlier, simpler).

## Point-table determinism (finding #11)

- **Effective-row rule:** the LAST `ok`|`capped` row per canonical `point_key`
  (matching the profiles convention).  `failed` rows count as "attempted" (no
  re-propose within a run; re-proposable across runs).
- **Censoring:** `capped` rows are res-censored — usable for η/skirt residuals,
  but the **res residual is skipped beyond the cap** (a cap-clipped resolution
  must not manufacture a residual or step).
- **Manifest pins** (so "same table → same next wave" holds across software
  changes): spec version, classifier/loss version, all constants above, seed
  definition, band priors, `nchan`, tie-breaking (lexicographic `point_key`),
  float canonicalization (`point_key` rounding).

## Retrofit / warm-start mode (findings #5, #13; addendum)

Warm start = **certification-first mode**, same code path, different entry state.
With an existing map (~230–500 rows per (subarray, combo)):

- **Non-dyadic legacy rows are auxiliary evidence ONLY** (finding #5): they
  inform classification, residuals (extra probes inside their containing leaf),
  and certification — but never become topology vertices.  New AMR vertices are
  seed-grid dyadics exclusively.
- **Retrofit seed = the coarsest dyadic grid whose vertices are all EXACT
  `point_key` hits** in the table (every-other of `ROBUST_LIST`
  {−2,−1.2,−0.4,0.4,1.2,2} plus matching canonical tapers — first-level dyadic
  midpoints land on the step-0.4 lattice, so are usually warm too; deeper
  refinement produces new evals).  Missing seed vertices are the first wave.
- The seed STAGE is skipped; build topology, run the certification pass, and
  only the unretired remainder — loci neighborhoods, cliff brackets, uncertified
  pockets — generates new evals (plan 40 / audit 80 new evals/map).
- **Gate status (finding #13):** V1 replay gates DEPLOYMENT of fresh-seed MFS
  waves; **implementation is not gated** (2b/2c/2d built first).  Retrofit
  deployment is **bmason-ordered** and supersedes the gate for retrofit — but
  the certification assessment runs first and the expected new-eval counts are
  reported before any Slurm job is submitted.

**Priors (finding #14).**  Scaled cliff locations from the mono campaigns (∝ λ)
and the skirt goal band `[0.05, 0.20]` are **immutable manifest INPUTS per
run**, not reconstructible from the rows.  Bands are independent per-band maps
(band is NOT a third continuous axis); Ka is the only band in scope now.

## Envelope consumer changes (2c)

`sa_select/envelope.py` gains a **leaf-cell enumerator**: the validated bilinear
`Cell` solver is reused VERBATIM per leaf; row/column segments become leaf edges
(segmented where a hanging node sits on them); cut edges emit limiting envelopes
instead of interior interpolation.  Display trims (`eta ≤ ETA_CAP`, ok+capped,
cap-clipping via `make_report.sample_from_row`) are unchanged.  The
global-lattice enumerator STAYS for legacy tables (a regular lattice is the
degenerate quadtree), so all existing campaigns keep working unmodified.  This
touches the validated solver and is replay-guarded.

## Invocation & cases

**One entry point: `curvegen/adaptive.py`** (library + CLI).

    casapy adaptive.py <subarray> [--plan-only] [--budget N] [--waves N]
                       [--warm-start | --fresh]

- Combo routing via `NGVLA_REV` / `NGVLA_SIM_MODE` / `NGVLA_BAND` + the
  config registry (extended with `band, ref_freq_ghz, freq_lo/hi_ghz, nchan,
  curve_types, noise_policy`).  MFS combos MUST have `nchan` set (else fail
  fast).
- **Mode auto-detect:** empty table → **fresh seed**; populated table →
  **certification-first**.  Overrides: `--warm-start` / `--fresh`.
- `--plan-only` emits the next wave (and, for retrofit, the certification
  estimate + expected new-eval counts) without measuring.

**Run matrix** (copy-paste commands mirrored to `RUN_CAMPAIGNS.md` at build):

| combo(s) | mode | style | when |
|---|---|---|---|
| revF/track, revF/snapshot, revD/track, revD/snapshot (mono) | retrofit (warm) | campaign-sbatch | **after** the revD/track canary completes |
| Ka MFS: 7 subarrays × {track, snapshot} (revF) | fresh seed | PyLauncher wave (MFS-4) | **blocked on bmason's `nchan`** |

Examples — retrofit (post-canary): `bash curvegen/submit_campaign.sh revD
snapshot --adaptive --budget 80`; Ka fresh (post-nchan, in the wave runner):
`NGVLA_BAND=band4 NGVLA_NCHAN=32 casapy adaptive.py core --fresh --budget 140`.

## Validation gates

**V1 — retrospective replay** (extends MFS-1, pure `sa_select`, no CASA).
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

**V2 — analytic harness** (extend `tests/test_refine.py`'s FakeSweep maps).
Required tests (finding #15): non-dyadic retrofit rows; taper=0 / natural seam;
hanging-node segmented-edge enumeration; capped / failed / retried points;
balanced-refinement budget admission (cannot cross the audit cap); cut-cell
limiting envelopes; exact-hit replay behaviour; classifier transitions
(smooth↔step↔ridge as evidence grows); deterministic ties; restart-determinism
(same table → same next wave); cell-completeness of every emitted batch.

## Task breakdown (replaces the MFS-2 row; canary-hazard sequenced)

| # | Task | Depends | Who/effort |
|---|------|---------|-----------|
| MFS-2a | Ka band axis + manifest + registry/schema (`nchan` required, fail-fast) | — | codex build or Sonnet 5, high |
| MFS-2b | Sampler core: quadtree/point-table view, residual+lifecycle, loss, feature/state machine, wave scheduler (CASA-free, FakeSweep-tested) | 2a | Fable 5 or Opus 4.8 / GPT-5.6, high — loss+classifier semantics are the hard part |
| MFS-2c | Envelope leaf-cell enumerator + cut/limiting-envelope + segmented edges | 2b | Opus 4.8 / GPT-5.6, high — touches the validated solver, replay-guarded |
| MFS-2d | V1 replay harness + report (joint with MFS-1) | 2b,2c | Sonnet 5 / GPT-5, medium |
| MFS-2e | Retrofit-mode driver (warm start, certification estimate, sbatch glue) | 2b–2d | Sonnet 5, medium |

**Phase 1 (implementation, unblocked now):** MFS-2a → 2b → 2c → 2d.  These are
NOT gated (finding #13) and are pure code / replay — no campaign jobs, so no
live-code hazard.  **Phase 2 (deployment, canary-gated):** once the revD/track
canary finishes AND no campaign jobs are queued, run 2e's certification pass on
the four mono maps, report expected new-eval counts, then submit the retrofit
sbatches.  Ka fresh waves deploy after V1 passes AND bmason sets `nchan`.

---

## v2 changelog (finding → resolution)

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

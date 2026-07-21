# MFS-2 (revised): goal-oriented adaptive sampler — design spec

**Status: SPEC v1 + codex review (21 Jul 2026) — bmason approved the
direction; REVISE TO v2 absorbing the appended codex findings (5 blockers,
all "make the semantics executable" class) before building MFS-2b.  The V1
replay gates campaign DEPLOYMENT, not implementation (finding #13).**  Supersedes MFS scope decision 4 (the fixed reduced
lattice), which becomes this design's SEED.  Provenance: bmason's
rails/tolerance proposal (21 Jul), two codex gpt-5.6-sol xhigh consults
(sampling-strategy critique; the loss/architecture recommendations below are
adjudicated from the second), and the 21 Jul escalation-ladder work whose
mechanics this generalizes.  Companion: `MFS_CAMPAIGN_PLAN.md` (everything
there not about the lattice is unchanged: bands, nchan pilots, noise A/B,
manifest, PyLauncher wave, storage).

## Problem

The regular (robust, taper) lattice spends most of its 165–209 points on
plateaus while under-sampling exactly where the (res, eta, skirt) outputs
move fastest; defect-driven polishing then back-fills.  For MFS the band
axis multiplies every sample by 6 (~55–70k tcleans done naively).  We want
samples distributed against OUTPUT-space tolerances, with genuine
discontinuities (snapshot taper-onset cliffs) localized and preserved rather
than chased or splined over.

**Tolerances (bmason, 21 Jul):** eta 0.1 absolute; resolution 5%
(ln 1.05) on smooth pieces; skirt 0.02 ABSOLUTE.  Across a classified step
no pointwise tolerance applies — the deliverable there is the step's
input-space location bracketed tightly enough that moving it anywhere within
the bracket changes the derived envelopes by less than the output tolerances
("envelope-stable bracket").

## Architecture (3 layers)

1. **Point table = source of truth.**  The existing per-subarray results
   CSVs (plus the band axis of original MFS-2 scope: key gains band via the
   `-<rev>_<mode>_<band>` combo routing; schema/registry/manifest per
   `MFS_CAMPAIGN_PLAN.md`).  Every measured (weighting, robust, taper) →
   (res, eta, skirt, status) row, keyed by `point_key`, append-only,
   resumable.  NOTE: any existing campaign's table is a valid warm start —
   see "Retrofit mode".
2. **Topology = derived view.**  A nested, 2:1-balanced quadtree over
   (robust, log10 taper) whose vertices are dyadic subdivisions of the seed
   grid; leaf cells are axis-aligned rectangles with 4 measured corners.
   Reconstructed deterministically from the point table on every restart —
   NO pickled sampler state.  Hanging nodes are measured (one tclean beats
   interpolation bookkeeping).  The untapered column and natural row remain
   special 1-D families glued to the quadtree edge (taper=0 cannot live on
   a log axis).
3. **Features = recomputed annotations.**  The classifier (ported from
   refine.py's E2 rim classification, ONE shared implementation) labels
   cells {smooth | step | ridge | noise} from the point table at build
   time; classified steps become CUT annotations the envelope consumer must
   not interpolate across.  Nothing stored; recompute-from-rows keeps the
   resumability contract.

## Seed design

Coarse tensor product: robust {−2, −1.2, −0.4, +0.4, +1.2, +2} (6) ×
taper {0 + 6 log-spaced levels spanning 0.3×fine-seed-beam to 20×natural}
(7) = 42 points, PLUS the full natural+taper row (the eta reference and the
ptsrc backbone right of natural) ≈ 56 points/map.  This CONTAINS bmason's
four rails as the boundary rows/columns; interior seeds are mandatory
(imaging winners and sparse-snapshot ptsrc winners are frequently interior
— rails alone under-determine both).  Seeds are also the QA gate (beam
caps, natural reference) exactly as campaign prep is today.

## Loss and scheduling

Per leaf cell T, tolerance-scaled **hierarchical residual** (interpolation
error, not raw gradient): when a new probe y lands in T,

    E_T = max_k ( |y_k − ŷ_T,k| − κ·σ_k )+ / τ_k        (L∞ across outputs)

with ŷ_T the parent cell's bilinear prediction, τ = (ln1.05, 0.1, 0.02),
κ≈2 against the measured noise floors (eta jitter 0.01–0.03; skirt
repeatability TO BE MEASURED in the MFS-3 pilot — if σ_skirt ≳ 0.01 the
0.02 tolerance needs a bmason revisit).  Priority:

    L_T = w_goal(T) · min(E_T, E_max) · sqrt(A_T)  +  λ·A_T

- `w_goal`: boosted when T's output box intersects the current
  non-dominated (eta, res) envelope or the skirt = 0.10 ± 0.03 band;
  strongly deprioritized (never zeroed before coverage is met) when clearly
  dominated.
- `λ·A_T`: input-space exploration floor so an undiscovered interior ridge
  cannot hide forever.
- `E_max` cap: a step's residual is bounded so it cannot monopolize the
  queue (steps get their own scoring below).

Scheduling is wave-batched for Slurm/PyLauncher: take the top-B
non-adjacent cells (B ≈ 8–16 = one node-packing unit), emit their
subdivision points (center + edge midpoints, shared edges deduped,
**always cell-complete** — the E0 rule: isolated points are invisible to
the envelope), measure, re-derive topology, repeat.  Stop when every leaf
has L_T below threshold or is terminally classified, or at budget.
**Budget: plan 80 evaluations/map, hard audit at 110–120** (vs 165–209
regular) — expected 35–60% of grid per the codex estimate.

## Feature state machine

unknown → {smooth, step, ridge, noise}, recomputed from rows:

- **smooth**: refined by E_T until below tolerance.
- **noise**: residuals within the κσ deadband → stop (never chase jitter).
- **step** (rim-only classification, as E2 does today): STOP scoring by
  jump height; score by input-location uncertainty E_step = h⊥/δ_edge
  (bracket width across the front, in input units).  Refine — using the
  ported E1 secant / E2 progressive log-midpoint proposals along the
  crossing axis — until the bracket is envelope-stable; then freeze, keep
  both rims, annotate the cut.  The envelope consumer draws the step
  sharply and the display smoother's segment-split rule already refuses to
  bridge it.
- **ridge** (interior, above-chord, confirmed by probes): mask once shown
  dominated relative to the envelope, retaining a small exploration weight
  (a ridge can become Pareto-relevant when the skirt setpoint changes).

## Envelope consumer changes

`sa_select/envelope.py` gains a leaf-cell enumerator: the validated
bilinear `Cell` interior solver is reused VERBATIM per quadtree leaf;
row/column segments become leaf edges; cut annotations disable
interpolation across steps.  Display trims (eta ≤ 5, ok+capped,
cap-clipping via `sample_from_row`) unchanged.  The global-lattice
enumerator stays for legacy tables (a regular lattice is the degenerate
quadtree), so all existing campaigns keep working unmodified.

## Bands

Independent per-band maps (band is NOT a third continuous axis).  Warm
start: taper levels and known feature locations (cliff positions, cap
boundaries) scale ∝ λ from the completed 30 GHz campaigns; suspected
features seed cells at 'unknown-but-suspected' priority.  All fixed-window
MFS semantics (A4), nchan floors/pilots (A1/A2), noise policy (A5), cost
model (A6), and the wave runner (A7/MFS-4) are unchanged from
`MFS_CAMPAIGN_PLAN.md`.  fill_grid.py must NOT run on adaptive combos
(manifest guard, as already planned for the reduced lattice).

## Retrofit mode (bmason's "fill the v1 holes" bet)

Because the point table is the source of truth, running the sampler on an
EXISTING campaign map is just a warm start where the seed is already
super-complete: the sampler will (a) tighten cliff-location brackets that
the 21 Jul escalation wave localizes only to its scan density, and (b) probe
coverage-floor cells the defect-driven ladder never visits.  Whether this
is worth node-hours is decided AFTER the 21 Jul wave lands + V1 replay:
if the wave's escalated refine (NOT the old polishing — it already targets
holes with output-conditioned probes) leaves specific under-converged maps,
retrofit those maps first as the sampler's pilot deployment.

## Validation gates

- **V1 — retrospective replay (extends MFS-1, pure sa_select, no CASA):**
  replay the four completed mono campaigns' full point tables through
  (i) the reduced-lattice mask (original MFS-1), (ii) this sampler's policy
  (simulated acquisition: the "measurement" is a lookup, with nearest-row
  fallback and a flagged interpolation-error caveat where the policy asks
  for unmeasured points).  8–12 representative maps including the worst
  snapshot/cliff cases.  Metrics: envelope eta regret per resolution bin,
  skirt-feasibility mistakes, genuine-hole preservation (no manufactured
  interior resolutions), tolerance-scaled envelope distance, and p90 (not
  median) sample count.  ACCEPT the sampler for MFS if p90 ≤ 60% of the
  regular grid with defect metrics no worse than the lattice+escalation
  baseline.  The scattered/Delaunay engine rewrite is REJECTED unless a
  simplex policy beats the accepted AMR by a further ≥30% at p90 — and if
  ever built, cuts must be first-class (no simplex interpolation across
  cliffs) per the codex architecture note.
- **V2 — analytic harness:** extend tests/test_refine.py's FakeSweep maps
  (cliff, sawtooth, fillable gap, bump, plateau) to the sampler: correct
  classification, budget respect, restart-determinism (same table → same
  next wave), cell-completeness of every emitted batch.

## Task breakdown (replaces MFS-2 row; MFS-1/3/4/5/6 unchanged)

| # | Task | Depends | Who/effort |
|---|------|---------|-----------|
| MFS-2a | Band axis + manifest + registry/schema (original MFS-2 scope) | — | codex build or Sonnet 5, high |
| MFS-2b | Sampler core: quadtree/point-table view, loss, state machine, wave scheduler (CASA-free, FakeSweep-tested) | 2a | Fable 5 or Opus 4.8 / GPT-5.6, high — the loss+classifier semantics are the hard part |
| MFS-2c | Envelope leaf-cell enumerator + cut annotations | 2b | Opus 4.8 / GPT-5.6, high — touches the validated solver, replay-guarded |
| MFS-2d | V1 replay harness + report (joint with MFS-1) | 2b,2c | Sonnet 5 / GPT-5, medium |
| MFS-2e | Retrofit-mode driver (existing-map warm start) | 2b–2d + wave results | Sonnet 5, medium |

Order: MFS-1 ∥ MFS-2a → 2b → 2c → 2d (**bmason gate**) → MFS-3 pilots
(unchanged) → MFS-4/5 → waves.  2e opportunistic after the 21 Jul wave.

## Open risks

- Skirt repeatability vs the 0.02 tolerance (measure in MFS-3; revisit κ).
- Classifier false positives: a "confirmed" cut where denser sampling would
  have filled — mitigated by the envelope-stable bracket criterion +
  V1 replay's genuine-hole-preservation metric + report annotation of every
  cut so a human can audit.
- Quadtree depth explosion along curved fronts — E_max cap + per-feature
  budgets + the step state machine (localize, don't tile).
- The natural row / taper=0 column glue (log-axis boundary) is where
  implementation fiddliness concentrates; keep it a special-cased 1-D
  family exactly as the current engine treats rows.

---

# APPENDIX: codex review findings (gpt-5.6-sol high, 21 Jul 2026) — ADJUDICATION PENDING

Verdict: architecture endorsed; 5 blockers + 8 high + 2 medium, all
'semantics not yet executable' class.  REVISE THIS SPEC TO v2 (absorbing
or explicitly waiving each item below) BEFORE building MFS-2b.  Quick
adjudications by Fable at hand-off: #13 accept (the V1 gate applies to
campaign DEPLOYMENT, not implementation — 2b/2c/2d get built first);
#10 accept (model (ln res, eta, skirt); normalize inputs; pin lambda,
E_max, thresholds numerically); #3 accept (acceptance metrics from
exact-hit oracle points only; fallback-derived outputs excluded);
#2 accept (budget = TOTAL including seed; scheduler shrinks B near the
audit line; whole-cell admission); #1/#4/#5/#6/#7/#9 accept in
principle — each needs the concrete rule written; #8/#11/#12/#14/#15
accept.  None rejected.  Full findings verbatim:

Verdict: blockers are present, so **not “NO blockers.”** The architectural direction remains sound, but several semantics are not yet executable or would invalidate V1.

I could not perform the literal repository cross-check because workspace reads failed before execution with an environment “No space left on device” namespace error. The standing-plan comments below therefore use the constraints quoted in this spec, not a fresh read of `MFS_CAMPAIGN_PLAN.md`.

1. **BLOCKER — Hierarchical residual ownership is undefined.**  
   `E_T` is defined only after a probe lands in `T`, but the initial leaves contain corners only, and after subdivision those probes become corners of the children. The spec never says whether the resulting residual belongs to the parent, all children, or some aggregation. Consequently neither “every leaf below threshold” nor restart reconstruction has a unique implementation. Define a cell lifecycle such as: untested leaf → emit fixed five-point stencil → compute the parent’s maximum hierarchical surplus → either certify its children or activate them for their own future tests.

2. **BLOCKER — Seed, batching, and budget arithmetic are incompatible.**  
   The nominal seed is approximately 56 evaluations. Eight non-adjacent refinements add up to five new points each, so the first minimum-size wave reaches roughly 96; sixteen reach roughly 136. That already exceeds the planned 80 and can exceed the 110–120 audit, before 2:1 balance closure or retries. “≈56” is also too imprecise for a hard budget. Specify:

   - Exact natural-row levels and overlaps.
   - Whether 80 means total or post-seed evaluations.
   - Whether the scheduler may reduce `B`.
   - A whole-cell, balance-aware admission rule that cannot cross the hard audit.

3. **BLOCKER — V1’s nearest-row fallback cannot support an acceptance gate.**  
   A nearest existing row is not the requested AMR measurement, especially near the very cliffs and holes being tested. Its interpolation error is unknowable without the missing true evaluation; merely flagging it does not remove bias. The sampler could appear efficient because the replay oracle silently snaps difficult requests onto favorable existing points. Gate metrics must use exact hits, a separately validated oracle with uncertainty bounds, or treat unsupported requests as replay failures requiring CASA measurements. Report exact-hit fraction and fallback distance, but do not use fallback-derived outputs for acceptance.

4. **BLOCKER — CUT geometry is insufficiently specified for the envelope consumer.**  
   A cut through a rectangular leaf cannot both “disable interpolation across the step” and reuse the existing bilinear `Cell` solver verbatim on that leaf. Four corners do not identify the front’s geometry or which side owns each interior region. The annotation needs at least bracketed edge crossings, side labels, and a rule for ambiguous cut bands. Then either polygonize the two sides, exclude the cut cell’s interior, or compute limiting envelopes. “Draw the step sharply” is not an implementable contract.

5. **BLOCKER for retrofit mode — Arbitrary existing tables do not reconstruct a dyadic quadtree.**  
   Fresh AMR points can be constrained to seed-grid dyadics; legacy regular-grid and escalation points generally cannot. “Super-complete warm start” therefore does not follow from point-table source-of-truth. Define whether non-dyadic rows are:

   - Auxiliary observations used for classification/loss but not topology;
   - Snapped under an explicit tolerance;
   - Inserted through a different constrained mesh; or
   - Ignored except at exact AMR vertices.

   The retrofit budget must also count new evaluations separately from pre-existing rows.

6. **HIGH — The natural/taper-zero glue has two unresolved topology problems.**  
   Taper zero is included in the 42-point tensor product but cannot border the positive-taper quadtree in log coordinates without defining what covers `(0, taper_min)`. A disconnected 1-D column leaves that interval unsampled; interpolating across it needs a coordinate rule. Natural weighting is categorical, not automatically a robust-axis edge, unless an explicit equivalence is declared. Specify seam ownership, interpolation policy, and the natural/robust intersection deduplication.

7. **HIGH — Hanging nodes contradict the four-corner solver contract.**  
   A 2:1-balanced coarse leaf next to a refined leaf has a measured midpoint on its edge. Treating the coarse leaf as a four-corner cell ignores that datum; enumerating both the coarse edge and the two fine edges produces overlapping/inconsistent segments. Either require a conforming refinement closure, teach the consumer about segmented edges, or define that hanging-node measurements do not participate on the coarse side.

8. **HIGH — Classification and convergence are conflated.**  
   “Residuals within the deadband” establishes consistency with a smooth/noise-adjusted model; it does not classify a cell as noise. Noise requires repeatability evidence or another variance estimate. Likewise, a ridge is called terminally maskable but also retains exploration weight—those cannot both govern the stop rule. Separate:

   - Feature class: smooth, step, ridge, unresolved.
   - Evidence/confidence.
   - Scheduling state: untested, active, converged, frozen, invalid.

   Permit reclassification as evidence accumulates and define precedence for cells containing more than one feature.

9. **HIGH — Step localization is not yet an executable stopping test.**  
   `h⊥/δ_edge` needs normalized coordinates, a defined front orientation, and a concrete `δ_edge`. More importantly, “envelope-stable” is global and cannot be inferred from bracket width alone. Compute envelopes for both limiting cut positions and freeze only when their difference is within the output tolerances on a stated resolution-bin support. Preserve the entire ambiguous bracket rather than selecting an unjustified sharp location.

10. **HIGH — The loss needs transformed outputs and uncertainty propagation specified.**  
    Resolution tolerance `ln(1.05)` requires interpolation and residuals in `ln(res)`, not raw resolution. State the modeled vector explicitly as `(ln res, eta, skirt)`. The prediction uncertainty should combine probe noise with the bilinear corner uncertainties, rather than subtracting one generic `σ_k`. Normalize both input axes before using `A_T`; otherwise `sqrt(A_T)`, `λ`, thresholds, and step widths depend on robust/log-taper units. Values for the threshold, `λ`, `E_max`, and goal-weight multipliers are also required for deterministic replay.

11. **HIGH — Point-table determinism omits failures, retries, censoring, and configuration.**  
    “Measured corners” does not say what happens when a tclean fails or is capped. Cap-clipped resolution is censored data and can create a false residual or step. Append-only retries can give multiple rows for one `point_key`; the effective-row rule must be deterministic. Pin seed construction, classifier/loss versions, all hyperparameters, band priors, float canonicalization, and tie-breaking in the manifest. Otherwise “same table → same next wave” is false across software/configuration changes.

12. **HIGH — V1 acceptance metrics are under-specified.**  
    With only 8–12 maps, p90 is nearly a worst-map statistic and should use a fixed, stratified suite. Take p90 of each map’s normalized sample fraction, not raw counts against varying 165–209 denominators. Budget exhaustion must count as failure, not as a low sample count. “No worse” needs numerical margins for each defect metric. The replay arms also name reduced lattice and sampler, while acceptance references “lattice+escalation”; that baseline acquisition policy must be explicitly included. Add convergence rate, unresolved-cell mass, false/missed-cut rates, bracket width/stability, and exact-oracle coverage.

13. **HIGH — Two claimed inherited-plan orderings conflict internally.**  
    The status says the “build” is gated on V1, but tasks 2b and 2c must be built before 2d can run V1. The sensible interpretation is that **campaign deployment**, not implementation, is gated; say that. Also, skirt repeatability is learned in MFS-3 after the V1 gate, yet it affects the sampler loss and possibly the tolerance itself. Either move the repeatability measurement earlier or make V1 provisional with a required `σ_skirt` sensitivity sweep.

14. **MEDIUM — Priors and goal semantics contradict “features only from rows.”**  
    Scaled cliff/cap priors and “unknown-but-suspected” priorities are state outside the rows. That is fine, but they must be immutable manifest inputs, not described as reconstructible from the point table alone. Similarly, `skirt = 0.10 ± 0.03` must be a configured campaign goal; the ridge discussion explicitly anticipates changing the skirt setpoint.

15. **MEDIUM — V2 is missing the tests most likely to catch integration failures.**  
    Add tests for non-dyadic retrofit rows, natural/taper-zero seams, hanging-node enumeration, capped/failed/retried points, balanced-refinement budget admission, cut-cell limiting envelopes, exact-hit replay behavior, classifier transitions, and deterministic ties.

Subject to the unavailable file-level check, the quoted standing constraints on independent bands, fixed-window/nchan semantics, noise A/B policy, the existing wave runner, and guarding `fill_grid.py` are not otherwise contradicted. The strongest parts worth retaining are the output-tolerance residual, cell-complete acquisition, explicit cuts, point-table resumability, and treating band as independent rather than a third AMR axis.
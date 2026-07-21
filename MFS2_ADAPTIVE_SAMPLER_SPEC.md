# MFS-2 (revised): goal-oriented adaptive sampler — design spec

**Status: SPEC (21 Jul 2026) — bmason approved the direction; build gated on
MFS-1/V1 replay.**  Supersedes MFS scope decision 4 (the fixed reduced
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

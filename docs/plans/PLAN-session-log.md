---
split_from: docs/plans/PLAN.md (lines 483-988 at commit 7f0a63f)
history: git log --follow docs/plans/PLAN.md
---
### HANDOFF STATE (7 Jul 2026 — read this first)

**SESSION DELTA (15 Jul 2026, Fable):**
- All four campaign reports EXIST and are FRESH (newer than their curve
  CSVs; the campaign collect stage builds them): `curvegen/reports/`
  revf-curves.html (14 SAs), revF-snapshot-curves.html (14),
  revD-track-curves.html (9), revD-snapshot-curves.html (9).  bmason review
  pending.  QA note: mid+long has only ~53 samples in BOTH snapshot
  reports (vs ~150 track) — consistent across revisions, so probably
  genuine snapshot-uv pruning, but eyeball its heatmap first.
- **Long b_min correction (supersedes the note in item 1):** Rev F Long is
  10 clusters x 3 antennas; intra-cluster baselines span 37–176 m, then a
  clean gap to 515 km.  A ~150 m cut is therefore WRONG (leaves the 176 m
  intra-cluster pair); any cut in (176 m, 515 km) works — use e.g. 1 km.
  The filter must be COMPONENT-AWARE: filter only Long's intra-cluster
  pairs, then b_min(combo) = min over components' legitimate b_min
  (e.g. main+long keeps core's real 42.15 m).  Long-only filtered
  b_min = 515 km (LAS ~4 uas at 30 GHz).  Analysis: single-linkage
  clustering on curvegen/configs/long.cfg, 15 Jul session.
- Queued next: bmason reviews the 3 new reports; long-family refine passes
  (standing caveat) when node-hours are approved; milestone commit of the
  RevD/snapshot campaign state (uncommitted since 74470c0); optional
  cross-revision/mode comparison report (spec deliberately before building).
  **[All four addressed in part 2 below, same day.]**

**SESSION DELTA (15 Jul 2026, Fable — part 2: defect diagnosis + fixes +
combined report + $WORK migration).**  bmason eyeballed the three new
reports and flagged uneven curve quality; full diagnosis, fixes, and staged
follow-ups below.  Codex (gpt-5.6-sol) consulted on the physics/diagnosis
and guard-reviewed the diff; a quantitative "curve census" (subagent,
reproducing make_report.build_curve exactly per campaign) grounded it.

*Diagnosis — every flagged defect mapped to a cause:*
1. **Refine starvation, three ways.**  (a) The campaign refine budget (60)
   was exhausted on the sparse fresh lattices; worst in-band eta steps
   0.36–1.53 survived (revD-track main+long 1.16 double-jump @0.9 mas,
   spiral+mid 2x0.36 staircase, mid+long 0.27 spike; snapshot main+long
   1.42/1.53 @~3.3 mas; etc.).  (b) `refine.samples_from` did NOT apply the
   report's eta<=5 display trim, so budgets were BURNED on invisible eta~5+
   fringe jumps — e.g. snapshot spiral "worst step 0.92" (identical in both
   revisions, suspicious-looking) while its rendered curve was already
   smooth at 0.10.  (c) refine only ever chased the IMAGING curve, so
   point-source steps (revF-snapshot main 0.45, main+long 1.42; even
   revF-track main+long 0.38) were never targets.
2. **One corrupt measurement**: revF-snapshot `long` briggs r=-2 t=6.332mas
   recorded ok with bmaj=bmin=1e-6", sigma=0, skirt=0 (an empty tclean
   product with a sentinel beam).  It alone caused the "LONG = dots" render
   (a lone curve point 324x finer than everything else).  Archived to
   `results-revF_snapshot/attic-degenerate/`, re-collected.
3. **Snapshot sub-natural absence is PHYSICS, not missing data**: with one
   60 s integration each baseline is one uv sample; on the Briggs density
   grid (uv cell = 1/(imsize*cell)) nearly every occupied cell holds <=1
   visibility, so Briggs == natural (core snapshot r=-2 shrinks the beam
   0.5% vs 30% for the track).  Established on the UNTAPERED lattice rows,
   where cell (hence the density grid) is identical across robust — immune
   to the adaptive-cell caveat below.
   Only composites (dense multi-occupancy core cluster) go sub-natural
   (main 0.55x). Verified numerically; codex concurs, with the caveat that a
   REAL snapshot has bandwidth/multi-dump uv filling — a monochromatic
   1-dump sim understates robust's lever (logged as an open control, below).
   Documented in-report (snapshot combos get a header note).
4. **mid+long snapshot ~53 usable points is real cap censoring** (175/228
   lattice points land beyond mid's natural-beam cap) and **LONG snapshot
   fragmentation is honest sparse instantaneous coverage** (plus item 2 in
   revF's case); revD-snapshot long keeps 3 genuine x1.4–2.0 in-window gaps
   (taper grid too coarse where beam(taper) moves fast).

*Fixes implemented (98 tests green):*
- `sweep.py run_point`: degenerate-product guard — fail (never ok) when
  bmin < 1 CELL or sigma<=0 or non-finite; stderr warning below 3 cells.
  (1 cell, not 2: legitimate far-coarse LONG rows fit bmin ~1.6–2.0 cells
  under the adaptive-cell convention — the sentinel sits at 0.001 cells.)
- `collect.py`: same check at publish time (hard fail, like the stale-cell
  guard); provenance `source` tag now rev/mode-aware for non-default combos
  (default stays byte-identical "revf-sim").
- `refine.py`: samples now eta<=ETA_CAP-trimmed EXACTLY like the report;
  chases BOTH imaging and point-source curves (same bracketing generator,
  jumps unioned); res-gap chasing still capped-subarrays-only.
- Campaign plumbing: `submit_campaign.sh --refine-budget N --refine-rounds M`
  -> `NGVLA_REFINE_BUDGET/ROUNDS` -> `campaign_sweep.sbatch` refine call.
- 3 new campaigns re-collected (revf_snapshot_curves.csv is 1 corrupt row
  lighter; labels fixed).
- **Staged for bmason (docs/ops/RUN_CAMPAIGNS.md §1): four POLISH campaigns**
  (budget 200, rounds 8; prep/sweep/fill are resumable no-ops, only refine
  runs).  Order free; revF/track last/optional (its two ptsrc steps).
- **NOT changed on purpose**: mid+long snapshot capping (honest physics),
  LONG snapshot dot/segment rendering (honest gaps — now explained by the
  in-report snapshot note), the fixed-FOV adaptive-cell weighting convention
  (documented trade-off; codex flagged that FOV varies with cell across a
  taper row — acknowledged, deliberate, collector-enforced since 9 Jul).

*Combined all-campaigns report (bmason feature):*
`make_report.py --combined reports/ngvla-curves.html` gathers ONE payload
per registered combo (each built by a subprocess with that combo's env —
config freezes RESULTS_DIR at import) and injects
`{payloads, combos, default}`; the template now has a **campaign dropdown**
(top-right of the header) that swaps DATA and re-renders the whole page.
Template re-architected from render-once to `bindData()` + idempotent
`render*()` functions under `renderAll()`; listeners wired once; s0 choice
survives campaign switches; snapshot combos show the physics note card; the
hardcoded Rev-F profile/QA diagnostic cards hide on other combos (closing
the old "cosmetic limitation").  Per-combo reports build exactly as before;
`campaign_collect.sbatch` now refreshes BOTH.  JS syntax esprima-checked;
subagent logic review of the refactor.  16 MB with all four campaigns.
`--payload-json` is the new subprocess interface.

*MS migration + regeneration insurance (bmason directive):*
- MS stores (the only expensive scratch assets; results CSVs live in git)
  **moved to `$WORK/ngvla_curvegen/`** (8.7 GB rsync, verified 16/16 MSes)
  because $SCRATCH is purged.  `curvegen/ms` symlink repointed; non-default
  combos route via new env `NGVLA_MS_BASE` (default `$WORK/ngvla_curvegen`
  in every campaign sbatch; falls back to NGVLA_SCRATCH for laptops).
  tclean work dirs (TempLattice churn) deliberately STAY on scratch.
  NB an interactive sweep without NGVLA_MS_BASE set still resolves the old
  scratch path for non-default combos — export it (or use the sbatches).
- `curvegen/regen_ms.sbatch` (`sbatch --array=0-3 ...`): one task per combo
  re-simulates any MISSING MS into $WORK; idempotent insurance, a few
  node-hours from nothing.  Old scratch copies left in place (purge will
  reap them).

*Codex guard review of the diff (gpt-5.6-sol, threaded) — adjudication:*
- FIXED per review: NaN/Inf fail-open in both degenerate guards (finiteness
  + positivity on bmaj/bmin/res/sigma/cell, natural-reference row validated
  before eta division); standalone per-combo reports now carry
  `payload.combo` so the snapshot note / per-combo header / Rev-F-reference
  card gating work OUTSIDE the combined report too; refine-budget env vars
  are always exported explicitly (a stale NGVLA_REFINE_* in the submitting
  shell could silently make a default campaign a polish pass) + integer
  validation; refine candidate selection is now severity-ranked round-robin
  per jump (flat sorted-set truncation could let one pathological jump
  starve the rest); collect.py + make_report.py write via tmp+os.replace
  (4 concurrent polish collects share ngvla-curves.html); MS migration
  verified by rsync checksum pass.
- REJECTED with rationale: 2-cell hard floor (legit LONG rows at 1.6-2.0
  cells; codex accepted the 1-cell floor + 3-cell warning split).
- REWORDED per review: the snapshot note no longer claims a "fixed-FOV"
  convention (imsize is fixed, cell adapts to taper, so FOV/density grid DO
  vary along a taper row — a deliberate, collector-enforced convention since
  v2) and states the sub-natural conclusion via the untapered rows; LONG
  fragmentation now "consistent with sparse instantaneous coverage" rather
  than conclusively "honest gaps" (dense diagnostic scans still pending).

*Logged-for-later (codex advisories, not blocking):* dense 1-D taper scans
as a diagnostic for any jump that survives the polish pass (distinguishes
budget artifact / beam-fit lobe switch / constraint-branch transition);
bisection-style direct resolution targeting in refine; a bandwidth+
multi-dump-realistic snapshot control sim (does robust get a lever back?);
reporting bmaj/bmin/axis ratio for snapshot beams (res_geo hides
elongation; data exists in results CSVs, needs schema thought); analytic
eta from gridded weights as a noise-free cross-check; PSF-peak/main-lobe
independent beam sanity checks.

*ASK BMASON (non-blocking, defaults chosen):*
1. Snapshot convention: we ACCEPT "snapshot curves start at ~natural for
   sparse subarrays" as the honest answer under the standard memo-121
   convention (report says so).  If snapshot forecasting fidelity matters,
   the bandwidth-realistic control sim above would tell us how much lever
   real continuum snapshots recover.  OK?
2. Keep offering LONG-family snapshot curves at all (fragmented but
   honest), or drop them from the snapshot registry rows?
3. Eyeball the new combined report (reports/ngvla-curves.html) — the four
   per-combo reports remain but the combined one is intended to be THE
   report going forward.

*Future goal noted (bmason, 15 Jul): per-subarray PSF plots and cuts in the
report for the selected subarrays.*  DESIGNED same day — see the dedicated
section below ("PSF inspector plan").

**SESSION DELTA (16 Jul 2026, Fable — polish crash + relaunch + P3/P4).**
1. *15 Jul polish attempt crashed*: Slurm inherits the SUBMISSION dir as
   cwd; refine.py's big tcleans dumped TempLattice into the repo on $HOME
   until the 14 GB quota filled (casacore "Disk quota exceeded" core
   dumps).  FIXED: all campaign sbatches pin cwd to
   `$NGVLA_SCRATCH/run_<jobid>[_<task>]`; ~9 GB debris deleted; also fixed
   `fill_beam_caps.py` hard-exiting on the default combo (first
   revF/track-through-submit_campaign ever).  Commit 553a765; post-mortem
   in docs/ops/RUN_CAMPAIGNS.md.  Second failure mode found: the per-user
   queued-job LIMIT silently kills later sbatch calls when 3-4 campaign
   chains stack up (cost revD/track its collect job TWICE) — gotcha below.
2. *16 Jul relaunch (bmason, 3 campaigns): DONE.*  All sweeps completed;
   revD/track's collect was run locally (queue limit again).  All three
   campaigns' curve CSVs + reports + PSF payloads are CURRENT.  Polish
   verdict: budget exhaustion is gone (except revD/track `long`, 1.21
   imaging, budget-limited — a resubmit continues it); most flagged
   defects FIXED (revF/snapshot main+long imaging 1.42→0.24; revD/track
   mid+long spike and main ptsrc gone); survivors (residual table in
   docs/ops/RUN_CAMPAIGNS.md) all stopped on CANDIDATES EXHAUSTED — dense local
   sampling didn't move them, which per the polish assumption is now real
   evidence of physics/branch transitions (esp. the snapshot natural-end
   ptsrc cliffs: main+long revD/snapshot 1.58).  Next levers = dense 1-D
   taper scans / bisection targeting in refine (codex advisories), or
   accept + document.  bmason decision point.
3. *P3+P4 BUILT* (see the PSF inspector section): exporter + report panel,
   codex build mode (sandbox works again), commit be0003e.  revF/track
   polish is the one campaign still to launch; P1 (cut capture) next,
   then P2 backfill AFTER revF/track polish lands.
4. bmason wrote two reference notes at repo root (untracked, theirs):
   `docs/architecture/ETA_JUMPS.md` (why eta jumps happen; the polish assumption) and
   `docs/ops/POLISH_AND_STORAGE.md` (how polish samples; the $WORK/$SCRATCH
   layout).

**SESSION DELTA (21 Jul 2026, Fable — state audit: revF/track polish LANDED
→ POLISH 4 of 4 DONE).**
1. *revF/track polish ran 16 Jul 16:19–16:39* — bmason launched it minutes
   after commit c643dca, so the committed docs still said "still to
   launch".  Full chain COMPLETED (prep 3318072 → sweep 3318073_0–5 →
   collect 3318074; first revF/track end-to-end through
   submit_campaign.sh).  Outcome (sweep logs): only
   long+mid+spiral+core-outer took new points (+5; ptsrc worst in-band
   step 0.49→0.42; ended round 3 "1 jumps, 0 new points" = CANDIDATES
   EXHAUSTED); main+long ptsrc stays 0.38 (+0, candidates exhausted); ALL
   imaging curves ≤0.19; everything else ≤0.25 on both curves.  **POLISH
   IS COMPLETE (4 of 4).**  Queue empty since 16 Jul 16:39.
2. *Reports are CURRENT — no regen needed*: the 16:39 collect rebuilt
   revF-track-curves.html + the combined ngvla-curves.html + PSF payloads
   (`reports/psf/revF_track`) with HEAD code (c643dca touched only
   planning docs).  revF/track's PSF panel still shows "pending backfill"
   by design until P2.  Survivors table in docs/ops/RUN_CAMPAIGNS.md gained the
   revF/track row.
3. *Milestone commit (this one)*: routed `revf_curves.csv` (4038 samples)
   + `results/long_mid_spiral_core_outer.csv` (+5 refine points) + these
   doc updates (PLAN/NEXT_AGENT/RUN_CAMPAIGNS).
4. Housekeeping: `revDsnapshotIssue.txt` (13 Jul, untracked) predates the
   successful 16 Jul relaunch — resolved/stale.  P2 anchor backfill is now
   UNBLOCKED (polish landed); order stays P1 → P2.  MFS-1/-2 (CASA-free)
   can start any time; MFS-3 pilots still gated on the bmason checkpoint.
   The only re-launch candidate is the optional revD/track polish resubmit
   (continues its budget-limited `long` imaging refine, 1.21; all else
   no-ops) — part of bmason's standing survivors decision (a/b/c above).

**SESSION DELTA (21 Jul 2026, part 2, Fable — curve-quality upgrade:
escalated refine + display smoothing + P1 + P2).**
1. *bmason review of the polished curves: not good enough.*  Flagged: huge
   ptsrc jumps (revF/snap main+long & main; revD/snap main+long 1.58 &
   main); disconnected points (revF/track long low-res point; revD/snap
   long); revD/track main+long imaging jumps + spiral+mid sawtooth; wiggly
   connecting lines (revF/track core & core+spiral imaging; revD/snap main
   imaging).  Decision: FIX, not accept.
2. *Data diagnosis (subagent over all 4 campaigns' displayed curves):*
   the snapshot ptsrc jumps are TAPER-ONSET CLIFFS at the natural-res
   boundary (untapered branch ends at robust +1.4..+1.8, eta~1.0; next
   winner is tapered at eta 1.4-2.6); the sawtooth is the coarse taper
   lattice (x1.52 columns); the disconnected points are interior taper
   transitions on homogeneous LONG (gap-chasing was heterogeneous-only);
   wiggles are 0.01-0.09 envelope zigzags whose worst cases are true BUMPS
   (a winner above its neighbours' chord = branch alternation).
3. *refine.py escalation ladder built* (codex gpt-5.6-sol xhigh design
   consult, adjudicated; opus implementation; Fable review + patches):
   E1 secant resolution targeting (one shot per interval, log-space, same-
   weighting evidence only; cliffs skip to E2) -> E2 staged progressive
   log-midpoint taper scans (SAME rounded taper vector at BOTH endpoint
   robusts — E0 verified singleton probes are INVISIBLE to the envelope,
   so probes must complete segments/cells; classify from measured rows:
   confirmed discontinuity / high-penalty / under-sampled) -> E3 gap
   chasing for ALL subarrays (homogeneous via E2; untapered-robust
   defects fall back to the fixed menu) -> E4 bump regions (eta-scaled
   trigger, top-2/curve, <=25% budget).  Shared sample_from_row now
   enforces the refine==report filter contract structurally.  New flags:
   --scan-points/--bump-min (+ NGVLA_REFINE_SCAN_POINTS passthrough);
   refine_parallel --budget forwarding bug fixed.  Dry-run on real
   revD/snapshot data: cliff scans at both bracket robusts with sub-0.15
   mas tapers, disconnected-LONG scans — exactly the intended probes.
4. *Display-only curve smoothing* (bmason: "more reliably smooth
   connecting interpolations"): make_report smooth_curve — segment at
   drawn gaps (1.055) and real steps (>0.20), RDP knots + forced material
   extrema (>0.05), pure-numpy PCHIP, iterative knot insertion to
   max|smooth-raw|<=0.03 and optimistic<=0.02, raw fallback; payload
   ships parallel imaging_smooth/pointsource_smooth arrays; the JS draws
   them for the LINE only (markers/tooltips/gap-breaks stay raw).  Raw
   curves untouched for refine and sa_select.  Real-build deviations:
   worst 0.028/0.020 over ~70 curves.
5. *P1 axis-cut capture BUILT* (measure.psf_axis_cuts + capture_profile
   beam/cuts fields, CASA-free tests) and *P2 anchor backfill BUILT*
   (backfill_psf.py + sbatch: re-images displayed-curve anchors lacking
   cut-bearing profile lines with the EXACT recorded convention via the
   new single-source sweep.tclean_kwargs; results CSVs byte-identical by
   construction + AST test; resumable).  Scale note: revF/track alone has
   ~949 anchors to image (predates profile capture) — node-days, 47 h
   walltime + resubmits.
6. *Codex guard review (xhigh, full diff): 5 blockers, 4 should-fix, 1
   nit.*  Accepted and fixed: axis-cut SIGN bug (negative RA increment
   reflects the cut line — real geometry error), _classify_scan bypassing
   sample_from_row, backfill success-on-fallback + stale-product reuse,
   E2 pair atomicity at budget edges, point_key -0.00 canonicalization,
   smoother hard-bound final guard, unused hysteresis claim removed, zero
   validation.  REJECTED with rationale: "backfill must cover all skirt
   setpoints" — the s0=0.10+ptsrc+natural scope is bmason's approved P2
   spec AND make_report strips env_keys for non-default setpoints, so the
   report cannot reference them (coupling comment added).
7. *Wave plan* (docs/ops/RUN_CAMPAIGNS.md "21 Jul wave"): revD/track CANARY
   (budget 240, rounds 12) + chained backfill --array=2; inspect
   escalation logs; then revF/snapshot, revD/snapshot, revF/track (200,
   12) serialized vs queue headroom, each + its backfill; final combined
   report rebuild.  Genuine snapshot cliffs will come back CLASSIFIED
   (physics), not smoothed away — expectation to set with bmason.

**SESSION DELTA (21 Jul 2026, part 3, Fable — wave launched; cap question
resolved; adaptive-sampler direction approved + spec).**
1. *Wave launched (canary stage).*  revD/track: prep 3333952 → sweep
   3333953[0-3] → collect 3333954 → backfill 3333958[2], all PENDING at
   hand-off.  Remaining three campaigns + backfills launch after canary
   inspection — docs/plans/NEXT_AGENT.md item 1-2, docs/ops/RUN_CAMPAIGNS.md "21 Jul wave".
   The 09d6d7e milestone commit carries the whole code upgrade (177 green).
2. *Beam-cap question (bmason): resolved as a memo misreading.*  The cap
   binds only the COARSE end; reference = coarsest component (mid+long →
   mid 2.96 mas; spiral+mid+long → spiral+mid 11.1; main+long → main 21.2;
   *+core-outer → 491; main → core 710); measured ranges relay with ~2x
   seam overlap (mid+long 0.51–2.82 mas hands to mid 2.03–54.6, etc.).
   bmason's proposals were both stricter than or equal to what exists;
   memo wording made unambiguous + recompiled (commit 07a144e).  Logged
   nuance: a min-integration-time ranking could in principle want
   beyond-cap mixture offerings (marginal sensitivity edge over the
   standalone subarray); a one-mixture 2x-cap-extension diagnostic
   (mid+long) is the cheap v2 experiment if ever wanted.
3. *Adaptive sampling (bmason proposal → codex xhigh consult → approved):*
   replace regular-lattice+polish with a goal-oriented quadtree/AMR
   sampler — tolerance-scaled hierarchical-residual loss (tau = ln1.05
   res / 0.1 eta / 0.02 skirt ABSOLUTE per bmason), 2-sigma noise
   deadband, exploration floor, envelope/skirt-band goal weighting,
   feature state machine {smooth, step, ridge, noise} with steps scored
   by INPUT-LOCATION bracket (localize cliffs, cut annotations, never
   interpolate across).  Rails demoted to seed-boundary (interior seeds
   mandatory — imaging winners are interior); triangular/scattered mesh
   REJECTED as architecture unless a replay shows ≥30% additional saving
   at p90 (Delaunay simplices across cliffs manufacture nonexistent
   resolutions).  Full spec: `docs/features/MFS2_ADAPTIVE_SAMPLER_SPEC.md` (supersedes
   MFS scope decision 4; seed ≈56 pts, budget plan 80/map, V1 replay
   gate).  Codex spec-review launched at session end — may need re-run
   (NEXT_AGENT).  bmason's standing bet: the in-flight wave (new
   escalation, not old polishing) may still not fill the holes — if maps
   remain under-converged they become the sampler's retrofit-mode pilot.

**SESSION DELTA (21 Jul 2026, part 4, Fable — adaptive sampler BUILT +
retrofit staged; grid MFS dropped).**
1. *bmason directives:* no grid-style MFS (adaptive from day one); MFS
   initially Ka band only (27±6.75 GHz), nchan an explicit parameter
   bmason sets later; adaptive retrofit ORDERED on all four existing
   campaigns; surrogate framing confirmed (the bilinear cell IS the local
   surrogate; residual-driven refinement everywhere, not just at branch
   points).  bmason's reframing (f: (t,r)->(theta,s,eta); per-theta 1-D
   contour searches; Pareto per theta) adopted — spec v2 carries it.
2. *Spec v2 (commit 250f85e):* executable build contract; all 15 codex
   findings resolved; constants pinned; budget arithmetic honest (fresh
   seed 56, plan 110/audit 140; retrofit plan 40/audit 80 NEW evals).
3. *Sampler core BUILT (commit 8242d08):* curvegen/adaptive.py + 44 tests
   (221 green) — quadtree over the point table, certification retirement,
   feature classification with cut brackets, wave planner, --plan-only
   CLI.  Key validation: revD/snap main+long "cliff" correctly certified
   smooth IN INPUT SPACE (eta climbs continuously while res stalls; the
   res step is 2.3% < the 5% tolerance) — the displayed jump is the
   honest image of a smooth surface; nothing to sample.  Its 16-eval wave
   targets the genuinely under-resolved 4.6-8.2 mas region instead.
4. *Certification pass over all 46 maps:* first wave 1508 evals total
   (F/track 537, F/snap 391, D/track 342-stale-canary, D/snap 238); all
   retrofit-auto, no cap violations; features match every documented
   defect; ONE NEW candidate: revD/snap long second step ~2.6 mas (E_T
   up to 14) + unresolved 0.34-0.49 mas cluster — retrofit will probe.
5. *Measuring driver BUILT (commit 0be5f8c):* wave loop (mode pinned
   across rebuilds; per-process budget window — documented limitation) +
   adaptive_retrofit.sbatch (array 0-3, collect+report+export tail).
   225 tests green.  Dev incident: a placeholder test briefly ran real
   tclean and appended 3 rows to results/core.csv — caught, reverted
   byte-identical, scratch cleaned, test monkeypatched.
6. *Sequencing:* escalation campaigns 2-4 SUPERSEDED by the retrofit
   chain (RUN_CAMPAIGNS "Adaptive retrofit wave"): canary collect ->
   scancel queued backfill 3333958 -> retrofit array 0-3 -> per-task
   backfill chain -> combined report.  Canary early results: spiral+mid
   sawtooth FIXED (1.16->0.18 imaging), mid+long 0.10/0.06 with honest
   classifications.  PHASE 3 (after retrofit wave drains; live-code
   hazard): 2c envelope leaf-cell enumerator + cuts, 2a Ka band axis
   (then Ka MFS wave once bmason supplies nchan).

**SESSION DELTA (17 Aug 2026, Fable — July wave harvested; NEW SCOPE =
docs/plans/WRAPUP.md; live plan = docs/plans/RELEASE_PLAN.md).**
1. *The 21-24 Jul chain COMPLETED unattended* (recovered from sacct + the
   logs bmason archived to /work2/.../oldNgvlaLogs/ on 13 Aug): canary
   sweep/collect (3333953/3333954), adaptive retrofit array 0-3 (3335064),
   all four PSF backfills (3335065-68) — every job exit 0.  Each retrofit
   task's collect tail auto-rebuilt the reports (23 Jul); the queued
   backfill 3333958 was cancelled per plan.  No compute artifacts exist
   after 24 Jul.
2. *Retrofit QA (from logs):* all steps everywhere came back "classified:
   sampled resolution discontinuity" (incl. the flagged revD/snapshot long
   ~2.6 mas candidate — genuine physics).  Snapshot maps mostly CONVERGED
   ("no proposals"); nearly every revF/track and revD/track map stopped at
   the 80-eval AUDIT CAP = wave 1 of ~2-3.  bmason decision (17 Aug): one
   more retrofit wave, tracks only (combos 0 and 2), then reassess.
3. *Harvest (this commit):* 6590 pure row-insertions across 50 CSVs
   (results-*/ + routed sa_select curve tables; headers unchanged), 225
   tests green, combined report rebuilt post-backfill (the run-sheet's
   final step, previously pending).  PSF axis-cut payloads exist for all
   four campaigns (reports/psf/, 23-24 Jul).
4. *NEW SCOPE (bmason, docs/plans/WRAPUP.md 17 Aug — supersedes this file where in
   conflict):* release the calculator web + python prototypes for
   revF/track (ptsrc+imaging), revD/track (ptsrc only), revC/track (ptsrc
   only, NEW campaign).  Snapshots NOT released.  Plan of record:
   `docs/plans/RELEASE_PLAN.md` (T0 harvest ✓ / T1 retrofit wave 2 / T2 revC campaign
   / T3 release page / T4 calculator surface / T5 MStroh formats /
   T6 docs+memo).  bmason launches all Slurm jobs himself now — agents
   prepare command lines only.

**SESSION DELTA (18 Aug 2026, Fable — 17-Aug release wave harvested).**
1. *All 11 jobs of the 17-Aug wave COMPLETED, exit 0* (bmason launched
   17 Aug pm): retrofit wave 2 tracks 3415615_{0,2} + backfills
   3415617_0/3415618_2, and the FIRST revC/track campaign chain — prep
   3415634 → sweep 3415635_0-3 → collect 3415636.
2. *Retrofit wave-2 QA (from logs):* zero failed evals.  Convergence:
   revF/track 6 of 14 maps "no proposals", 8 still at the 80-eval audit
   cap; revD/track 2 of 9 converged, 7 at the cap.  Every wave-2 step
   feature again classified "sampled resolution discontinuity"; ridges
   "locally supported high-penalty interval" — consistent with wave 1
   (physics, not under-sampling).  Both backfills exit 0 = all envelope
   anchors cut-bearing.  Wave 3 is bmason's call (RELEASE_PLAN decision 1
   said reassess after wave 2).
3. *revC/track campaign DONE end-to-end:* 9 subarrays, 2091 result rows
   (results-revC_track/), routed curves (sa_select/data/
   revc_track_curves.csv, 1935 rows) + 3 beam caps filled into
   subarrays_revc.csv by prep.  Residual worst in-band steps: long
   0.74/0.75 both curves and main+long imaging 0.78 / ptsrc 0.30 — all
   refine-budget hits (+60 pts each); every other subarray ≤ 0.22.
4. *revC PSF backfill NOT needed:* `backfill_psf.py --dry-run` audit =
   586/586 anchors already cut-bearing (fresh campaigns capture axis
   cuts natively, feature P1).  The run-sheet `--array=4` line is
   superseded; reports/psf/revC_track/ payloads (9 files) exported by
   collect.
5. *Reports + tests:* combined internal report rebuilt (5 campaigns) and
   release page rebuilt (3 tracks; revC curves now live; revD+revC
   imaging "Omitted" markers present).  253 tests green (1 skipped;
   count grew from 225 with the T2-T5 test additions).
6. *(18 Aug pm)* PSF capture range 3 -> 10 FWHM (`measure.
   CAPTURE_RMAX_FWHM`), same sampling density (134 bins / 271 cut
   samples); cut lines record `cut_rmax_fwhm`; backfill planner treats
   short-range or unusable lines as stale, and line validity is now the
   exporter's own `parse_profile_line` (shared, so planner and exporter
   can never disagree).  Chart: per-entry range + sqrt-r x scale; null
   cut samples no longer render as fake zeros.  bmason's avg-above-cuts
   report verified GENUINE (fitted-beam bmaj overestimation on messy
   LONG cores + real angular structure), not a normalization bug —
   radius is geo-mean-normalized in all 3 curves.  The queued wave-3
   backfills (combos 0, 2) auto-refresh every anchor; revC needs a
   separate `--array=4` backfill (supersedes item 4 above).  Three
   codex review rounds (round 1 accidentally gpt-5.5; 2-3 gpt-5.6-sol),
   7 findings all fixed; 280 tests green (1 skipped).

**SESSION DELTA (19 Aug 2026, Fable — 10-FWHM report claim was premature;
wave-3 status + harvest checklist).**
1. *bmason flagged: the released report's PSF plots still stop at ~3 FWHM*
   despite the 18-Aug range change being reported done.  CONFIRMED by
   decoding the release page's embedded payloads (built 19 Aug 11:32):
   revF/track **0**/2839 cuts at 10 FWHM, revD/track 451/2852 (only the
   wave-3 retrofit's own new points), revC/track 0/1935.  Root cause: the
   3→10 change was CODE-complete (a2c1577) but the DATA refresh of
   existing anchors is the wave-3 backfill jobs, which had not run when
   the page was rebuilt — the 11:32 rebuild was premature and the "done"
   claim wrong.  The chart itself is correct (per-entry captured range,
   floor 3; `report_template.html` ~line 1573).  **Treat the current
   ngvla-curves-release.html as STALE for PSF range.**
2. *Wave-3 state (19 Aug pm):* retrofits 3418621_0/2 COMPLETED exit 0
   (collects rebuilt per-combo + combined reports and PSF exports at
   09:44 / 16:01); backfills 3418623_0 (revF) + 3418624_2 (revD) still
   RUNNING, healthy (logs show the stale-anchor refresh proceeding, e.g.
   revD 455 anchors re-imaged at 7 h elapsed).  revC (combo 4) backfill
   3421939_4 was launched later and is also RUNNING; it is required for
   the release because all 1935 revC cuts in the 11:32 page are 3-FWHM
   (the 18-Aug "not needed" verdict predates range-versioning).
3. *Harvest checklist when the backfills drain* (any session can run it):
   (a) exit codes via sacct — NONZERO = anchors still lack cuts, a
   resubmit signal, not a bug; (b) verify range coverage by counting
   `cut_rmax_fwhm: 10` vs untagged entries in `reports/psf/*/*.js`
   (untagged = old 3-FWHM); (c) rebuild combined + release reports
   (RUN_CAMPAIGNS lines); (d) re-verify the release page by decoding its
   `data-psf-id` embed blocks; (e) tests + data milestone commit.
4. *Working-agreement addition (bmason):* long-running local agent work
   (persistent monitors, big report rebuilds) belongs on a **dev node
   (idev), not a login node**.  A squeue-polling monitor started this
   session on a login node was killed on bmason's request.

**SESSION DELTA (4 Sep 2026, Fable — PSF Gaussian reference switched to the
restoring beam; range-classification/legacy-warning logic reverted).**
bmason decision: legacy ~3-FWHM captures are pre-18-Aug data left as is (no
range-classification, no legacy warnings — see `docs/archive/plans/PSF_REPORT_FIX_PLAN.md`, which
supersedes `docs/archive/plans/PSF_PLOT_FIX_HANDOFF.md` §3). ΩGaussian is now the tclean
restoring-beam volume (π·bmaj·bmin/(4 ln 2)); exporter/report/template/tests
updated; Rev F/Rev C track points nearly all have a beam, but ~1,750 Rev D
track exploratory points and most snapshot points (Rev F ~2,470/3,830, Rev D
~1,560/2,380) lack one and get no ratio ("—").

**Follow-up (4 Sep, same session):** for two-scale (composite-subarray)
PSFs the restoring beam is systematically wider than the radial profile's
half-power width (up to 1.25-1.6x, mostly at Briggs+taper points) — tclean's
`psfcutoff=0.35` fit picks up the PSF shoulder. Added
`restoring_to_halfpower_ratio` to `derive_psf_metrics`/the compact summary
(index 6) and surfaced it in the PSF inspector, chart legend/x-axis title,
and a new QA-table "beam/core" column; see docs/architecture/PSF_DIAGNOSTICS.md's "Restoring
beam versus core half-power width" section for the measured per-subarray
ratios and the confirmed default-`psfcutoff` tclean call.

**Follow-up (4 Sep, same session): nearest-PSF lookup bug fixed.**
`nearestPsfKey` picked the resolution-nearest captured lattice PSF instead of
the one nearest in (weighting, robust, taper), so an interpolated curve point
often displayed a PSF from the wrong weighting family (MAIN skirt excess
median +0.05/p90 +0.16/max +0.38). Fixed to rank by weighting family first,
then normalized robust/taper distance, resolution as tie-break only; see
docs/architecture/PSF_DIAGNOSTICS.md's "Which captured PSF the calculator shows" section and
`tests/test_psf_lookup_replay.py`.


**SESSION DELTA (5 Sep 2026, Fable orchestrator + sonnet workers — MFS
pilot imaging launcher + V1 replay harness built; V1 gate FAILS as specified).**
1. *Late-Aug mono work, recovered from logs (not previously logged):* retrofit
   waves 3436514_4/3436656_4/3436682_4 (revC/track), 3436521_2/3436668_2
   (revD/track), 3436525_0 (revF/track) all MEASURED to completion (every map
   "audit cap reached", ~80 evals/wave); their report tails failed with a
   RecursionError in `adaptive._reconstruct_leaf` (key-aliasing below the
   point_key precision), fixed 4 Sep (distinct-3x3 key-grid guard) and
   verified today: `adaptive.py main --plan-only` (revF/track) reconstructs
   363 leaves in <1 s.  revF/snapshot retrofit 3456893_1 + backfill 3456900_1
   and revD/track backfill 3470047_2 (10 anchors) completed clean.
2. *MFS-3 pilot, simulation half DONE:* job 3470012 (4 Sep 21:46) created
   core/main Band-4 snapshot MSes for nchan 27 and 54 in ~15 s each, MaxRSS
   236-327 MB (memory is a non-issue at these nchan).  MSes on $SCRATCH under
   `ms-revF_snapshot_band4_pilot-nchan0NN-equal/`; manifests in
   `curvegen/results-revF_snapshot_band4_pilot-nchan0NN-equal/` (untracked).
3. *MFS-3 imaging half — launcher BUILT (sonnet_worker, spec
   `docs/plans/mfs-imaging-pilot-spec.md`):* `curvegen/submit_mfs_imaging_pilot.sh`
   + `mfs_imaging_pilot.sbatch` (one slot: seeds -> pinned points -> points-file
   sweeps -> compare), `mfs_pilot_points.py` (10 non-seed points: natural x
   {mid, coarse} + robust {-2,-0.4,1.2} x {0, mid, coarse}, mid/coarse =
   canonical taper_list_mas indices 6 and 8 from the nchan-27 seeds, shared
   verbatim across variants so keys match), `mfs_pilot_compare.py` (per-point
   |d eta|/eta < 0.5 %, |d res|/res < 1 %, endpoint checks, p95/max, timing
   table; exit 3 on criteria fail), 21 tests.  `--sim-mode track --nchan-list 27`
   doubles as the cost benchmark (sweep auto-simulates the track MS).  NB
   band-4 `main` beam cap is blank (fill_beam_caps not yet run for band4) —
   harmless for the pilot, REQUIRED before production.
4. *MFS-2d V1 replay harness BUILT (sonnet_worker, spec
   `docs/plans/mfs-v1-replay-spec.md`):* `curvegen/replay_v1.py` (+19 tests;
   `adaptive.py` gained an optional, default-None `seed_tapers` override).
   Architecture finding: the fresh seed's 7 log-uniform tapers do NOT
   coincide with the 14-level canonical lattice, so an exact-hit replay needs
   the seed pinned to canonical[::2]+rim (retrofit's grid); with that, exact-hit
   fractions are 0.95-1.00.  **Verdict at the spec budget (audit 140): 0/10
   maps converge, all FAIL on budget exhaustion; p90 sample fraction 0.78.**
   Budget sweep (`curvegen/reports/v1_replay/sweep/`): with a fail-on-miss
   oracle convergence goes 0 -> 4 -> 6 -> 10 of 10 at budgets 140/280/560/1120,
   but at 1120 the replay has sampled 99.9 % of the legacy lattice (replay
   ceiling, not a production estimate); median regret_max_covered drops below
   0.1 at budget ~280 (0.051) and 6-7/10 maps meet it thereafter.  Persistent
   cut disagreements at every budget: ~4 false + 4 missed cuts across the suite
   (revD/track spiral+mid false; revF/track core+spiral missed) — to
   investigate.  The nearest-row fallback oracle poisons certification (plateaus
   at 3-4/10 converged) — `--on-miss fail` is the honest oracle.
5. *Consistency check:* the mono retrofits also spent 80 evals/wave for 2-5
   waves per map without converging, so the replay is telling the truth about
   the certification criterion, not about the replay.
6. Tests: 402 green (1 skipped).  Nothing committed this session; pending
   bmason review of items 3-4 and the decisions in NEXT_AGENT.

**SESSION DELTA (6 Sep 2026, Fable orchestrator + haiku scout + sonnet
worker — MFS status review; docs/worklog/ created).**
1. Verified the MFS-3 imaging pilot has still NOT been launched: checked
   for `/work2/10240/bmason72/stampede3/mfs_imaging_pilot_*.log`,
   `/scratch/10240/bmason72/ngvla_curvegen/mfs_imaging_pilot/`, and any
   `nchan_convergence_vs_*.md`/`timing_track.md` — none exist.  Only the
   simulation half (Slurm job 3470012) and the CPU-only V1 replay have run;
   `sacct` for 4-6 Sep shows just 3470012, backfill 3470047_2, and idev
   sessions.
2. Created `docs/worklog/` as a new documentation area (convention in
   `docs/worklog/README.md`) and `docs/worklog/mfs-campaigns.md` as the
   first rolling-status file for it, plus `docs/archive/worklog/README.md`
   for the eventual retirement path.  Added rows for all three to
   `docs/INDEX.md`.
3. Flagged a doc inconsistency: `docs/plans/mfs-campaigns-detail.md` still
   describes the MFS-3 convergence pilot as band 2, both modes, nchan
   16..512 with two consecutive doublings; `docs/plans/MFS_CAMPAIGN_PLAN.md`
   (authoritative, 5 Sep status) narrowed it to Band 4 snapshot, core+main,
   nchan 27 vs 54.  Added a one-line superseded pointer under the detail
   doc's title rather than rewriting its body.
4. Re-confirmed tests green: `casapy -m unittest discover -s tests -t .` ->
   402 tests, OK (skipped=1).
5. Confirmed nothing MFS-related is committed (git status/diff against last
   commit `c264af4`, 5 Sep doc cleanup only).  This session made
   documentation-only edits and did not commit.
6. bmason decided D1 (production nchan for Band 4 = 32, 0.5 GHz channels
   across the 13.5 GHz Band-4 window rounded up to the next power of two;
   the 27-vs-54 pilot becomes a confirmation run, not a gate) and D2 (Band 4
   only is in scope for the MFS campaigns now; other bands are obtained by
   scaling the Band-4 curves with wavelength, an approximation, largest
   expected effect at the fine, negative-robust end; a Band-2 vs scaled-
   Band-4 check on core and main is queued).  Pinned `nchan` to 32 on both
   band4 rows in `sa_select/data/config_registry.csv`; ran the full test
   suite afterward (`casapy -m unittest discover -s tests -t .` -> 402
   tests, OK (skipped=1)), updating one test
   (`test_mfs_config_requires_explicit_nchan`) that had asserted the old
   blank-registry failure.
7. Doc files touched recording D1/D2: `docs/plans/MFS_CAMPAIGN_PLAN.md`,
   `docs/plans/mfs-campaigns-detail.md`, `docs/ops/RUN_CAMPAIGNS.md`,
   `docs/plans/NEXT_AGENT.md`, `docs/worklog/mfs-campaigns.md`, and this
   file.
8. Replay anomaly investigation done (`curvegen/reports/v1_replay/INVESTIGATION.md`):
   sample_fraction>1 was a numerator/denominator status mismatch (fixed in
   `replay_v1.py` + regression test); converged-but-FAIL maps are a
   seed-vs-historical-lattice coverage artifact; false/missed cuts are
   sparse-subset aliasing; the one traced track map genuinely needs ~560
   evals.  No sampler defect found; relaxing to an accuracy gate at 280 is
   NOT supported.  Recommended next: a continuous surrogate oracle for the
   replay.  Also fixed `config.py` so pilot variants may override the pinned
   registry nchan (27-vs-54 confirmation pilot preflights again).
9. bmason decided D3 and D4. D3: the adaptive quadtree sampler is set aside
   for MFS v1 (parked, not abandoned). This parks MFS-2b/2c/2d/2e, the V1
   replay gate, and MFS-4 (the PyLauncher wave runner). Reasoning: the
   sampler was designed on the assumption that a full MFS grid is
   unaffordable, and that assumption is being dropped for snapshot mode;
   also, multi-channel uv coverage very likely changes how eta and
   resolution respond to robust relative to the mono simulations the
   sampler was tuned and tested on, so a mono-based certification tests the
   wrong surface. D4: no MFS track campaign and no further timing benchmark
   now. Band-4 snapshot mode only. The production path is the proven mono
   pipeline on the full fixed grid (11 robust values by the canonical 14
   tapers plus the natural row), revF, 7 subarrays (core-inner, core,
   spiral, mid, core+spiral, spiral+mid, main), nchan 32, equal
   per-channel noise. Snapshot timing at 32 channels is judged fine without
   a benchmark.
10. What was learned (from `curvegen/reports/v1_replay/INVESTIGATION.md`):
    the replay's failures were a metric bug (fixed), a coverage artifact of
    the fresh seed versus the historical multi-campaign taper lattices, and
    sparse-subset aliasing; the one traced track map genuinely needed about
    560 evaluations; no sampler defect was found. If the sampler is revived
    later, the cheap snapshot MFS full grids are the right oracle for
    certifying it (real multi-channel surfaces, grid built to coincide with
    its bisection points). The 27-vs-54 snapshot confirmation pilot stays
    available (MSes exist; launcher preflights cleanly) as an optional
    check that 0.5 GHz channels are converged; it is not a gate.
11. Open questions for bmason: point-source curves only or both curves from
    the full grid; keep the 7-subarray set; whether Band-4 results enter
    the combined release page and calculator or stay as per-combo CSVs and
    reports for now; when to make the milestone commit of the MFS code.
12. Next step (agent side): scout and spec what the standard campaign chain
    (prep, sweep, refine, fill_grid, collect, report) needs to run for
    revF/snapshot/band4 at nchan 32, including removing adaptive-only
    guards that reject full-grid MFS, and fill_beam_caps for band4 (main's
    cap is blank). A scout is doing that inventory now; its findings will
    be added later.
13. Evening: milestone commit `b52504d`.  bmason decisions D5 to D8 (both
    curves; 7 subarrays; MFS snapshot as its own report view, no "band 4" in
    user-facing text; chain = prep, sweep, refine, collect; denser robust
    sampling for MFS).  Spec written: `docs/plans/mfs-snapshot-production-spec.md`
    (robust_step registry column, 0.2 for band4; curve_types both; envelope
    gap from data; report label/note; run-sheet launch section; tests).
    Sonnet worker dispatched to build it; see NEXT_AGENT "RESUME HERE" if the
    session ended before it reported.

**SESSION DELTA (7 Sep 2026, Fable — MFS snapshot production chain landed).**
The overnight worker build of `docs/plans/mfs-snapshot-production-spec.md`
(C1-C5) was reviewed and completed after the reservation reset: registry
`robust_step` (0.2 for band4, mono unchanged), `curve_types both`, per-table
envelope gap limit, "Rev F — MFS snapshot" report view with a registry-built
note, `submit_campaign.sh --band/--noise-policy`, band-suffixed per-combo
report file, run-sheet launch section.  414 tests green (1 skipped).  Details
in `docs/worklog/mfs-campaigns.md` (2026-09-07 entry).  bmason launches.
Follow-up (7 Sep): launcher interface changed to `--mode mfs|1chan` (`--band`
rejected; band resolved from the registry by `campaign_tasks.py mfs_band`);
astra_seer tclean consult (nterms=1/hogbom at niter=0 correct;
perchanweightdensity irrelevant for mfs; MT-MFS tt0 penalty ~0 for symmetric
equal-noise channels; FOV dependence of Briggs weighting at coarse tapers is
an open decision).  419 tests green.

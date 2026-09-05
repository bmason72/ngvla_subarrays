# Campaign run sheet (copy-paste, one command per step)

## 4 Sep MFS snapshot simulation pilot — READY TO LAUNCH (production is not)

The Band-4 snapshot simulator path is ready for the safe first half of the
nchan/RSS pilot. It creates **only** core and main measurement sets, does not
run tclean or mutate production result tables, and consumes one Slurm queue
slot. Each nchan has an isolated manifest and scratch MS directory.

```bash
# 27 channels = 0.5 GHz/channel across the 13.5-GHz Band-4 window;
# 54 is one deliberately limited convergence check at 0.25 GHz/channel.
bash /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/submit_mfs_snapshot_sim_pilot.sh

# Monitor the umbrella job and inspect the per-run resource logs.
squeue -u bmason72 -o "%.18i %.22j %.10T %.12M %.6D %R"
grep -E "created |reusing existing|Maximum resident set size|Elapsed \(wall clock\)" \
  /work2/10240/bmason72/stampede3/mfs_snapshot_sim_<JOBID>_*.log

```

Success means every per-run log reports `created` or validated `reusing
existing`, the umbrella job exits 0, snapshot validation finds exactly one
integration, and MaxRSS leaves comfortable node headroom. Re-running either
command is safe and revalidates/reuses its own MS.

The two nchan values test whether the derived beam/skirt/eta quantities have
already converged at the proposed 0.5-GHz spacing while also measuring memory;
there is no plan to continue to 128--512 unless 27 versus 54 fails that test.

This is **not** the production MFS snapshot campaign. Do not use
`submit_campaign.sh` for MFS: its full-grid/fill path violates the adaptive
MFS contract. Before production, finish MFS-2d/V1 replay, run the tclean
convergence and noise-policy pilots, record bmason's nchan/noise decision, and
land the MFS-4 fresh adaptive wave runner. The current registry therefore
keeps production `nchan` blank.

## 4 Sep PSF audit — report rebuilt; legacy coverage remains

The release report was regenerated on 4 Sep and embeds current payload files.
Plots ending near r=3 are genuine pre-upgrade compact profiles captured before
the 18 Aug `CAPTURE_RMAX_FWHM` change; bmason's decision (4 Sep) is to leave
them as is — the chart already shows them honestly — rather than add
range-classification or legacy-warning logic to the report.

The former fixed-intercept “robust core Gaussian” is removed: it was visibly
and quantitatively poor for multi-scale composite arrays. ΩGaussian is now the
**tclean restoring-beam volume** (π·bmaj·bmin/(4 ln 2)), a genuine 2-D fit CASA
already produced during imaging, not a fit to the radial profile. Essentially
all Rev F and Rev C track points (the release tracks) carry a restoring beam;
about 1,750 Rev D track exploratory points and most snapshot-campaign points
(Rev F ~2,470 of 3,830; Rev D ~1,560 of 2,380) lack one and get no ΩPSF/ΩG or
confusion ratio; the report says so ("—", "no restoring beam recorded").

For a future reduced final-point campaign, retain a 2-D PSF (compressed FITS or
an equivalent float array) for every curve anchor, plus the derived radial and
axis profiles, weighted uv-radius histogram/moments, effective frequency,
weight/noise totals, MS/config hash, imaging parameters, and CASA version.
Full 2-D products need only be retained for this small final set; exploratory
lattice points can continue using compact profiles. bmason's intent: this
follow-on campaign samples a subspace of the grid along the optimum curves
(not the full exploratory lattice) and retains PSFs, and possibly MSs, for
that reduced set.

**Restoring beam vs. core half-power width (4 Sep, bmason decision).** For
two-scale PSFs — composite subarrays such as core+spiral, main, main+long,
spiral+mid+long, mostly at Briggs+taper points — the tclean restoring beam is
systematically wider than the radial profile's half-power width, by up to
1.25-1.6x. Mechanism: tclean's beam fit uses every pixel above
`psfcutoff=0.35` in a 41x41 box, and a two-scale PSF's shoulder stays above
0.35 out to ~0.75 FWHM, so shoulder pixels broaden the Gaussian fit. The
tclean call in `curvegen/sweep.py` uses CASA's default `psfcutoff` (confirmed
by `grep -rn "tclean(" curvegen/*.py`: the sole call site, `sweep.py`'s
`run_tclean`, passes no `psfcutoff` kwarg). Measured Rev F track numbers:
single-scale arrays (core, core_inner, mid, spiral) have a median ratio
&approx;1.00 and max 1.07, none above 1.10; core_spiral has 25 of 276 points
above 1.10 (max 1.29); main 70/403 (max 1.42); long 128/354 (max 1.57);
spiral_mid_long 115/315 (max 1.59); main_long 99/359 (max 1.50).

The report now exposes this rather than hiding it: `derive_psf_metrics` adds
`restoring_to_halfpower_ratio` (restoring FWHM over measured half-power FWHM)
alongside the existing beam metrics, `build_psf_metric_summary`'s compact row
carries it as index 6, and the PSF inspector, its chart legend/x-axis title,
and the QA table's new "beam/core" column all surface it. Because `res_geo`
throughout the pipeline is the restoring beam (never the core half-power
width), the reported resolution at an affected point is coarser than the true
core — readers should treat res_geo as the restoring-beam figure it always
was. The confusion estimate is insensitive to which width is used as the
reference: Condon's γ=3 scaling has the source-count model going as θ and the
correction as 1/θ, so they cancel to first order.

## 17 Aug release wave — COMPLETE (harvested 18 Aug; see PLAN.md 18-Aug delta)

Outcome (all 11 jobs exit 0): retrofit wave 2 tracks (3415615_{0,2}) +
backfills (3415617_0, 3415618_2); revC/track campaign end-to-end (prep
3415634 → sweep 3415635_0-3 → collect 3415636).  The revC `--array=4`
PSF backfill from the original sheet was NEVER NEEDED — `backfill_psf.py
--dry-run` shows every revC anchor already cut-bearing (fresh campaigns
capture axis cuts natively).  Combined + release reports rebuilt 18 Aug;
data committed.

Wave-2 convergence: revF/track 6/14 maps "no proposals", revD/track 2/9;
the rest stopped at the 80-eval audit cap.  All step features again
classified genuine.  revC residual budget-limited steps: long 0.74 (both
curves), main+long imaging 0.78 / ptsrc 0.30; all else ≤ 0.22.

## Retrofit wave 3 — LAUNCHED 18 Aug (retrofit 3418621_{0,2}; backfills 3418623_0, 3418624_2)

bmason launched the tracks-only variant (combos 0 and 2; no revC retrofit).

**Status 19 Aug pm:** retrofits 3418621_0/2 COMPLETED exit 0 (their collects
rebuilt per-combo + combined reports and PSF exports 09:44 / 16:01); all
three range-refresh backfills are now launched and RUNNING: 3418623_0 revF,
3418624_2 revD, and 3421939_4 revC.  **The 19 Aug 11:32 release-page rebuild
was PREMATURE** — it embeds mostly 3-FWHM cuts (revF 0/2839 at 10 FWHM,
revD 451/2852, revC 0/1935; verified by decoding its payloads) because the
backfills carry the anchor refresh.  Rebuild both reports again AFTER the
three backfills drain; harvest checklist in the PLAN.md 19-Aug delta.

**PSF range upgrade rides along (18 Aug pm):** capture now goes to 10 FWHM
(was 3; `measure.CAPTURE_RMAX_FWHM`) and backfill treats shorter-range cuts
as stale.  So the two QUEUED backfills refresh EVERY displayed-curve anchor
for combos 0 and 2 — the scale of the original full backfill, well inside
the 47 h walltime, resumable as always.  revC (combo 4) was launched later
as 3421939_4 because its anchors are stale too.  The launch command was:

```
sbatch --array=4 /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/backfill_psf.sbatch
```

Snapshots (combos 1, 3) stay at 3 FWHM — not in the release; the report
renders each point at its own captured range.  If the retrofit started
before the range change was committed, its early captures are 3-FWHM;
the dependent backfill then refreshes them (self-healing, no action).

```
# After it drains: rebuild the internal + release reports
cd /home1/10240/bmason72/Code/ngvla_subarrays/curvegen && \
/work2/10240/bmason72/stampede3/casaenv/bin/casapy make_report.py --combined reports/ngvla-curves.html && \
/work2/10240/bmason72/stampede3/casaenv/bin/casapy make_report.py --combined --release
```

QA: retrofit logs per "Adaptive retrofit wave" below.  Job logs land in
/work2/10240/bmason72/stampede3/ (the July wave's were archived to
oldNgvlaLogs/).  Combo indices: 0=revF/track, 1=revF/snapshot, 2=revD/track,
3=revD/snapshot, 4=revC/track (the sbatch COMBOS arrays; appended, never
reordered).

Run everything below **from a login node** (compute nodes cannot `sbatch`).
All commands use absolute paths, so your current directory does not matter.
`$USER` = bmason72; job logs land in `/work2/10240/bmason72/stampede3/`
(prep_<id>.log, sweep_<id>_<task>.log, collect_<id>.log, regen_ms_<id>_<task>.log).

The campaign pipeline is 3 chained stages: **prep** (cfgs + seeds + beam caps —
the QA gate) → **sweep** (job array; sweep_parallel → fill_grid → refine) →
**collect** (curves CSV + per-combo report + the combined all-campaigns
report).  Each stage waits for the previous via `afterok`.  Everything is
resumable: re-running a campaign continues where it left off.

## State (15 Jul 2026)

- **All four base campaigns are DONE** (13–14 Jul): revF/track (mature),
  revF/snapshot, revD/track, revD/snapshot.  Curves + reports exist for all.
- **Curve-defect diagnosis complete** (PLAN.md, 15 Jul): the visible
  jumps/staircases are refinement-budget starvation (worse: the old refine
  chased invisible eta>5 fringe jumps and never chased point-source-curve
  jumps — both fixed in `refine.py`); one corrupt snapshot LONG row was
  stripped; snapshot curves *legitimately* start at ≈ the natural beam for
  sparse single-component subarrays (single-integration uv occupancy —
  physics, not missing data; see the snapshot note in the report).
- **MS stores moved to $WORK** (`$WORK/ngvla_curvegen/ms*`): `$SCRATCH` is
  purged periodically; only the disposable tclean work dirs stay on scratch.
  `curvegen/ms` symlink + `NGVLA_MS_BASE` route everything automatically.

## State after the 15 Jul evening polish attempt (diagnosed + fixed 16 Jul)

The four polish campaigns were submitted 15 Jul ~18:20.  Outcome:

- **Every refine stage that had real work CORE-DUMPED** with
  `casacore FiledesIO ... Disk quota exceeded`: Slurm jobs inherit the cwd of
  the SUBMISSION directory (the repo, on $HOME, 14 GB quota), and plain
  `refine.py` — unlike sweep_parallel/fill_grid — has no scratch-cwd
  management, so its big tcleans dumped multi-GB TempLattice images into the
  repo until home filled.  The earlier campaigns dodged this only by
  submission-directory luck.  **FIXED**: all three campaign sbatches now pin
  their cwd to `$NGVLA_SCRATCH/run_<jobid>[_<task>]`.  The ~9 GB of
  TempLattice/casa-log debris in the repo has been deleted.
- **revF/track prep FAILED instantly** (job 3314391): `fill_beam_caps.py`
  hard-exited on the default combo instead of no-op'ing (first time
  revF/track ever went through submit_campaign.sh).  **FIXED** (successful
  no-op, like `--verify`).  Its dependent sweep/collect jobs can never run.
- **revD/track's collect job was never created** (prep 3314261 + sweep
  3314262 exist; no collect) — most likely the third sbatch submission
  failed silently; its curves CSV is stale.  A clean resubmit supersedes it.
- **Partial gains landed anyway** (refine points measured before the crash
  are recorded; everything is resumable): both snapshot campaigns collected
  and refreshed their CSVs + reports (e.g. revD/snapshot `long` +54 points,
  worst step 1.02 → 0.72).

### 16 Jul relaunch — OUTCOME (three campaigns DONE)

bmason relaunched revF/snapshot, revD/snapshot, revD/track the morning of
16 Jul; all sweeps COMPLETED cleanly with the cwd fix (no crashes, no
budget exhaustion except revD/track `long`).  revD/track's collect job was
again lost to the queue limit (see "If a submit fails") — its collect +
report + PSF export were run locally the same day, so **all three
campaigns' curve CSVs, reports, and PSF payloads are current.**

Post-polish residual steps (from the refine logs; everything else ≤ 0.25
on BOTH curves — e.g. revF/snapshot main+long imaging 1.42 → 0.24,
revD/track mid+long spike and main ptsrc: FIXED):

| campaign | survivors (worst in-band Δη) | why it survived |
|---|---|---|
| revF snapshot | main+long ptsrc 0.48, l+m+s+c-o ptsrc 0.50, main ptsrc 0.45 | candidates exhausted (not budget) |
| revD snapshot | main+long ptsrc 1.58, long 0.72 both curves, main ptsrc 0.41 | candidates exhausted; long +0 points |
| revD track | long imaging 1.21 (**budget hit** — a resubmit continues), main+long imaging 1.09, spiral+mid imaging 0.36, main+long ptsrc 0.33 | long: budget; others: candidates exhausted |
| revF track (16 Jul pm) | main+long ptsrc 0.38 (+0 pts), l+m+s+c-o ptsrc 0.49→0.42 (+5 pts) | candidates exhausted; ALL imaging ≤0.19 |

"Candidates exhausted" = refine measured every bracketing probe its
generator can propose and the jump stayed — per the polish assumption
(ETA_JUMPS.md), that is now real evidence of physics/branch transitions
(the snapshot natural-end eta cliffs especially), not under-sampling.
Next levers, bmason's call: (a) resubmit revD/track polish (helps `long`
only), (b) the logged codex advisories — dense 1-D taper scans through the
surviving intervals and/or bisection-style direct resolution targeting in
refine, (c) accept + document.

### 16 Jul evening: revF/track polish — DONE (POLISH complete, 4 of 4)

bmason launched it 16 Jul 16:19 (right after commit c643dca, so the
committed docs briefly said "still to launch").  Full chain completed
16:39 — prep 3318072 → sweep 3318073_0–5 → collect 3318074 — the first
revF/track chain to run end-to-end through `submit_campaign.sh`.  Collect
rebuilt the per-combo + combined reports and PSF payloads the same minute,
so reports are CURRENT; survivors added to the table above.  The only
follow-up launch on offer is the optional revD/track resubmit (§1 below,
continues its budget-limited `long` imaging refine; all else no-ops) —
part of bmason's survivors decision.

## 21 Jul wave — escalated refine + PSF anchor backfill (launch sheet)

The 21 Jul code upgrade (PLAN.md 21-Jul part-2 delta) gives refine.py an
escalation ladder (E1 secant / E2 staged taper scans / E3 homogeneous gaps /
E4 bumps) that targets every defect bmason flagged on 21 Jul, plus P1 axis-cut
capture (new refine points carry PSF cuts natively) and the P2 anchor-backfill
job.  Wave order (queue limit: verify all three ids per campaign):

```
# 1. CANARY first, alone (most defects; biggest budget):
bash /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/submit_campaign.sh revD track --time 47:00:00 --refine-budget 240 --refine-rounds 12
#    ... then chain its backfill (combo index 2) on the collect job id:
sbatch --array=2 --dependency=afterok:<revD_track_COLLECT_id> /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/backfill_psf.sbatch

# 2. INSPECT the canary sweep logs before the rest:
grep -E "refined|budget|worst|escalation|E2 " /work2/10240/bmason72/stampede3/sweep_<ID>_*.log
#    sane = E2 plans with small-taper scans at both bracket robusts, terminal
#    "sampled resolution discontinuity"/"high-penalty" classifications, no
#    runaway budget.
# 2'. SUPERSEDED (21 Jul evening, bmason): the remaining three escalation
#     campaigns are replaced by the ADAPTIVE RETROFIT below.
```

### Adaptive retrofit wave (REPLACES escalation campaigns 2-4; 21 Jul pm)

The adaptive sampler (curvegen/adaptive.py, spec MFS2_ADAPTIVE_SAMPLER_SPEC.md)
runs certification-first on every existing map and measures only what your
tolerances still need.  Certification pass (21 Jul): first wave = 1508 evals
across all 46 maps (revF/track 537, revF/snapshot 391, revD/track 342-stale,
revD/snapshot 238); full retrofit ~2-3 shrinking waves, audit-capped at
80 new evals/map.  After the CANARY COLLECT (3333954) completes:

```
scancel 3333958        # requeue revD/track PSF backfill BEHIND the retrofit
RID=$(sbatch --parsable --array=0-3 /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/adaptive_retrofit.sbatch | tail -1)
# PSF backfills per combo, each after ITS retrofit task (retrofit moves anchors):
for K in 0 1 2 3; do sbatch --array=$K --dependency=afterok:${RID}_$K /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/backfill_psf.sbatch; done
```

Each retrofit task ends with its own collect + per-combo report + combined
report + PSF export (non-blocking), so reports refresh automatically; the
backfills then add anchor cuts.  QA per task:
`grep -E "wave |adaptive:|step|ridge" /work2/10240/bmason72/stampede3/retrofit_*.log`
(healthy = shrinking waves, "stopped: no proposals (converged/classified)").
Known limitation: the per-map budget window resets across a kill+resubmit
(measurements stay perfectly resumable; worst case a resumed task re-spends
up to one audit cap).  NB a NEW candidate defect to watch: revD/snapshot
`long` shows an undocumented second step at ~2.6 mas (certification pass) —
the retrofit will probe it; check its classification in the logs.

```
# after ALL backfills: rebuild the combined report once more
cd /home1/10240/bmason72/Code/ngvla_subarrays/curvegen && \
/work2/10240/bmason72/stampede3/casaenv/bin/casapy make_report.py --combined reports/ngvla-curves.html
```

Notes: backfill combo indices follow config_registry order (0=revF/track,
1=revF/snapshot, 2=revD/track, 3=revD/snapshot); each backfill task re-images
the curve ANCHORS lacking cut-bearing profiles (revF/track: ~949, node-days —
resumable, resubmit if the 47 h ceiling hits) and then re-exports that combo's
PSF payloads.  Campaign collects rebuild per-combo + combined reports as
always — the new display-smoothing (bounded, display-only) rides along
automatically.  Expected outcomes: fillable defects (sawtooth, coarse
columns, most gaps) get filled; genuine snapshot taper-onset cliffs get
CLASSIFIED ("sampled resolution discontinuity" in the logs) — those are
physics, and the honest rendering (a sharp step, never splined over) stays.

## 1. POLISH campaigns — the follow-up refine passes (SUPERSEDED by the 21 Jul wave above)

Base grids are complete, so prep + sweep_parallel + fill_grid are fast no-ops;
each array task effectively runs only the upgraded `refine.py` (both curves,
display-trimmed samples, res-gap chasing) with a bigger budget.  Order is
arbitrary; they can run concurrently (each has its own results dirs).

```
bash /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/submit_campaign.sh revF snapshot --time 24:00:00 --refine-budget 200 --refine-rounds 8
bash /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/submit_campaign.sh revD snapshot --time 24:00:00 --refine-budget 200 --refine-rounds 8
bash /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/submit_campaign.sh revD track     --time 47:00:00 --refine-budget 200 --refine-rounds 8
bash /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/submit_campaign.sh revF track     --time 47:00:00 --refine-budget 200 --refine-rounds 8
```

The revF/track pass is last/optional but recommended: its two known
point-source steps (main+long Δη 0.38 @ 0.52 mas,
long+mid+spiral+core-outer Δη 0.49 @ 0.51 mas) were never refine targets
before the point-source-chasing fix.

Defect targets these passes should fix (from the 15 Jul census — worst
in-band adjacent Δη on the *rendered* curves):

| campaign | worst offenders (curve, Δη @ res) |
|---|---|
| revD track | main+long (imaging 1.16 @ 0.92 mas, double jump), spiral+mid (imaging 2×0.36 staircase), mid+long (imaging 0.27 spike @ 1.1 mas), main (ptsrc 0.40), long (ptsrc 0.41) |
| revF snapshot | main+long (ptsrc 1.42 @ 3.5 mas), main (ptsrc 0.45 @ 21.7 mas), long+mid+spiral+core-outer (0.65–0.71) |
| revD snapshot | main+long (1.53 @ 3.3 mas), long (0.80 + three ×1.4–2.0 res gaps), main (ptsrc 0.41) |
| revF track | main+long ptsrc 0.38, long+mid+spiral+core-outer ptsrc 0.49 |

Residual fragmentation on snapshot LONG curves after the pass is expected
(honest sparse instantaneous uv coverage) — the report now says so.

### Watch / QA-gate (same as ever)
```
squeue -u bmason72 -o "%.10i %.14j %.8T %.10M %.6D %R"
grep -E "refined|budget|worst" /work2/10240/bmason72/stampede3/sweep_<SWEEP_ID>_<task>.log
```
Success criterion per subarray: `worst in-band step` ≤ ~0.25 for BOTH
`(imaging)` and `(ptsrc)` lines, or a budget-reached line worth reading.

After the polish campaigns land, the next campaign to stage is the **PSF
anchor backfill** (PLAN.md "PSF inspector plan", task P2) — it must wait for
polish because refinement moves the envelope anchors it targets.

## 2. MS regeneration (insurance — run after any scratch purge, or never)

One array task per combo; re-simulates only MISSING MSes into
`$WORK/ngvla_curvegen` (idempotent, safe any time):

```
sbatch --array=0-3 /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/regen_ms.sbatch
```

Nothing else needs regenerating: sweep results (the expensive part) are CSVs
in the git repo; tclean work dirs are recreated per run.

## 3. Reports

- Flagship (internal): `curvegen/reports/ngvla-curves.html` — ALL campaigns
  with a campaign dropdown (top right).  PSF data lazy-loads from the
  sibling `reports/psf/` directory, which must travel with the HTML.
  Rebuild locally any time:
  ```
  cd /home1/10240/bmason72/Code/ngvla_subarrays/curvegen && \
  /work2/10240/bmason72/stampede3/casaenv/bin/casapy make_report.py --combined reports/ngvla-curves.html
  ```
- Release (public): `curvegen/reports/ngvla-curves-release.html` — the three
  track campaigns, **fully standalone** (~17 MB: all PSF payloads embedded
  gzip+base64, inflated in-browser on first use).  scp/distribute the ONE
  file; no psf/ directory needed.  Rebuild:
  ```
  /work2/10240/bmason72/stampede3/casaenv/bin/casapy make_report.py --combined --release
  ```
- Per-combo reports still build as before (`--rev/--sim-mode`); the campaign
  collect stage refreshes the internal reports automatically.  NB the
  release page is NOT rebuilt by collect — rebuild it by hand after new
  data lands.

## Handy monitoring

```
squeue -u bmason72 -o "%.10i %.14j %.8T %.10M %.6D %R"          # my queue
sacct -X -S today --format=JobID,JobName,State,Elapsed,End      # today's jobs
```

Cancel an entire campaign (all its jobs):
```
scancel -u bmason72 --name=ngvla_prep
scancel -u bmason72 --name=ngvla_sweep
scancel -u bmason72 --name=ngvla_collect
```

## Where the results land

- Sweep CSVs + PSF profiles: `curvegen/results-<rev>_<mode>/` (repo)
- Curves table (registry-routed): `sa_select/data/<rev>_<mode>_curves.csv`
- MS stores (persistent): `$WORK/ngvla_curvegen/ms*`
- tclean scratch (disposable): `$SCRATCH/ngvla_curvegen/work*`
- HTML reports: `curvegen/reports/` (per-combo + `ngvla-curves.html` combined)

## If a submit fails

- **A campaign chain missing its later stage(s)** (a prep with no sweep, or a
  sweep with no collect — seen 15 Jul revD/track and 16 Jul revF/track) →
  almost certainly the per-user queued-job limit: array elements count
  individually, so 3-4 concurrent campaigns (~20+ queued jobs) make later
  `sbatch` calls fail and `submit_campaign.sh` exits mid-chain.  Wait for the
  queue to drain and resubmit that campaign (resumable, harmless); an
  orphaned prep with no dependents just runs its cheap idempotent prep.
- "Job dependency problem" → the captured job id was malformed — run the
  failing `sbatch` alone and read what it printed (see `submit_campaign.sh`).
- Instant task deaths with a bare "SWEEP: ... FAILED" and no Python traceback →
  suspect the shell, not CASA: a bash special variable (`GROUPS`, `UID`,
  `EUID`, `BASH*`, `SHELLOPTS`) being assigned, or `set -u` hitting an unset
  var.  Reproduce the failing snippet interactively on a login node.
- A stage failed midway → just re-run the same `submit_campaign.sh` line; prep
  seeds and measured sweep points are skipped, only the missing work runs.
- History: the 12 Jul across-the-board sweep failure was the `GROUPS` bash
  special variable (fixed 13 Jul; gotcha logged in PLAN.md §13).

# Campaign run sheet (copy-paste, one command per step)

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

## 1. POLISH campaigns — the follow-up refine passes (launch these)

Base grids are complete, so prep + sweep_parallel + fill_grid are fast no-ops;
each array task effectively runs only the upgraded `refine.py` (both curves,
display-trimmed samples, res-gap chasing) with a bigger budget.  Order is
arbitrary; they can run concurrently (each has its own results dirs).

```
bash /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/submit_campaign.sh revF snapshot --time 24:00:00 --refine-budget 200 --refine-rounds 8
bash /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/submit_campaign.sh revD snapshot --time 24:00:00 --refine-budget 200 --refine-rounds 8
bash /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/submit_campaign.sh revD track     --time 48:00:00 --refine-budget 200 --refine-rounds 8
bash /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/submit_campaign.sh revF track     --time 48:00:00 --refine-budget 200 --refine-rounds 8
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

- Flagship: `curvegen/reports/ngvla-curves.html` — ALL four campaigns with a
  campaign dropdown (top right).  Rebuild locally any time:
  ```
  cd /home1/10240/bmason72/Code/ngvla_subarrays/curvegen && \
  /work2/10240/bmason72/stampede3/casaenv/bin/casapy make_report.py --combined reports/ngvla-curves.html
  ```
- Per-combo reports still build as before (`--rev/--sim-mode`); the campaign
  collect stage refreshes both automatically.

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

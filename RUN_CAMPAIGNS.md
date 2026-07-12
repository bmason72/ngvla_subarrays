# Campaign run sheet (copy-paste, one command per step)

Run everything below **from a login node** (you are on login4 — good; compute
nodes cannot `sbatch`).  All commands use absolute paths, so your current
directory does not matter.  `$USER` = bmason72; job logs land in
`/work2/10240/bmason72/stampede3/` (prep_<id>.log, sweep_<id>_<task>.log,
collect_<id>.log).

The pipeline is 3 chained stages: **prep** (build cfgs + seeds + beam caps —
the QA gate) → **sweep** (the job array) → **collect** (curves CSV + report).
Each stage waits for the previous via `afterok`, so the sweep stays PENDING
until prep succeeds — you can eyeball the prep log and cancel before the sweep
burns node-hours.  Everything is resumable: re-running a campaign continues
where it left off.

---

## 0. One-time cleanup (orphaned prep job from the failed submit)

```
scancel 3299875
```

---

## 1. Campaign A — RevF / snapshot  (run this first; validates the new mode axis)

```
bash /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/submit_campaign.sh revF snapshot --time 24:00:00
```

It prints three job ids: prep, sweep array, collect.  Note the **prep** id.

### Watch it / QA-gate it
```
squeue -u bmason72 -o "%.10i %.14j %.8T %.10M %.6D %R"
```
When prep finishes (sweep will be PENDING with reason `Dependency`), eyeball
the seed beams — replace `<PREP_ID>` with the prep job id:
```
grep -E "beam|imsize|cell|seed|FAIL" /work2/10240/bmason72/stampede3/prep_<PREP_ID>.log
```
If the seed beams / imsize look wrong, abort the rest (replace ids):
```
scancel <SWEEP_ID> <COLLECT_ID>
```

---

## 2. Campaign B — RevD / track  (after A looks good)

```
bash /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/submit_campaign.sh revD track --time 48:00:00
```
Same watch / QA-gate commands as above with this run's prep id.

---

## 3. (Optional, later) RevD / snapshot

Only if you want it after seeing A and B:
```
bash /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/submit_campaign.sh revD snapshot --time 24:00:00
```
NOTE THIS ONE IS NOT WORKING NOW SUPPORTING METADATA SEEMS TO BE NEEDED

---

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

---

## Where the results land

- Sweep CSVs + PSF profiles: `curvegen/results-<rev>_<mode>/`
- Curves table (registry-routed): `sa_select/data/<rev>_<mode>_curves.csv`
  (revF/snapshot → `revf_snapshot_curves.csv`, revD/track →
  `revd_track_curves.csv`)
- HTML report: written by the collect stage via
  `make_report.py --rev <rev> --sim-mode <mode>` (e.g.
  `curvegen/reports/revd-track-curves.html`)

---

## If a submit fails again

- "Job dependency problem" → fixed in `submit_campaign.sh` (202b83b); if it
  recurs, the captured job id is malformed — run the failing `sbatch` alone and
  read what it printed.
- A stage failed midway → just re-run the same `submit_campaign.sh` line; prep
  seeds and measured sweep points are skipped, only the missing work runs.
</context>

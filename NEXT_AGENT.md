# NEXT_AGENT — start here (updated 17 Aug 2026)

Hand-off sheet for whoever (human or agent) picks this up.  Read order:
`WRAPUP.md` (bmason's 17 Aug scope — the authority) → `RELEASE_PLAN.md`
(the live plan) → `CLAUDE.md` → `README.md` → `PLAN.md` (17-Aug delta
first) → `RUN_CAMPAIGNS.md` → `casaLocation.md`.

## Where things stand (17 Aug 2026)

- **The 21-24 Jul wave COMPLETED unattended and was harvested 17 Aug:**
  canary + adaptive retrofit (array 0-3) + all four PSF backfills, every
  job exit 0.  6590 result rows committed; combined report rebuilt; 225
  tests green.  PSF axis-cut payloads exist for all four campaigns.
- **Retrofit is wave 1 of ~2-3:** snapshot maps mostly converged; nearly
  every revF/track and revD/track map hit the 80-eval audit cap.  All
  step features everywhere came back classified as genuine ("sampled
  resolution discontinuity") — including the once-flagged revD/snapshot
  long ~2.6 mas step.
- **NEW SCOPE (WRAPUP.md):** release = web page + python calculator for
  revF/track (ptsrc+imaging), revD/track (ptsrc only), revC/track (ptsrc
  only — a NEW campaign to build and run).  Snapshots are not released.
  Tasks T0-T6 in RELEASE_PLAN.md; T0 (harvest) is DONE.

## Immediate queue (in order; see RELEASE_PLAN.md for detail)

1. **T1 — retrofit wave 2, tracks only.  bmason launches:**
   ```
   RID=$(sbatch --parsable --array=0,2 /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/adaptive_retrofit.sbatch | tail -1)
   for K in 0 2; do sbatch --array=$K --dependency=afterok:${RID}_$K /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/backfill_psf.sbatch; done
   ```
2. **T2 — revC/track campaign:** extend config.py/registry by the revD
   pattern (Rev C.01 component cfgs are in ngvla-configurations/; lba →
   long), APPEND to config_registry.csv (indices 0-3 must not move),
   tests, then bmason submits.
3. **T3 — release web page** (3-track dropdown, revD/revC imaging marked
   "Omitted/Intentionally blank", core+mid caveat removed, PSF cuts +
   calculator verified).  **T4** calculator surface (revC routing, EOP
   batch input).  **T5** MStroh formats (stretch).  **T6** docs + LaTeX
   memo editorial pass (ASD-STE100 + Zinsser), compile clean.

## Working agreements (bmason) — updated 17 Aug

- **bmason launches ALL Slurm jobs himself** — agents prepare exact
  command lines, never sbatch.
- **Never write outside directories bmason owns** (repo, $WORK, $SCRATCH,
  session scratchpad).
- No web artifacts; local HTML under curvegen/reports/ only.
- Codex bridge for consults/reviews (gpt-5.6-sol); probe its sandbox
  before trusting build mode.  Subagents of equal/lower capability for
  well-specified tasks.
- Use casapy; CASA cwd on scratch; never write CASA products under $HOME.
- Commit at milestones; don't sweep bmason's scratch files (files.txt,
  revDsnapshotIssue.txt, memo/foo.tar, tmp/, ETA_JUMPS.md,
  POLISH_AND_STORAGE.md).

## Sharp edges (full log PLAN §13; 21-Jul ones still apply)

- Job logs from the July wave now live in
  `/work2/10240/bmason72/stampede3/oldNgvlaLogs/` (moved 13 Aug).
- The retrofit budget window resets across kill+resubmit (measurements
  stay resumable; worst case one extra audit cap re-spent).
- backfill_psf exits NONZERO while any anchor lacks cuts — resubmit
  signal, not a bug.
- An agent testing submit_campaign.sh WILL submit real Slurm jobs — use
  --prep-only (and bmason launches jobs anyway, see above).

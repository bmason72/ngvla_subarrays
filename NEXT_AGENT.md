# NEXT_AGENT — start here (updated 18 Aug 2026)

Hand-off sheet for whoever (human or agent) picks this up.  Read order:
`WRAPUP.md` (bmason's 17 Aug scope — the authority) → `RELEASE_PLAN.md`
(the live plan) → `CLAUDE.md` → `README.md` → `PLAN.md` (18-Aug delta
first) → `RUN_CAMPAIGNS.md` → `casaLocation.md`.

## Where things stand (18 Aug 2026)

- **All compute for the release is DONE.**  The 17-Aug wave (retrofit
  wave 2 tracks + backfills; the first revC/track campaign, prep → sweep
  → collect) completed 18 Aug, every job exit 0, and was harvested the
  same day: results committed, combined + release reports rebuilt, 253
  tests green (1 skipped).
- **revC/track is in the release page and calculator.**  9 subarrays,
  PSF payloads included; NO combo-4 PSF backfill is needed (dry-run
  audit: every anchor already cut-bearing).  Residual budget-limited
  steps: long 0.74 (both curves), main+long imaging 0.78 / ptsrc 0.30;
  all else ≤ 0.22.
- **Retrofit wave 3 is an OPEN bmason decision:** wave 2 converged
  revF/track 6/14 maps and revD/track 2/9; the rest hit the 80-eval
  audit cap.  All step features again classified genuine ("sampled
  resolution discontinuity").  Options: another wave (lines below), or
  accept + document.
- Scope (WRAPUP.md): release = web page + python calculator for
  revF/track (ptsrc+imaging), revD/track (ptsrc only), revC/track
  (ptsrc only).  Snapshots are not released.  RELEASE_PLAN T0-T5 DONE;
  T6 (docs + memo) in progress.

## Immediate queue (in order; see RELEASE_PLAN.md for detail)

1. **bmason decision — retrofit wave 3?**  If yes (optionally add combo
   4 to also chase revC's budget-limited long/main+long steps):
   ```
   RID=$(sbatch --parsable --array=0,2,4 /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/adaptive_retrofit.sbatch | tail -1)
   for K in 0 2 4; do sbatch --array=$K --dependency=afterok:${RID}_$K /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/backfill_psf.sbatch; done
   ```
   (Tracks-only variant: `--array=0,2` and `for K in 0 2`.)  After it
   drains: harvest = QA logs, rebuild combined + release reports, tests,
   data commit — same as the 18-Aug delta in PLAN.md.
2. **T6 — finish the memo:** bmason's review comments beyond the §4 ¶1
   stop marker (memo/myComments.tex), then the final editorial pass
   (ASD-STE100 + Zinsser), compile clean.
3. **Final release commit + tag** (RELEASE_PLAN T6 last step).

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

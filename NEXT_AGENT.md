# NEXT_AGENT — start here (updated 19 Aug 2026)

Hand-off sheet for whoever (human or agent) picks this up.  Read order:
`WRAPUP.md` (bmason's 17 Aug scope — the authority) → `RELEASE_PLAN.md`
(the live plan) → `CLAUDE.md` → `README.md` → `PLAN.md` (18-Aug delta
first) → `RUN_CAMPAIGNS.md` → `casaLocation.md`.

## Where things stand (19 Aug 2026)

- **Wave 3 is IN FLIGHT — do not trust the current release page's PSF
  range.**  Retrofits 3418621_{0,2} completed 19 Aug exit 0; the two
  PSF backfills (3418623_0 revF, 3418624_2 revD) — which carry the
  3→10 FWHM cut refresh for every existing anchor — were still RUNNING
  19 Aug evening; revC backfill 3421939_4 was launched later and is also
  RUNNING.  `ngvla-curves-release.html` (rebuilt 19 Aug 11:32)
  therefore still embeds mostly 3-FWHM cuts (verified by decoding its
  payloads: revF 0/2839 at 10 FWHM, revD 451/2852, revC 0/1935) — the
  rebuild was premature.  The chart code is fine (renders each entry at
  its own captured range); only the data lags.  Full story: PLAN.md
  19-Aug delta.
- The 17-Aug wave (retrofit wave 2 tracks + backfills; the first
  revC/track campaign, prep → sweep → collect) completed 18 Aug, every
  job exit 0, and was harvested the same day: results committed,
  combined + release reports rebuilt, 253 tests green (1 skipped).
- **revC/track is in the release page and calculator.**  9 subarrays,
  PSF payloads included.  Its fresh campaign needed no backfill merely
  to add cuts, but the subsequent 3→10 FWHM range upgrade makes all of
  those original cuts stale; backfill 3421939_4 is refreshing them.
  Residual budget-limited steps: long 0.74 (both curves), main+long
  imaging 0.78 / ptsrc 0.30; all else ≤ 0.22.
- **Retrofit wave 3 (tracks only) was LAUNCHED 18 Aug** — the open
  decision is resolved.  Retrofit outcomes not yet QA'd from logs
  (grep lines in RUN_CAMPAIGNS "Adaptive retrofit wave"); wave-2
  history: revF/track 6/14 maps converged, revD/track 2/9, rest at the
  80-eval audit cap, all step features classified genuine.
- Scope (WRAPUP.md): release = web page + python calculator for
  revF/track (ptsrc+imaging), revD/track (ptsrc only), revC/track
  (ptsrc only).  Snapshots are not released.  RELEASE_PLAN T0-T5 DONE;
  T6 (docs + memo) in progress.

## Immediate queue (in order; see RELEASE_PLAN.md for detail)

1. **Wait for the backfills to drain** (3418623_0, 3418624_2,
   3421939_4),
   then **harvest**: check exit codes via sacct (NONZERO = anchors still
   lack cuts → resubmit signal); QA the retrofit logs (grep lines in
   RUN_CAMPAIGNS); verify 10-FWHM coverage by counting `cut_rmax_fwhm`
   in `curvegen/reports/psf/*/*.js` (untagged cut entries = old 3-FWHM);
   rebuild combined + release reports; re-verify the release page by
   decoding its `data-psf-id` gzip+base64 blocks; tests; data commit —
   checklist in the PLAN.md 19-Aug delta.
2. **T6 — finish the memo:** bmason's review comments beyond the §4 ¶1
   stop marker (memo/myComments.tex), then the final editorial pass
   (ASD-STE100 + Zinsser), compile clean.
3. **Final release commit + tag** (RELEASE_PLAN T6 last step).

## Working agreements (bmason) — updated 19 Aug

- **bmason launches ALL Slurm jobs himself** — agents prepare exact
  command lines, never sbatch.
- **Agent sessions with long-running local work** (persistent monitors,
  squeue pollers, big report rebuilds) belong on a **dev node (idev),
  not a login node** (bmason, 19 Aug — a login-node monitor was killed).
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

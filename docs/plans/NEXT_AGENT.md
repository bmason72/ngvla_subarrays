# NEXT_AGENT — start here (updated 21 Sep 2026)

## RESUME HERE (21 Sep 2026) — spiral+5/+10 campaign RUNNING, freeze ACTIVE

**Do not edit `curvegen/`, `sa_select/` or `sa_select/data/*.csv` on `main`**
until collect 3524017 has finished and been checked: each Slurm stage
re-imports them from this checkout when it starts.  Code work goes in a
separate git worktree and merges afterwards.

bmason launched 21 Sep 2026: prep 3523968 (done, seed beams checked clean)
-> sweep 3524014_0 -> collect 3524017, restricted to the four new subarrays
(`spiral+5`, `spiral+10`, `mid+spiral+5`, `mid+spiral+10`) so the other
fourteen subarrays' released curves cannot be touched.

Plan: `docs/plans/spiral-plus-campaign-plan.md` (decisions D12-D15; task S7
is the harvest).  Rolling status and the prep-gate numbers:
`docs/worklog/spiral-plus.md` 21 Sep.  Code landed in commits `892da6c`
(subarrays + subset flag + preflight) and `97d8670` (docs).

When the jobs finish, do S7 in the plan.  Two things to carry into it: the
D14 acceptance check (the routed curves CSV must change by insertions only),
and the D15 question — spiral+10's natural-weight skirt (0.126) is above the
0.10 imaging threshold, which is the first evidence these subarrays may need
a beam cap after all.


Hand-off sheet for whoever (human or agent) picks this up.  Read order:
`docs/plans/WRAPUP.md` (bmason's 17 Aug scope — the authority) → `docs/plans/RELEASE_PLAN.md`
(the live plan) → `CLAUDE.md` → `README.md` → `docs/plans/PLAN.md` (18-Aug delta
first) → `docs/ops/RUN_CAMPAIGNS.md` → `docs/ops/casaLocation.md` → `docs/worklog/`
for the rolling status of any feature currently under active development.

## START HERE (8 Sep 2026) — MFS snapshot production run COMPLETE, harvested

Anything that needs bmason (decision, review, launch, manual step) is listed in
`docs/ACTION_ITEMS.md`; add rows there, not here.

Launched by bmason 7 Sep 2026 ~12:15 CDT (prep 3475087, sweep 3475088, collect
3475089); all three exit 0.  Harvested 8 Sep 2026: 0 failures, refine found 0
defects, 419 tests green (one harmless marginal-sampling warning); routed CSV
`sa_select/data/revf_snapshot_band4_curves.csv` committed.  A band-blind PSF
export bug was found during harvest and fixed on main (commit 7016330,
`fix/psf-export-band` merged): reports now carry PSF panels.  A science
finding on Briggs-robust leverage across track/MFS-snapshot/mono-snapshot is
logged.  Full detail: `docs/worklog/mfs-campaigns.md` 8 Sep entry.  The
campaign freeze is OVER (nothing queued or running); the freeze rule itself
still applies whenever a stage IS queued or running.

- Commits `b52504d` (milestone), `ebde3bc` (docs), and the 7 Sep chain
  commit hold the pre-harvest code.  Rolling status: `docs/worklog/mfs-campaigns.md`.
- The production chain for revF/snapshot/band4 (nchan 32, robust step 0.2,
  both curves, 7 subarrays, refine 200/8) is built, tested and has now run
  end to end.  Launch line (kept for future combos): `bash
  curvegen/submit_campaign.sh revF snapshot --mode mfs --refine-budget 200
  --refine-rounds 8 --time 24:00:00` (`--mode mfs|1chan` replaced `--band`;
  the band key is internal).  FOV at coarse tapers is decided (D9, bmason 7
  Sep 2026): keep the convention, document it in the memo and docs (worklog
  `docs/worklog/mfs-campaigns.md`).  tclean consult saved in
  `docs/worklog/mfs-tclean-consult-2026-09-07.md`.  Harvest checklist: top of
  `docs/ops/RUN_CAMPAIGNS.md`.  bmason launches; agents never sbatch.
- Remaining: A3 (bmason review of the "Rev F — MFS snapshot" report view and
  the robust-axis behaviour) and A14 (possible-later follow-up sims, not
  prioritised).

## Pending merges (built 7 Sep 2026 in $WORK worktrees; merge AFTER collect 3475089 is checked)

Collect 3475089 checked and the campaign data harvested 8 Sep 2026 (see
START HERE above).  `fix/psf-export-band` (commit 7016330) merged to main
8 Sep 2026.  `feature/spiral-plus` merged to main 21 Sep 2026 (D13; task S0
of `docs/plans/spiral-plus-campaign-plan.md`), including a fix for the
latent MFS `KeyError` bug (the branch's `spiral+5`/`spiral+10` rows were
removed from both Band-4 MFS metadata CSVs — those two subarrays are out of
scope for MFS per D12).  Still pending, per A4:

| Branch | Worktree | What | Tests there |
| --- | --- | --- | --- |
| `feature/curve-limits` | `/work2/10240/bmason72/stampede3/ngvla_wt_curvelimits` | manual per-curve valid range: `sa_select/data/curve_limits.csv` (header only), limits at `Envelope.solve`, report/calculator agreement | 458 green |

Note: `feature/curve-limits` edits `curvegen/make_report.py`, which task S1
of `docs/plans/spiral-plus-campaign-plan.md` also edits (its `ORDER` list) —
expect a small merge conflict there whenever curve-limits is finally taken,
in whichever order the two land.  Docs-only items
landed directly on main: glossary + audit fixes (5e18e3d), curve-product design note
(263bd2e).

## Where things stand (5 Sep 2026) — MFS workstream

Rolling status now lives in `docs/worklog/mfs-campaigns.md`; this section is
a snapshot.

- **Mono release (WRAPUP scope):** all Aug/Sep retrofit + backfill jobs done and
  harvested (results committed 4 Sep); reports rebuilt 4 Sep after the
  reconstruction RecursionError fix.  Remaining: T6 memo/editorial + release
  tag (unchanged).
- **MFS-3 pilot:** simulation half DONE (job 3470012; 4 MSes on $SCRATCH).
  Imaging half launcher BUILT, not launched: `curvegen/submit_mfs_imaging_pilot.sh`
  (see docs/ops/RUN_CAMPAIGNS.md first section).  bmason launches.
- **MFS-2d V1 replay:** BUILT (`curvegen/replay_v1.py --suite`; reports in
  `curvegen/reports/v1_replay/`).  **Gate FAILS as specified** — see the 5 Sep
  session delta.  Decision needed from bmason (below) before MFS-4.
- **MFS-4 (wave runner):** not built.  pylauncher/5.3.1 is available on
  Stampede3.  Design requirement learned from the replay + mono retrofits:
  waves must evaluate their 8-16 proposals IN PARALLEL (the driver is serial
  today), because realistic per-map budgets are ~300+ evals, not 140.
- **Scope (6 Sep 2026):** Band 4 only; other bands are obtained by scaling
  the Band-4 curves with wavelength, not by running per-band campaigns.
- **D3/D4 (bmason, 6 Sep 2026):** the adaptive quadtree sampler is set aside
  (parked, not abandoned) for MFS v1, parking MFS-2b/2c/2d/2e, the V1
  replay gate, and MFS-4; production uses the standard mono-style campaign
  chain on the full fixed grid (11 robust values by the canonical 14
  tapers plus the natural row) in Band-4 snapshot mode only, revF, 7
  subarrays, nchan 32, equal noise. No MFS track campaign and no further
  timing benchmark for now. See `docs/worklog/mfs-campaigns.md` for the
  reasoning and what was learned.

## Decisions for bmason (5 Sep, updated 6 Sep)

1. V1 gate: **DECIDED 6 Sep (D3)** — moot; the adaptive sampler is parked
   for v1, so the V1 replay gate does not block production. Investigation
   DONE 6 Sep, report at `curvegen/reports/v1_replay/INVESTIGATION.md`: no
   sampler defect found; the anomalies were a metric bug (fixed), a
   seed-vs-historical-lattice coverage artifact, and sparse-subset
   aliasing; the one traced track map genuinely needed ~560 evals. If the
   sampler is revived later, the recommendation is a continuous surrogate
   oracle (interpolated legacy surfaces) or certification against the
   cheap snapshot MFS full grids.
2. Fresh seed tapers: **moot while parked (D3)** — this only matters if the
   sampler is revived.
3. nchan + noise policy: **DECIDED 6 Sep** — nchan pinned at 32 for band4
   (see `docs/plans/MFS_CAMPAIGN_PLAN.md`); noise policy stays `equal`, no
   decision needed. Noise A/B at band 2 remains moot while MFS is Band-4
   only (config hard-pins `equal`).

Open questions (bmason, 6 Sep 2026):

4. Point-source curves only, or both point-source and imaging curves, from
   the full grid?
5. Keep the 7-subarray set (core-inner, core, spiral, mid, core+spiral,
   spiral+mid, main)?
6. Whether Band-4 results enter the combined release page and calculator, or
   stay as per-combo CSVs and reports for now.
7. When to make the milestone commit of the MFS code.

## Immediate queue (in order)

1. Not needed (bmason, 7 Sep): the 27-vs-54 snapshot confirmation run
   (D10) will not be run.
2. Scout and spec what the standard campaign chain (prep, sweep, refine,
   fill_grid, collect, report) needs to run for revF/snapshot/band4 at
   nchan 32, including removing adaptive-only guards that reject full-grid
   MFS.
3. `fill_beam_caps` for band4 (main's cap is blank).
4. bmason launches the snapshot full-grid wave.
5. Milestone commit of the MFS code + specs once bmason has reviewed.

## Where things stand (19 Aug 2026) — mono release (historical)

- **Wave 3 is IN FLIGHT — do not trust the current release page's PSF
  range.**  Retrofits 3418621_{0,2} completed 19 Aug exit 0; the two
  PSF backfills (3418623_0 revF, 3418624_2 revD) — which carry the
  3→10 FWHM cut refresh for every existing anchor — were still RUNNING
  19 Aug evening; revC backfill 3421939_4 was launched later and is also
  RUNNING.  `ngvla-curves-release.html` (rebuilt 19 Aug 11:32)
  therefore still embeds mostly 3-FWHM cuts (verified by decoding its
  payloads: revF 0/2839 at 10 FWHM, revD 451/2852, revC 0/1935) — the
  rebuild was premature.  The chart code is fine (renders each entry at
  its own captured range); only the data lags.  Full story: docs/plans/PLAN.md
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
- Scope (docs/plans/WRAPUP.md): release = web page + python calculator for
  revF/track (ptsrc+imaging), revD/track (ptsrc only), revC/track
  (ptsrc only).  Snapshots are not released.  RELEASE_PLAN T0-T5 DONE;
  T6 (docs + memo) in progress.

## Immediate queue (in order; see docs/plans/RELEASE_PLAN.md for detail)

1. **Wait for the backfills to drain** (3418623_0, 3418624_2,
   3421939_4),
   then **harvest**: check exit codes via sacct (NONZERO = anchors still
   lack cuts → resubmit signal); QA the retrofit logs (grep lines in
   RUN_CAMPAIGNS); verify 10-FWHM coverage by counting `cut_rmax_fwhm`
   in `curvegen/reports/psf/*/*.js` (untagged cut entries = old 3-FWHM);
   rebuild combined + release reports; re-verify the release page by
   decoding its `data-psf-id` gzip+base64 blocks; tests; data commit —
   checklist in the docs/plans/PLAN.md 19-Aug delta.
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
  revDsnapshotIssue.txt, memo/foo.tar, tmp/, docs/architecture/ETA_JUMPS.md,
  docs/ops/POLISH_AND_STORAGE.md).

## Sharp edges (full log PLAN §13; 21-Jul ones still apply)

- Job logs from the July wave now live in
  `/work2/10240/bmason72/stampede3/oldNgvlaLogs/` (moved 13 Aug).
- The retrofit budget window resets across kill+resubmit (measurements
  stay resumable; worst case one extra audit cap re-spent).
- backfill_psf exits NONZERO while any anchor lacks cuts — resubmit
  signal, not a bug.
- An agent testing submit_campaign.sh WILL submit real Slurm jobs — use
  --prep-only (and bmason launches jobs anyway, see above).

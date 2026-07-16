# NEXT_AGENT — start here (updated 16 Jul 2026, evening)

Hand-off sheet for whoever (human or agent) picks this up.  Read order:
`CLAUDE.md` (task + raw-materials map; its freshness banner points here) →
`README.md` (layout + commands) → `PLAN.md` (status; the **15 Jul part-2**
and **16 Jul** session deltas and the **PSF inspector plan** are the live
sections) → `RUN_CAMPAIGNS.md` (Slurm run sheet + post-polish residual
table) → `casaLocation.md` (TACC environment).  bmason's own reference
notes `ETA_JUMPS.md` and `POLISH_AND_STORAGE.md` (untracked) explain why
eta jumps happen and how polish samples — accurate and worth reading.

## Where things stand (through commit be0003e + the 16 Jul data)

- **POLISH campaigns: 3 of 4 DONE** (16 Jul; revF/snapshot, revD/snapshot,
  revD/track).  All curve CSVs, per-combo reports, PSF payloads, and the
  combined report are CURRENT.  Headline: budget exhaustion eliminated
  (one exception below); most of bmason's flagged defects fixed
  (revF/snapshot main+long imaging 1.42→0.24; revD/track mid+long spike
  gone; nearly everything ≤0.25 on both curves).
- **Survivors** (RUN_CAMPAIGNS.md table): they stopped on **candidates
  exhausted**, not budget — dense local sampling did not move them, which
  is now real evidence of physics/branch transitions rather than
  under-sampling.  Biggest: revD/snapshot main+long ptsrc 1.58 (the
  snapshot natural-end eta cliff), revD/track main+long imaging 1.09,
  revD/snapshot long 0.72 (sparse snapshot LONG), revD/track spiral+mid
  imaging 0.36.  Exception: revD/track `long` imaging 1.21 hit the
  200-point budget — a plain resubmit continues it.
- **PSF inspector (P3+P4) is LIVE** in every report: subarray dropdown,
  heatmap-cell / sample-mark click-through, per-row "PSF" button in the
  calculator; lazy payloads under `curvegen/reports/psf/` (must travel
  with the HTML).  revF/track shows "pending backfill" until it has
  profiles.  Codex (gpt-5.6-sol) built it in build mode — its sandbox
  works again on this login node; probe before relying on it.
- Two commits today: 553a765 (crash fixes: sbatch cwd pinned to scratch,
  fill_beam_caps default no-op) and be0003e (P3+P4).  98→102 tests green
  (`casapy -m unittest discover -s tests -t .`).

## Immediate queue (in order)

1. **bmason launches the LAST polish campaign** — revF/track (queue is
   empty): see RUN_CAMPAIGNS.md "Remaining launch".  Optionally resubmit
   revD/track at the same time (only `long` continues; everything else
   no-ops).  NB the queue limit: verify all three job ids print per
   campaign; a lost collect can be run locally (gotcha in PLAN §13).
2. **bmason decision — surviving jumps**: (a) dense 1-D taper scans
   through the surviving intervals (diagnostic: artifact vs physics vs
   beam-fit branch), (b) bisection-style direct resolution targeting in
   refine.py (codex advisory, sketched in PLAN part-2 "Logged-for-later"),
   or (c) accept + document.  The snapshot ptsrc cliffs right above the
   natural beam are the flagship case.
3. **PSF inspector P1** (axis-cut capture in measure.py/sweep.py — spec in
   PLAN "PSF inspector plan"): can land any time; ideally before P2.
4. **PSF inspector P2** (anchor backfill) — **only after revF/track polish
   lands** (refinement moves the anchors it targets).  Gives revF/track
   its profiles and every campaign its anchor cuts.
5. Standing items: bmason eyeball of the combined report + snapshot
   convention sign-off + LONG-snapshot offering (ASK list, PLAN part 2);
   memo read; cross-revision comparison report (spec first).

## Working agreements (bmason)

- **No web artifacts** — local HTML under `curvegen/reports/` only.
- **Codex bridge** for design consults, diff reviews, and (sandbox
  permitting) build-mode implementation (`codex-bridge/PROTOCOL.md`).
  Model id `gpt-5.6-sol` via `CODEX_MODEL`; effort per bmason's ask.  Run
  the bridge from the repo root (its output + resume state are
  cwd-relative).
- Use `casapy` (never bare python for CASA work); CASA jobs need cwd on
  scratch; never write CASA products under `$HOME` (14 GB quota).
- Commit at milestones; don't sweep bmason's scratch files (ETA_JUMPS.md,
  POLISH_AND_STORAGE.md, files.txt, revDsnapshotIssue.txt,
  NEXT_AGENT_old.md, memo/foo.tar, tmp/) into commits.

## Sharp edges (full log: PLAN §13)

- Slurm jobs inherit the SUBMISSION dir as cwd; CASA TempLattice* lands
  there.  Campaign sbatches pin cwd to scratch — keep that in new sbatches.
- The per-user queued-job limit truncates multi-campaign submissions
  (a prep without a sweep / sweep without collect).  Check all three ids.
- Never name a shell variable `GROUPS`.
- Resumable sweeps preserve stale conventions forever; the collector
  hard-fails on convention violations (cell rule, degenerate rows) by
  design — repair/strip, don't bypass.
- `refine.py` sees exactly what the report draws (eta ≤ 5, ok+capped,
  cap-clipped, BOTH curves).  Keep it that way.
- The report template re-renders per campaign: new panels must clear
  their containers, wire persistent-element listeners ONCE, read DATA at
  call time, and guard async draws with the render token (see the PSF
  panel for the pattern).
- MS stores live on `$WORK` (`NGVLA_MS_BASE`); export it for interactive
  non-default sweeps.  `sbatch --array=0-3 curvegen/regen_ms.sbatch`
  re-simulates anything missing.

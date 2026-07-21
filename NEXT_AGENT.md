# NEXT_AGENT — start here (updated 21 Jul 2026)

Hand-off sheet for whoever (human or agent) picks this up.  Read order:
`CLAUDE.md` (task + raw-materials map; its freshness banner points here) →
`README.md` (layout + commands) → `PLAN.md` (status; the **15 Jul part-2**
and **16 Jul** session deltas and the **PSF inspector plan** are the live
sections) → `RUN_CAMPAIGNS.md` (Slurm run sheet + post-polish residual
table) → `casaLocation.md` (TACC environment).  bmason's own reference
notes `ETA_JUMPS.md` and `POLISH_AND_STORAGE.md` (untracked) explain why
eta jumps happen and how polish samples — accurate and worth reading.

## Where things stand (21 Jul audit; PLAN.md 21-Jul delta has details)

- **POLISH campaigns: 4 of 4 DONE.**  bmason launched the last one
  (revF/track) 16 Jul 16:19, minutes after the 16-Jul docs were committed
  saying "still to launch"; its full chain completed 16:39 and the queue
  has been empty since.  All curve CSVs, per-combo reports, PSF payloads,
  and the combined report are CURRENT (the 16:39 collect rebuilt them with
  HEAD code) — regenerating reports now is a no-op.  Headline: budget
  exhaustion eliminated (one exception below); most of bmason's flagged
  defects fixed (revF/snapshot main+long imaging 1.42→0.24; revD/track
  mid+long spike gone; ALL revF/track imaging curves ≤0.19; nearly
  everything ≤0.25 on both curves).
- **Survivors** (RUN_CAMPAIGNS.md table): they stopped on **candidates
  exhausted**, not budget — dense local sampling did not move them, which
  is now real evidence of physics/branch transitions rather than
  under-sampling.  Biggest: revD/snapshot main+long ptsrc 1.58 (the
  snapshot natural-end eta cliff), revD/track main+long imaging 1.09,
  revD/snapshot long 0.72 (sparse snapshot LONG), revF/track main+long
  ptsrc 0.38 and long+mid+spiral+core-outer ptsrc 0.42, revD/track
  spiral+mid imaging 0.36.  Exception: revD/track `long` imaging 1.21 hit
  the 200-point budget — a plain resubmit continues it.
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

0. **NEW WORKSTREAM (16 Jul, planned): broadband MFS continuum campaigns**
   — per-band (1-6) ptsrc curves, revF homogeneous+main, both modes, under
   a 1-queue-slot multi-node PyLauncher wave.  Full plan + scope decisions
   + codex-sol adjudication: PLAN.md "MFS broadband continuum campaigns".
   Build order: retrospective lattice validation → band-axis machinery →
   pilots (nchan convergence + noise A/B + cost/packing; bmason checkpoint)
   → wave runner → waves.
1. ~~bmason launches the LAST polish campaign~~ **DONE 16 Jul 16:39**
   (revF/track completed end-to-end; see PLAN.md 21-Jul delta).
2. **bmason decision — surviving jumps**: (a) dense 1-D taper scans
   through the surviving intervals (diagnostic: artifact vs physics vs
   beam-fit branch), (b) bisection-style direct resolution targeting in
   refine.py (codex advisory, sketched in PLAN part-2 "Logged-for-later"),
   (c) accept + document, and/or the cheap lever: resubmit revD/track
   polish (continues only its budget-limited `long` imaging refine;
   everything else no-ops — command in RUN_CAMPAIGNS.md §1).  The snapshot
   ptsrc cliffs right above the natural beam are the flagship case.
3. **PSF inspector P1** (axis-cut capture in measure.py/sweep.py — spec in
   PLAN "PSF inspector plan"): can land any time; ideally before P2.
4. **PSF inspector P2** (anchor backfill) — **now UNBLOCKED** (revF/track
   polish landed; refinement no longer moves the anchors it targets).
   Gives revF/track its profiles and every campaign its anchor cuts.
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

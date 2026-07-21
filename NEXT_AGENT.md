# NEXT_AGENT — start here (updated 21 Jul 2026, end of session; WAVE IN FLIGHT)

Hand-off sheet for whoever (human or agent) picks this up.  Read order:
`CLAUDE.md` → `README.md` → `PLAN.md` (the THREE 21-Jul deltas are the live
sections) → `RUN_CAMPAIGNS.md` ("21 Jul wave" launch sheet) →
`MFS2_ADAPTIVE_SAMPLER_SPEC.md` + `MFS_CAMPAIGN_PLAN.md` (next workstream)
→ `casaLocation.md`.

## Where things stand (through commit 07a144e + the in-flight canary)

- **21 Jul curve-quality upgrade LANDED (commit 09d6d7e, 177 tests green):**
  refine.py escalation ladder (E1 secant / E2 staged progressive taper
  scans at BOTH bracket robusts / E3 homogeneous gap chasing / E4 bumps,
  with terminal classification of genuine discontinuities), display-only
  curve smoothing (bounded 0.03/0.02, drawn line only — raw untouched for
  refine + sa_select), PSF inspector P1 (axis cuts, sign-correct) and P2
  (anchor backfill, results-CSV-untouched by construction).  Everything
  was codex-guard-reviewed (5 blockers found and fixed — the axis-cut
  sign bug and the classify-scan display-contract violation were real).
- **The 21 Jul WAVE is IN FLIGHT (canary stage).**  Submitted 21 Jul pm,
  still PENDING (Priority) at hand-off: revD/track canary — prep 3333952 →
  sweep 3333953[0-3] → collect 3333954 → PSF backfill 3333958[2]
  (afterok-chained).  The session's watcher process died with the login
  window: **someone must check these jobs by hand** (`squeue -u bmason72`,
  `sacct -X -S 21jul26`; logs in /work2/10240/bmason72/stampede3/).
- **Beam-cap question (bmason 21 Jul): resolved as a memo misreading** —
  caps bind only the COARSE end, reference = coarsest component, ranges
  relay with ~2x seam overlap.  Memo wording fixed + recompiled (07a144e).
- **Adaptive-sampler direction APPROVED (bmason):** quadtree/AMR,
  tolerance-scaled hierarchical-residual loss, cliff localization
  semantics; skirt tolerance 0.02 ABSOLUTE; spec drafted =
  `MFS2_ADAPTIVE_SAMPLER_SPEC.md` (supersedes MFS scope decision 4).
  A codex review of the spec was launched at session end and may not have
  completed — if `tmp/codex/tasks/` has no fresh review output, re-run:
  `CODEX_MODEL=gpt-5.6-sol codex-bridge/codex_bridge.sh consult` with the
  spec + "review this spec" prompt, and adjudicate findings into the spec.

## Immediate queue (in order)

1. **Inspect the canary when it finishes** (revD/track).  QA:
   `grep -E "refined|budget|worst|escalation|E2 " /work2/.../sweep_3333953_*.log`
   Healthy = E2 plans with small-taper scans at both bracket robusts,
   terminal classifications ("sampled resolution discontinuity" /
   "high-penalty"), no runaway budget (240 cap), worst in-band steps
   shrinking vs the RUN_CAMPAIGNS survivors table.  The collect hard-fails
   on convention violations by design — a failed collect means repair, not
   bypass.  If the sweep looks pathological: scancel downstream, diagnose,
   fix, resubmit (everything is resumable).
2. **Launch the remaining three campaigns + their backfills** (serialized
   vs the queue limit; exact commands in RUN_CAMPAIGNS.md "21 Jul wave"):
   revF/snapshot, revD/snapshot, revF/track (budget 200, rounds 12), each
   followed by `sbatch --array=<1|3|0> --dependency=afterok:<its collect>`
   backfill.  Verify all three job ids print per campaign (queue-limit
   gotcha).  Backfill task 0 (revF/track, ~949 anchors) will likely need a
   resubmit at the 47 h ceiling — it is resumable and exits nonzero while
   anchors remain.
3. **After ALL backfills: rebuild the combined report** (command in
   RUN_CAMPAIGNS §3) and eyeball the flagged curves: snapshot main+long /
   main ptsrc cliffs (expect CLASSIFIED + honestly stepped, likely NOT
   filled — physics), revD/track spiral+mid sawtooth (expect FILLED),
   disconnected LONG points (expect filled or confirmed), wiggles (expect
   visually smooth lines within 0.03).  **bmason's standing bet:** the
   wave might not fully fix the holes — if specific maps remain
   under-converged, they become the retrofit-mode pilot for the adaptive
   sampler (spec §"Retrofit mode"), which doubles as the bet's data-driven
   answer.  Then: milestone commit of the wave's data + doc deltas.
4. **MFS workstream:** MFS-1 replay ∥ MFS-2a (band axis) per
   `MFS2_ADAPTIVE_SAMPLER_SPEC.md` task table — 2b sampler core next; the
   V1 replay gate (2d) is a bmason checkpoint.  MFS-3 pilots need queue
   slots — wait for the wave to drain.
5. Standing: memo update for the new machinery (escalation ladder +
   smoothing + caps clarification are NOT yet described in the memo beyond
   the cap fix); ASK-list leftovers (snapshot convention sign-off,
   LONG-snapshot offering); cross-revision comparison report (spec first).

## Working agreements (bmason) — unchanged

- No web artifacts; local HTML under curvegen/reports/ only.
- Codex bridge for design consults + diff reviews (gpt-5.6-sol via
  CODEX_MODEL; run from repo root).  Its TACC sandbox was BROKEN for
  writes all day 21 Jul (bwrap namespace) — consult-only with inlined
  content; probe before trusting build mode.
- Use casapy; CASA cwd on scratch; never write CASA products under $HOME.
- Commit at milestones; don't sweep bmason's scratch files (files.txt,
  revDsnapshotIssue.txt [stale, 13 Jul], memo/foo.tar, tmp/, ETA_JUMPS.md,
  POLISH_AND_STORAGE.md).

## Sharp edges (new ones from 21 Jul; full log PLAN §13)

- refine.py's escalation counters double-tally bumps worked via E2
  (intentional; don't "fix" without reading the code comment).
- E2/E1 probes must stay CELL-COMPLETE (E0: singletons are invisible to
  the envelope).  take_group() enforces it — keep it that way.
- The smoother must never see a >0.20 step or a gap as one segment; its
  hard bounds (0.03/0.02) are enforcement, the 0.06 print is forensics.
- backfill_psf exits NONZERO while any anchor lacks cuts — that is the
  resubmit signal, not a bug.
- sweep.point_key now folds -0.00 → 0.00 centrally.
- submit_campaign.sh rejects 0 for budget/rounds/scan-points; NEW env
  passthrough NGVLA_REFINE_SCAN_POINTS (default 8).
- An agent testing submit_campaign.sh WILL submit real Slurm jobs — use
  --prep-only or scancel immediately (it happened once on 21 Jul; zero
  compute ran).

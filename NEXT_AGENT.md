# NEXT_AGENT — start here (updated 15 Jul 2026)

Hand-off sheet for whoever (human or agent) picks this up.  Read order:
`CLAUDE.md` (task + raw-materials map; its freshness banner points here) →
`README.md` (layout + commands) → `PLAN.md` (status; the **15 Jul session
delta part 2** and the **PSF inspector plan** are the live sections) →
`RUN_CAMPAIGNS.md` (Slurm run sheet) → `casaLocation.md` (TACC environment).

## Where things stand (commit 2803b61 + this docs pass)

- **Four campaigns swept and reported**: revF/track (mature), revF/snapshot,
  revD/track, revD/snapshot.  Curves live in `sa_select/data/*_curves.csv`
  (registry-routed via `config_registry.csv`); results CSVs in
  `curvegen/results-*/`.
- **15 Jul defect diagnosis is DONE** (PLAN part 2): visible jumps =
  refine-budget starvation (+ two refine bugs, both fixed: eta>5
  fringe-chasing, imaging-only chasing); one corrupt snapshot LONG row
  (stripped, guards added at measure + publish time); snapshot curves
  legitimately start at ≈ natural for sparse single-component subarrays
  (single-integration uv occupancy — physics, documented in-report).
- **Flagship report**: `curvegen/reports/ngvla-curves.html` — all four
  campaigns behind a dropdown (`make_report.py --combined`).  Per-combo
  reports still build; both refresh in the campaign collect stage.
- **MS stores moved to `$WORK/ngvla_curvegen`** (scratch purges;
  checksum-verified).  `NGVLA_MS_BASE` routes non-default combos — export it
  for interactive non-default sweeps.  Insurance:
  `sbatch --array=0-3 curvegen/regen_ms.sbatch` re-simulates missing MSes.
- 98 tests green: `casapy -m unittest discover -s tests -t .` (repo root).

## Immediate queue (in order)

1. **bmason launches the four POLISH campaigns** — commands in
   `RUN_CAMPAIGNS.md` §1 (refine budget 200 / rounds 8; base stages are
   resumable no-ops).  These exist to erase the census-tabled steps.
2. **QA the polish results**: per subarray, both `(imaging)` and `(ptsrc)`
   "worst in-band step" lines in the sweep logs should be ≤ ~0.25; then
   confirm the collect stage refreshed the curve CSVs + reports, eyeball
   `ngvla-curves.html`, and make a milestone commit of the refreshed data.
3. **PSF inspector** (bmason-approved design, PLAN "PSF inspector plan"):
   P1 capture extension (anytime) → P2 anchor backfill (**only after polish
   lands** — anchors move) → P3 payload export → P4 report panel → P5 docs.
4. Standing open items: bmason's ASK list in PLAN part 2 (snapshot
   convention sign-off, LONG-snapshot offering, combined-report eyeball);
   memo needs bmason read; codex advisories logged in PLAN part 2
   (dense 1-D diagnostic scans if any jump survives polish, etc.).

## Working agreements (bmason)

- **No web artifacts** — local HTML under `curvegen/reports/` only.
- **Codex bridge** for design consults + diff reviews
  (`codex-bridge/PROTOCOL.md`); model id is `gpt-5.6-sol` (NOT `gpt-5.6`),
  set via `CODEX_MODEL`; Codex cannot read files on TACC — inline
  everything; run the bridge from the repo root (output lands in
  `<cwd>/tmp/codex/last_message.md`).
- Use `casapy` (never bare python for CASA work); sweeps need cwd on
  scratch; never write CASA products under `$HOME` (14 GB quota).
- Commit at milestones; don't sweep bmason's scratch files (`files.txt`,
  `revDsnapshotIssue.txt`, `NEXT_AGENT_old.md`, `memo/foo.tar`, `tmp/`)
  into commits.

## Sharp edges (full log: PLAN §13)

- Never name a shell variable `GROUPS` (bash special var; killed two
  campaigns silently).
- Resumable sweeps preserve stale conventions forever — any measurement-
  convention change needs a repair/strip pass, and the collector hard-fails
  on convention violations (cell rule, degenerate rows) by design.
- `refine.py` sees exactly what the report draws (eta ≤ 5, ok+capped rows,
  beam-cap clipped).  Keep it that way — divergence burned 60-point budgets
  invisibly once already.
- The report template re-renders per campaign: new panels must clear their
  containers, wire listeners ONCE, and read DATA at call time (see
  renderAll / bindData; the PSF panel plan repeats this).

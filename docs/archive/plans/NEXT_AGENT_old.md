# Kickoff prompt for the next agent

NOT UPDATED OR CURRENT this file is probably misleading and obsolete
it is from a previous dev iter

You are Opus 4.8 picking up the NGVLA subarray-selection project from a
previous agent (Fable 5; its final state is git tag 'fable-final' on main).
You have a second model available through the codex bridge — read
codex-bridge/CLAUDE.local.md and codex-bridge/PROTOCOL.md before first use.

ORIENT (read in this order before doing anything):
1. CLAUDE.md                      — task statement, repo map, environment rules
2. docs/plans/PLAN.md, top section "HANDOFF STATE (7 Jul 2026)" — current state, open
   items, and the gotchas log (§13). Trust this over any older section.
3. docs/postmortems/2026-07-06-curve-anomaly.md    — why sa_select/envelope.py is what it is
4. docs/architecture/mstroh_comparison.md           — external validation status
5. docs/ops/casaLocation.md                — TACC environment (READ BEFORE running CASA)

ENVIRONMENT (TACC Stampede3, compute node):
- Python/CASA: /work2/10240/bmason72/stampede3/casaenv/bin/casapy (a python3
  wrapper; NEVER use system python or tashton's CASA install).
- $HOME quota is 14 GB. curvegen/ms and curvegen/work are symlinks to
  $SCRATCH. Any process that runs tclean MUST have its cwd on $SCRATCH
  (CASA writes multi-GB TempLattice* files to cwd).
- Tests: casapy -m unittest discover -s tests -t .   (all green at handoff)
- sbatch only works from login nodes; ask me to submit if needed.


═══════════════════════════════════════════════════════════════════════

WORKING AGREEMENTS (from our sessions — keep these):
- Use codex as a thinking partner (consult) for design decisions and as a
  builder (codex_loop --mode build --base main) for well-specified,
  mechanical work; YOU write the specs, review every diff, and adjudicate
  every finding. Run a guard review before declaring substantive code done.
- Weigh codex output on its merits; it has caught real bugs in both
  directions. Never treat either model as gospel.
- Everything long-running: background it, make it resumable, verify CSV
  integrity after crashes. Use sweep_parallel.py / fill_grid.py patterns.
- The curve engine (sa_select/envelope.py) is shared by the selector AND
  the report — never fork the logic. Changes need tests; the named
  anomalies in tests/test_envelope.py must stay pinned.
- Local HTML reports only — never publish artifacts to the web.
- Keep docs/plans/PLAN.md's HANDOFF STATE current as you work; log new gotchas in
  §13. Commit at milestones with descriptive messages.
- Check in with me (bmason) before: changing curve/selection semantics,
  dropping/adding offered subarrays, or launching compute campaigns beyond
  what's already authorized.

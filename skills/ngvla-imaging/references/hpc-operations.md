# Operational hygiene running ngVLA CASA sims on HPC

These are patterns observed running ngVLA taperability/sculpting campaigns
on a shared HPC cluster (TACC Stampede3, in the source repo) under Slurm.
The specific paths are that repo's; the *patterns* generalize to any shared
HPC + Slurm + CASA setup.

## CASA environment

- Prefer a modular CASA install (`casatools`/`casatasks` installed into a
  plain Python venv) over a vendor "casa" launcher bundle if one is
  available and known-good; a broken/stale vendor install is a real,
  observed failure mode (import errors that only surface once you actually
  call into C++ extensions, after the launcher appears to start fine).
- Cluster library environments (e.g. Intel oneAPI's `LD_LIBRARY_PATH`) can
  conflict with CASA's bundled OpenMPI and cause obscure symbol-not-found
  crashes; a thin wrapper script that sanitizes `LD_LIBRARY_PATH` before
  invoking the venv's Python is a reasonable fix — don't assume a crash like
  this is a CASA bug before checking the library search path.
- CASA downloads a sizeable measures-data table (several hundred MB) to
  `~/.casa/data` on first use in a given environment — expect this on first
  run in a fresh environment/container.

## Never run CASA work in `$HOME`

Home directories on shared HPC are typically small-quota (tens of GB) and
**not** meant for scratch. CASA's imaging tasks (`tclean` especially) create
large temporary "TempLattice" files **in the process's current working
directory**, not in a configurable temp dir — so the *cwd* CASA is launched
from, not just where output images are named, must be on scratch-class
storage. Running a sweep with cwd under `$HOME` can blow the home quota
almost immediately.

## Storage tiering

A workable three-tier pattern:

- **Durable inputs/outputs** (measurement sets, results tables, reports) on
  a persistent, larger-quota filesystem (e.g. `$WORK`-class storage) —
  survives between sessions and isn't subject to scratch purge policies.
- **tclean scratch** (TempLattice churn, per-point imaging work directories)
  on a purge-eligible scratch filesystem (e.g. `$SCRATCH`-class) — treat
  everything there as disposable and regeneratable from the durable inputs.
- **Never** point either at `$HOME`.

Point CASA at these via environment variables your simulate/sweep code reads
(e.g. an `MS_BASE`/`SCRATCH_BASE` pair), not hardcoded paths, so different
machines/users can relocate storage without code changes.

## Resumable sweeps

A (robust x taper) grid times (subarrays) times (curve types) can be
hundreds to thousands of tclean calls, each potentially minutes to hours
(composite/heterogeneous subarrays with huge `imsize` are the expensive
ones). Any sweep driver should:

- record each measured point (or "skipped"/"failed" outcome) to a results
  table keyed by its lattice coordinates, and **skip already-recorded
  points** on restart — a killed job or an extended grid should resume, not
  restart from scratch;
- **catch and log failures per-point** (don't let one bad tclean call abort
  an entire multi-hour array job) — record the failure with enough context
  (subarray, robust, taper, traceback) to diagnose later, then continue;
- clean up each point's scratch image products immediately after extracting
  the needed scalar measurements, so disk doesn't fill mid-sweep;
- prune the parameter grid deliberately up front (e.g. an early-stop rule
  once a composite subarray's beam has clearly moved into a coarser
  component's native regime) rather than measuring an unbounded lattice —
  but be wary of *over*-pruning: a documented failure mode in the source
  repo was pruning too aggressively and leaving holes that broke downstream
  interpolation, which had to be walked back to "measure the full grid."

## Working-tree / Slurm interaction

- Slurm array/step jobs commonly `import` project code (config, sweep
  logic) **fresh at each stage's start** from whatever is on disk in the
  working tree at that moment. If you edit the working tree while a
  campaign's stages are still queued or running, a later stage can pick up
  your in-progress edit rather than the code the campaign was launched
  with — silently corrupting or invalidating results. **Do not edit a
  working tree that has a campaign's Slurm stages queued or running**; use
  a separate checkout/worktree for concurrent code work and merge only
  after the campaign's stages have completed and been checked.
- Respect the cluster's/project's job-queue etiquette (e.g. a shared
  informal cap on how many queued jobs one user keeps outstanding at once,
  such as an observed 8-job soft limit) — don't flood the scheduler even if
  technically permitted.
- **Agents should prepare command lines, not launch Slurm jobs themselves**,
  unless the human operator has explicitly delegated that. Draft the exact
  `sbatch`/`srun` invocation (with a short explanation of what it does and
  what to check afterward), and let the human decide when to submit it. This
  is a strict convention in the source repo (see its `CLAUDE.md`) and a
  reasonable default anywhere shared compute and irreversible queue time are
  involved.

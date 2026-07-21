#!/bin/bash
#SBATCH -J ngvla_sweep
#SBATCH -A AST25010
#SBATCH -o /work2/10240/bmason72/stampede3/sweep_%A_%a.log
#SBATCH -p icx
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 48:00:00
# ^ walltime CEILING per array task; submit_campaign.sh overrides with --time
#   (24 h snapshot, 48 h track).  Everything is resumable, so a task that hits
#   the limit continues on resubmit.

# CAMPAIGN SWEEP (stage 2 of 3).  A Slurm JOB ARRAY: each task full-sweeps one
# group of subarrays on its own node.  Per bmason's rule the long-baseline
# (> 2600 km) subarrays are one-per-node heavy tasks and everything else shares
# the final grouped task -- campaign_tasks.py `groups` defines the mapping and
# SLURM_ARRAY_TASK_ID selects the line.  Depends (afterok) on campaign_prep.
set -u
CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy
: "${NGVLA_REV:?export NGVLA_REV (use submit_campaign.sh)}"
: "${NGVLA_SIM_MODE:?export NGVLA_SIM_MODE (use submit_campaign.sh)}"
export NGVLA_SCRATCH="${NGVLA_SCRATCH:-$SCRATCH/ngvla_curvegen}"
export NGVLA_MS_BASE="${NGVLA_MS_BASE:-$WORK/ngvla_curvegen}"
mkdir -p "$NGVLA_MS_BASE"
mkdir -p "$NGVLA_SCRATCH"
# CASA writes multi-GB TempLattice* images to the process cwd, which Slurm
# inherits from the SUBMISSION directory -- pin it to scratch so submitting
# from $HOME/the repo can never blow the home quota.  refine.py in particular
# has no scratch-cwd management of its own (sweep_parallel/fill_grid do): the
# 15 Jul 2026 polish refines core-dumped on exactly this
# ("FiledesIO ... Disk quota exceeded", TempLattice debris in the repo).
RUN_CWD="$NGVLA_SCRATCH/run_${SLURM_JOB_ID:-manual}${SLURM_ARRAY_TASK_ID:+_$SLURM_ARRAY_TASK_ID}"
mkdir -p "$RUN_CWD"; cd "$RUN_CWD"
# refine intensity: the default (60/3) matches the original campaigns; a
# POLISH pass (base grids already swept, so sweep_parallel/fill_grid are
# fast no-ops) raises these via submit_campaign.sh --refine-budget/-rounds
REFINE_BUDGET="${NGVLA_REFINE_BUDGET:-60}"
REFINE_ROUNDS="${NGVLA_REFINE_ROUNDS:-3}"
# E2 escalation knob (taper levels per interval); default 8 matches refine.py
REFINE_SCAN_POINTS="${NGVLA_REFINE_SCAN_POINTS:-8}"

# preflight: fail closed if the caps this combo needs are not in the metadata
# CSV, so a full grid never runs uncapped (no-op for revF/track)
"$PY" "$CG/fill_beam_caps.py" --verify \
    || { echo "SWEEP: cap preflight FAILED -- run prep/fill_beam_caps first"; exit 1; }

# resolve this task's subarray group (guard the helper: a campaign_tasks
# failure must NOT collapse into an empty task and a bogus success).
# NB: must NOT be named GROUPS -- that is a bash special variable (the user's
# group ids); assigning to it FAILS with status 1, which silently killed every
# task of the 12 Jul 2026 campaigns ("SWEEP: campaign_tasks FAILED" with no
# traceback).  Same trap for UID/EUID/BASH*/SHELLOPTS.
SA_GROUPS=$("$PY" "$CG/campaign_tasks.py" groups) \
    || { echo "SWEEP: campaign_tasks FAILED"; exit 1; }
TASK=$(printf '%s\n' "$SA_GROUPS" | sed -n "$((SLURM_ARRAY_TASK_ID+1))p")
if [ -z "${TASK:-}" ]; then
    echo "no group for array index $SLURM_ARRAY_TASK_ID -- nothing to do"; exit 0
fi
echo "=== SWEEP task $SLURM_ARRAY_TASK_ID  rev=$NGVLA_REV mode=$NGVLA_SIM_MODE  group=[$TASK] ==="

# rc tracks BASE-sweep failures only: sweep_parallel produces the curve data, so
# a failure there must make this array task exit nonzero -> the afterok collect
# job will NOT run on missing data.  fill_grid/refine are polish passes (heatmap
# holes / imaging-curve smoothing); their failures warn but do not block collect.
rc=0
for SA in $TASK; do
    echo "=== sweep $SA ==="
    "$PY" "$CG/sweep_parallel.py" "$SA" --max-procs 10 --omp 8 \
        || { echo "SWEEP FAILED: $SA"; rc=1; }
    echo "=== fill $SA ==="
    "$PY" "$CG/fill_grid.py" "$SA" --max-procs 10 --omp 8 \
        || echo "FILL FAILED (non-blocking): $SA"
    echo "=== refine $SA ==="
    "$PY" "$CG/refine.py" "$SA" --budget "$REFINE_BUDGET" --rounds "$REFINE_ROUNDS" \
        --scan-points "$REFINE_SCAN_POINTS" \
        || echo "REFINE FAILED (non-blocking): $SA"
done
echo "sweep task $SLURM_ARRAY_TASK_ID done (rc=$rc)"
exit $rc

#!/bin/bash
# Submit a full (rev, sim_mode) curve-generation campaign as a 3-stage Slurm
# pipeline: prep (seeds + beam caps) -> sweep (job array, one node per heavy
# subarray) -> collect+report, chained with --dependency=afterok.  Run from a
# LOGIN node (compute nodes cannot sbatch).
#
#   bash curvegen/submit_campaign.sh revF snapshot --time 24:00:00
#   bash curvegen/submit_campaign.sh revD track     --time 48:00:00
#   bash curvegen/submit_campaign.sh revD track     --prep-only   # QA gate first
#
# Env (NGVLA_REV / NGVLA_SIM_MODE / NGVLA_SCRATCH) is exported to EVERY stage:
# a Slurm dependency does NOT inherit the submitter's environment, so each
# sbatch gets it explicitly via --export.  Everything is resumable; re-running
# this script (or resubmitting a single stage) continues where it left off.
set -euo pipefail

REV=${1:-}; MODE=${2:-}
if [ -z "$REV" ] || [ -z "$MODE" ]; then
    echo "usage: submit_campaign.sh <rev> <sim_mode> [--time HH:MM:SS] [--prep-only]" >&2
    exit 2
fi
shift 2
WALL="48:00:00"; PREP_ONLY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --time) WALL=${2:?}; shift 2 ;;
        --prep-only) PREP_ONLY=1; shift ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy
ACCT="-A AST25010"      # TACC allocation (also in every .sbatch header)
export NGVLA_REV=$REV NGVLA_SIM_MODE=$MODE
export NGVLA_SCRATCH="${NGVLA_SCRATCH:-$SCRATCH/ngvla_curvegen}"
EXP="ALL,NGVLA_REV=$REV,NGVLA_SIM_MODE=$MODE,NGVLA_SCRATCH=$NGVLA_SCRATCH"

# guard: the combo must be registered and its metadata CSV must exist
"$PY" "$CG/campaign_tasks.py" narray >/dev/null || {
    echo "campaign_tasks failed -- is ($REV,$MODE) in config_registry.csv with a metadata CSV?" >&2
    exit 1; }
N=$("$PY" "$CG/campaign_tasks.py" narray)
echo "campaign $REV/$MODE : $N sweep array tasks, sweep walltime $WALL, scratch $NGVLA_SCRATCH"

prep=$(sbatch --parsable $ACCT --export="$EXP" "$CG/campaign_prep.sbatch")
echo "prep job:    $prep   (QA gate -- check prep_${prep}.log seed beams)"
if [ "$PREP_ONLY" -eq 1 ]; then
    echo "--prep-only: stopping.  After eyeballing prep, submit the rest with:"
    echo "  sweep=\$(sbatch --parsable $ACCT --dependency=afterok:$prep --array=0-$((N-1)) --time=$WALL --export=\"$EXP\" $CG/campaign_sweep.sbatch)"
    echo "  sbatch $ACCT --dependency=afterok:\$sweep --export=\"$EXP\" $CG/campaign_collect.sbatch"
    exit 0
fi

sweep=$(sbatch --parsable $ACCT --dependency=afterok:"$prep" --array=0-$((N-1)) \
        --time="$WALL" --export="$EXP" "$CG/campaign_sweep.sbatch")
echo "sweep array: $sweep  (0-$((N-1)))"
collect=$(sbatch --parsable $ACCT --dependency=afterok:"$sweep" \
          --export="$EXP" "$CG/campaign_collect.sbatch")
echo "collect job: $collect"
echo "submitted.  monitor: squeue -u $USER   |   cancel downstream: scancel $sweep $collect"

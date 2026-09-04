#!/bin/bash
# Submit the simulation/RSS half of the Ka MFS snapshot convergence pilot as
# one queue slot.  Defaults stop at nchan=128 so sm.corrupt memory is inspected
# before the explicitly requested 256/512 continuation.
set -euo pipefail

CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy
NCHAN_LIST="16:32:64:128"
WALL="04:00:00"
MAX_PROCS=4

while [ $# -gt 0 ]; do
    case "$1" in
        --nchan-list) NCHAN_LIST=${2:?}; shift 2 ;;
        --time) WALL=${2:?}; shift 2 ;;
        --max-procs) MAX_PROCS=${2:?}; shift 2 ;;
        *) echo "usage: $0 [--nchan-list 16:32:64:128] [--time HH:MM:SS] [--max-procs N]" >&2
           exit 2 ;;
    esac
done

case "$NCHAN_LIST" in ''|*[!0-9:]*)
    echo "--nchan-list must be colon-separated positive integers" >&2; exit 2 ;;
esac
case "$MAX_PROCS" in ''|*[!0-9]*)
    echo "--max-procs must be a positive integer" >&2; exit 2 ;;
esac
if [ "$MAX_PROCS" -lt 1 ]; then
    echo "--max-procs must be a positive integer" >&2; exit 2
fi

FIRST_NCHAN=${NCHAN_LIST%%:*}
export NGVLA_REV=revF NGVLA_SIM_MODE=snapshot NGVLA_BAND=band4
export NGVLA_NCHAN="$FIRST_NCHAN" NGVLA_CAMPAIGN_VARIANT=pilot-preflight
export NGVLA_NOISE_POLICY=equal
export NGVLA_SCRATCH="${NGVLA_SCRATCH:-$SCRATCH/ngvla_curvegen}"
# Pilot MSes are disposable and intentionally scratch-first.  Override only
# when a different large-filesystem base is explicitly desired.
export NGVLA_MS_BASE="${NGVLA_MFS_MS_BASE:-$SCRATCH/ngvla_curvegen}"

"$PY" -c "import sys; sys.path.insert(0, '$CG'); import config as c; print('preflight:', c.REV, c.SIM_MODE, c.BAND, c.NCHAN, c.MS_DIR)"

EXP="ALL,NGVLA_REV=revF,NGVLA_SIM_MODE=snapshot,NGVLA_BAND=band4,NGVLA_NOISE_POLICY=equal,NGVLA_NCHAN_LIST=$NCHAN_LIST,NGVLA_MFS_SIM_MAX_PROCS=$MAX_PROCS,NGVLA_SCRATCH=$NGVLA_SCRATCH,NGVLA_MS_BASE=$NGVLA_MS_BASE"
OUT=$(sbatch --parsable -A AST25010 --time="$WALL" --export="$EXP" \
      "$CG/mfs_snapshot_sim_pilot.sbatch")
JOB_ID=$(printf '%s\n' "$OUT" | grep -oE '^[0-9]+' | tail -n1)
if [ -z "$JOB_ID" ]; then
    echo "could not parse a job id from sbatch output:" >&2
    printf '%s\n' "$OUT" >&2
    exit 1
fi
echo "submitted MFS snapshot simulation pilot job $JOB_ID"
echo "nchan: ${NCHAN_LIST//:/,}; monitor: squeue -u $USER"

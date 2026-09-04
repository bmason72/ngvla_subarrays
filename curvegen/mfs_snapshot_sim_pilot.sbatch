#!/bin/bash
#SBATCH -J ngvla_mfs_snap_sim
#SBATCH -A AST25010
#SBATCH -o /work2/10240/bmason72/stampede3/mfs_snapshot_sim_%j.log
#SBATCH -p icx
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 80
#SBATCH --hint=nomultithread
#SBATCH -t 04:00:00

# Simulation-only Ka MFS snapshot nchan/RSS pilot.  This intentionally does
# not run tclean, adaptive sampling, collection, or reporting.  Each nchan is
# routed through an isolated campaign variant, so its immutable manifest and
# MS cannot collide with another pilot or prematurely pin production nchan.
set -u
CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy
: "${NGVLA_NCHAN_LIST:?submit with submit_mfs_snapshot_sim_pilot.sh}"
: "${NGVLA_MS_BASE:?submit with submit_mfs_snapshot_sim_pilot.sh}"
: "${NGVLA_SCRATCH:?submit with submit_mfs_snapshot_sim_pilot.sh}"

export NGVLA_REV=revF NGVLA_SIM_MODE=snapshot NGVLA_BAND=band4
export NGVLA_NOISE_POLICY=equal
MAX_PROCS="${NGVLA_MFS_SIM_MAX_PROCS:-4}"
case "$MAX_PROCS" in ''|*[!0-9]*)
    echo "NGVLA_MFS_SIM_MAX_PROCS must be a positive integer" >&2; exit 2 ;;
esac
if [ "$MAX_PROCS" -lt 1 ]; then
    echo "NGVLA_MFS_SIM_MAX_PROCS must be a positive integer" >&2; exit 2
fi

NCHAN_VALUES=${NGVLA_NCHAN_LIST//:/ }
for NCHAN_VALUE in $NCHAN_VALUES; do
    case "$NCHAN_VALUE" in ''|*[!0-9]*)
        echo "invalid nchan in NGVLA_NCHAN_LIST: $NCHAN_VALUE" >&2; exit 2 ;;
    esac
    if [ "$NCHAN_VALUE" -lt 1 ]; then
        echo "nchan must be positive: $NCHAN_VALUE" >&2; exit 2
    fi
done

mkdir -p "$NGVLA_MS_BASE" "$NGVLA_SCRATCH"

# Geometry is channel-independent and variants deliberately share CFG_DIR.
# Build it once under any valid pilot nchan before parallel simulator starts.
set -- $NCHAN_VALUES
export NGVLA_NCHAN="$1"
unset NGVLA_CAMPAIGN_VARIANT
"$PY" "$CG/build_configs.py" \
    || { echo "MFS snapshot pilot: build_configs FAILED" >&2; exit 1; }

rc=0
active=0
pids=()
labels=()

stop_children() {
    local pid
    echo "stopping active MFS snapshot simulators" >&2
    for pid in "${pids[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait || true
    exit 130
}
trap stop_children INT TERM

wait_batch() {
    local index pid
    for index in "${!pids[@]}"; do
        pid=${pids[$index]}
        if ! wait "$pid"; then
            echo "FAILED: ${labels[$index]} (see its log)" >&2
            rc=1
        fi
    done
    pids=()
    labels=()
    active=0
}

for NCHAN_VALUE in $NCHAN_VALUES; do
    VARIANT=$(printf 'pilot-nchan%03d-equal' "$NCHAN_VALUE")
    for SA in core main; do
        SAFE_SA=${SA//+/_}
        RUN_CWD="$NGVLA_SCRATCH/mfs_snapshot_sim_pilot/$VARIANT/$SAFE_SA"
        LOG="/work2/10240/bmason72/stampede3/mfs_snapshot_sim_${SLURM_JOB_ID:-manual}_${VARIANT}_${SAFE_SA}.log"
        mkdir -p "$RUN_CWD"
        echo "launching $SA nchan=$NCHAN_VALUE variant=$VARIANT -> $LOG"
        (
            export NGVLA_NCHAN="$NCHAN_VALUE"
            export NGVLA_CAMPAIGN_VARIANT="$VARIANT"
            export OMP_NUM_THREADS=8
            cd "$RUN_CWD"
            /usr/bin/time -v "$PY" "$CG/simulate.py" "$SA"
        ) >"$LOG" 2>&1 &
        pids+=("$!")
        labels+=("$SA nchan=$NCHAN_VALUE")
        active=$((active + 1))
        if [ "$active" -ge "$MAX_PROCS" ]; then
            wait_batch
        fi
    done
done
if [ "$active" -gt 0 ]; then
    wait_batch
fi

if [ "$rc" -ne 0 ]; then
    echo "MFS snapshot simulation pilot completed with failures" >&2
    exit "$rc"
fi
echo "MFS snapshot simulation pilot complete: core/main for nchan ${NGVLA_NCHAN_LIST//:/,}"
echo "Inspect per-run logs for 'Maximum resident set size' before adding nchan 256/512."

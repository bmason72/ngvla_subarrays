#!/bin/bash
#SBATCH -J ngvla_mfs_img_pilot
#SBATCH -A AST25010
#SBATCH -o /work2/10240/bmason72/stampede3/mfs_imaging_pilot_%j.log
#SBATCH -p icx
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 80
#SBATCH --hint=nomultithread
#SBATCH -t 04:00:00

# Imaging half of the Ka MFS-band4 nchan/RSS pilot (docs/plans/mfs-imaging-pilot-spec.md):
# seeds -> pilot points -> points-file sweep -> nchan-convergence compare (>=2
# nchan variants) or a timing-only cost benchmark (1 variant).  Each nchan is
# an isolated campaign variant sharing geometry (CFG_DIR) but never colliding
# on manifest/results/MS -- the same isolation the simulation-only pilot uses
# (mfs_snapshot_sim_pilot.sbatch), extended with the tclean/imaging phases
# that one deliberately did not run.  This job does everything sweep.py
# needs, INCLUDING re-simulating a missing MS (so it also works standalone
# for NGVLA_SIM_MODE=track, which the sim-only pilot never simulated).
set -u
CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy
: "${NGVLA_NCHAN_LIST:?submit with submit_mfs_imaging_pilot.sh}"
: "${NGVLA_SIM_MODE:?submit with submit_mfs_imaging_pilot.sh}"
: "${NGVLA_MS_BASE:?submit with submit_mfs_imaging_pilot.sh}"
: "${NGVLA_SCRATCH:?submit with submit_mfs_imaging_pilot.sh}"

export NGVLA_REV=revF NGVLA_BAND=band4
export NGVLA_NOISE_POLICY=equal
MAX_PROCS="${NGVLA_MFS_IMG_MAX_PROCS:-4}"
SA_LIST="${NGVLA_MFS_IMG_SUBARRAYS:-core:main}"
case "$MAX_PROCS" in ''|*[!0-9]*)
    echo "NGVLA_MFS_IMG_MAX_PROCS must be a positive integer" >&2; exit 2 ;;
esac
if [ "$MAX_PROCS" -lt 1 ]; then
    echo "NGVLA_MFS_IMG_MAX_PROCS must be a positive integer" >&2; exit 2
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
SUBARRAYS=${SA_LIST//:/ }

mkdir -p "$NGVLA_MS_BASE" "$NGVLA_SCRATCH"
JOBID="${SLURM_JOB_ID:-manual}"
LOGBASE="/work2/10240/bmason72/stampede3/mfs_imaging_pilot_${JOBID}"

variant_of() { printf 'pilot-nchan%03d-equal' "$1"; }

set -- $NCHAN_VALUES
FIRST_NCHAN="$1"
FIRST_VARIANT=$(variant_of "$FIRST_NCHAN")

# ---- phase 0: build configs once (geometry is channel-independent) --------
export NGVLA_NCHAN="$FIRST_NCHAN"
unset NGVLA_CAMPAIGN_VARIANT
"$PY" "$CG/build_configs.py" \
    || { echo "MFS imaging pilot: build_configs FAILED" >&2; exit 1; }

rc=0
active=0
pids=()
labels=()

stop_children() {
    local pid
    echo "stopping active MFS imaging pilot tasks" >&2
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

# ---- phase 1: seeds-only per (variant, subarray) ---------------------------
# creates the MS if missing, so this launcher also works for track mode.
for NCHAN_VALUE in $NCHAN_VALUES; do
    VARIANT=$(variant_of "$NCHAN_VALUE")
    for SA in $SUBARRAYS; do
        SAFE_SA=${SA//+/_}
        RUN_CWD="$NGVLA_SCRATCH/mfs_imaging_pilot/$VARIANT/$SAFE_SA/seeds"
        LOG="${LOGBASE}_${VARIANT}_${SAFE_SA}_seeds.log"
        mkdir -p "$RUN_CWD"
        echo "launching $SA nchan=$NCHAN_VALUE seeds -> $LOG"
        (
            export NGVLA_NCHAN="$NCHAN_VALUE"
            export NGVLA_CAMPAIGN_VARIANT="$VARIANT"
            export OMP_NUM_THREADS=$((80 / MAX_PROCS))
            cd "$RUN_CWD"
            /usr/bin/time -v "$PY" "$CG/sweep.py" "$SA" --seeds-only
        ) >"$LOG" 2>&1 &
        pids+=("$!")
        labels+=("$SA nchan=$NCHAN_VALUE seeds")
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
    echo "MFS imaging pilot: phase 1 (seeds) FAILED -- stopping before points/sweep" >&2
    exit 1
fi

# ---- phase 2: pilot points per subarray, under the FIRST variant's env -----
POINTS_DIR="$NGVLA_SCRATCH/mfs_imaging_pilot"
mkdir -p "$POINTS_DIR"
export NGVLA_NCHAN="$FIRST_NCHAN"
export NGVLA_CAMPAIGN_VARIANT="$FIRST_VARIANT"
for SA in $SUBARRAYS; do
    SAFE_SA=${SA//+/_}
    LOG="${LOGBASE}_${FIRST_VARIANT}_${SAFE_SA}_points.log"
    echo "generating pilot points for $SA (reference $FIRST_VARIANT) -> $LOG"
    "$PY" "$CG/mfs_pilot_points.py" "$SA" \
        --out "$POINTS_DIR/points_${SAFE_SA}.json" >"$LOG" 2>&1
    if [ $? -ne 0 ]; then
        echo "FAILED: pilot points for $SA (see $LOG)" >&2
        rc=1
    fi
done
unset NGVLA_CAMPAIGN_VARIANT

if [ "$rc" -ne 0 ]; then
    echo "MFS imaging pilot: phase 2 (pilot points) FAILED -- stopping before sweep" >&2
    exit 1
fi

# ---- phase 3: points-file sweep per (variant, subarray) --------------------
for NCHAN_VALUE in $NCHAN_VALUES; do
    VARIANT=$(variant_of "$NCHAN_VALUE")
    for SA in $SUBARRAYS; do
        SAFE_SA=${SA//+/_}
        RUN_CWD="$NGVLA_SCRATCH/mfs_imaging_pilot/$VARIANT/$SAFE_SA/sweep"
        LOG="${LOGBASE}_${VARIANT}_${SAFE_SA}_sweep.log"
        POINTS_FILE="$POINTS_DIR/points_${SAFE_SA}.json"
        mkdir -p "$RUN_CWD"
        echo "launching $SA nchan=$NCHAN_VALUE sweep -> $LOG"
        (
            export NGVLA_NCHAN="$NCHAN_VALUE"
            export NGVLA_CAMPAIGN_VARIANT="$VARIANT"
            export OMP_NUM_THREADS=$((80 / MAX_PROCS))
            cd "$RUN_CWD"
            /usr/bin/time -v "$PY" "$CG/sweep.py" "$SA" \
                --points-file "$POINTS_FILE"
        ) >"$LOG" 2>&1 &
        pids+=("$!")
        labels+=("$SA nchan=$NCHAN_VALUE sweep")
        active=$((active + 1))
        if [ "$active" -ge "$MAX_PROCS" ]; then
            wait_batch
        fi
    done
done
if [ "$active" -gt 0 ]; then
    wait_batch
fi

sweep_rc=$rc
if [ "$sweep_rc" -ne 0 ]; then
    echo "MFS imaging pilot: one or more sweeps FAILED (see logs above) -- " \
         "still running the comparison/timing report for whatever data exists" >&2
fi

# ---- phase 4: nchan convergence compare, or timing-only cost benchmark ----
compare_rc=0
set -- $NCHAN_VALUES
REF_DIR="$CG/results-revF_${NGVLA_SIM_MODE}_band4_${FIRST_VARIANT}"
if [ "$#" -ge 2 ]; then
    shift
    for NCHAN_VALUE in "$@"; do
        VARIANT=$(variant_of "$NCHAN_VALUE")
        OTHER_DIR="$CG/results-revF_${NGVLA_SIM_MODE}_band4_${VARIANT}"
        REPORT="$OTHER_DIR/nchan_convergence_vs_${FIRST_VARIANT}.md"
        echo "comparing $FIRST_VARIANT vs $VARIANT -> $REPORT"
        "$PY" "$CG/mfs_pilot_compare.py" --ref "$REF_DIR" --other "$OTHER_DIR" \
            --subarrays $SUBARRAYS --out "$REPORT"
        this_rc=$?
        if [ "$this_rc" -eq 3 ]; then
            compare_rc=3
        elif [ "$this_rc" -ne 0 ] && [ "$compare_rc" -ne 3 ]; then
            compare_rc=$this_rc
        fi
        echo "---- $REPORT ----"
        cat "$REPORT" 2>/dev/null || echo "(no report written)"
    done
else
    REPORT="$REF_DIR/timing_${NGVLA_SIM_MODE}.md"
    echo "single variant $FIRST_VARIANT -- timing-only cost benchmark -> $REPORT"
    "$PY" "$CG/mfs_pilot_compare.py" --ref "$REF_DIR" \
        --subarrays $SUBARRAYS --out "$REPORT"
    compare_rc=$?
    echo "---- $REPORT ----"
    cat "$REPORT" 2>/dev/null || echo "(no report written)"
fi

# Compare failures must never mask sweep failures: a sweep failure is always
# reported and always non-zero, regardless of what the comparison found; a
# clean sweep with only the convergence criteria failing exits 3 specifically
# (distinguishable from other failure modes by callers/CI).
if [ "$sweep_rc" -ne 0 ]; then
    echo "MFS imaging pilot completed with SWEEP FAILURES (see logs above)" >&2
    exit 1
fi
if [ "$compare_rc" -eq 3 ]; then
    echo "MFS imaging pilot: sweeps OK but nchan convergence criteria FAILED" >&2
    exit 3
fi
if [ "$compare_rc" -ne 0 ]; then
    echo "MFS imaging pilot: compare tool usage/data error (rc=$compare_rc)" >&2
    exit "$compare_rc"
fi
echo "MFS imaging pilot complete: sim_mode=$NGVLA_SIM_MODE" \
     "nchan=${NGVLA_NCHAN_LIST//:/,} subarrays=${SA_LIST//:/,}"

#!/bin/bash
# Submit the imaging half of the Ka MFS-band4 nchan/RSS pilot as one queue
# slot: seeds -> pilot points -> points-file sweep -> nchan-convergence
# compare (>=2 --nchan-list values) or a timing-only cost benchmark (1
# value).  Mirrors submit_mfs_snapshot_sim_pilot.sh's env plumbing.  Run from
# a LOGIN node (compute nodes cannot sbatch).
#
#   bash submit_mfs_imaging_pilot.sh                                  # snapshot 27:54 convergence
#   bash submit_mfs_imaging_pilot.sh --sim-mode track --nchan-list 27  # track 27 cost benchmark
#   bash submit_mfs_imaging_pilot.sh --dry-run                        # print the sbatch command only
set -euo pipefail

CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy
SIM_MODE="snapshot"
NCHAN_LIST="27:54"
WALL=""
MAX_PROCS=4
SA_LIST="core:main"
DRY_RUN=0

usage() {
    echo "usage: $0 [--sim-mode snapshot|track] [--nchan-list 27:54] " \
         "[--time HH:MM:SS] [--max-procs N] [--subarrays core:main] [--dry-run]" >&2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --sim-mode) SIM_MODE=${2:?}; shift 2 ;;
        --nchan-list) NCHAN_LIST=${2:?}; shift 2 ;;
        --time) WALL=${2:?}; shift 2 ;;
        --max-procs) MAX_PROCS=${2:?}; shift 2 ;;
        --subarrays) SA_LIST=${2:?}; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        *) usage; exit 2 ;;
    esac
done

case "$SIM_MODE" in
    snapshot|track) ;;
    *) echo "--sim-mode must be snapshot or track" >&2; exit 2 ;;
esac
case "$NCHAN_LIST" in ''|*[!0-9:]*)
    echo "--nchan-list must be colon-separated positive integers" >&2; exit 2 ;;
esac
case "$MAX_PROCS" in ''|*[!0-9]*)
    echo "--max-procs must be a positive integer" >&2; exit 2 ;;
esac
if [ "$MAX_PROCS" -lt 1 ]; then
    echo "--max-procs must be a positive integer" >&2; exit 2
fi
case "$SA_LIST" in ''|*[!a-z0-9:+-]*)
    echo "--subarrays must be colon-separated lowercase subarray names" >&2; exit 2 ;;
esac

if [ -z "$WALL" ]; then
    if [ "$SIM_MODE" = "track" ]; then WALL="08:00:00"; else WALL="04:00:00"; fi
fi

FIRST_NCHAN=${NCHAN_LIST%%:*}
export NGVLA_REV=revF NGVLA_SIM_MODE="$SIM_MODE" NGVLA_BAND=band4
export NGVLA_NOISE_POLICY=equal
export NGVLA_NCHAN="$FIRST_NCHAN"
export NGVLA_CAMPAIGN_VARIANT=$(printf 'pilot-nchan%03d-equal' "$FIRST_NCHAN")
export NGVLA_SCRATCH="${NGVLA_SCRATCH:-$SCRATCH/ngvla_curvegen}"
# Pilot MSes are disposable and intentionally scratch-first, exactly like the
# simulation-only pilot -- this reuses the MSes that pilot already created.
export NGVLA_MS_BASE="${NGVLA_MFS_MS_BASE:-$SCRATCH/ngvla_curvegen}"

"$PY" -c "import sys; sys.path.insert(0, '$CG'); import config as c; print('preflight:', c.REV, c.SIM_MODE, c.BAND, c.NCHAN, c.MS_DIR, c.RESULTS_DIR)"

EXP="ALL,NGVLA_REV=revF,NGVLA_SIM_MODE=$SIM_MODE,NGVLA_BAND=band4,NGVLA_NOISE_POLICY=equal,NGVLA_NCHAN_LIST=$NCHAN_LIST,NGVLA_MFS_IMG_MAX_PROCS=$MAX_PROCS,NGVLA_MFS_IMG_SUBARRAYS=$SA_LIST,NGVLA_SCRATCH=$NGVLA_SCRATCH,NGVLA_MS_BASE=$NGVLA_MS_BASE"

CMD=(sbatch --parsable -A AST25010 --time="$WALL" --export="$EXP" \
     "$CG/mfs_imaging_pilot.sbatch")

if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY RUN -- would submit:"
    printf '%q ' "${CMD[@]}"
    echo
    echo "sim_mode=$SIM_MODE nchan_list=$NCHAN_LIST subarrays=$SA_LIST" \
         "max_procs=$MAX_PROCS wall=$WALL"
    exit 0
fi

OUT=$("${CMD[@]}")
JOB_ID=$(printf '%s\n' "$OUT" | grep -oE '^[0-9]+' | tail -n1)
if [ -z "$JOB_ID" ]; then
    echo "could not parse a job id from sbatch output:" >&2
    printf '%s\n' "$OUT" >&2
    exit 1
fi
echo "submitted MFS imaging pilot job $JOB_ID"
echo "sim_mode: $SIM_MODE; nchan: ${NCHAN_LIST//:/,}; subarrays: ${SA_LIST//:/,}; monitor: squeue -u $USER"

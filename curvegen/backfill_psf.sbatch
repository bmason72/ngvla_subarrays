#!/bin/bash
#SBATCH -J ngvla_backfill
#SBATCH -A AST25010
#SBATCH -o /work2/10240/bmason72/stampede3/backfill_%A_%a.log
#SBATCH -p icx
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 47:00:00
# ^ walltime CEILING per array task.  Backfill is resumable (cut-bearing
#   anchors are skipped), so a task that hits the limit continues on resubmit.
#   Scale note (21 Jul dry-run): revF/track alone has ~949 anchors to image
#   (it predates profile capture), so expect the odd resubmit for task 0.

# PSF INSPECTOR P2: ANCHOR BACKFILL.  A Slurm JOB ARRAY (0-3), one task per
# (rev, sim_mode) campaign combo, that gives every DISPLAYED-curve anchor point
# a PSF profile line WITH major/minor-axis cuts by re-imaging the anchors that
# lack one.  It NEVER writes curve data -- the results CSVs are byte-identical
# after a run; only results<suffix>/profiles/*.jsonl gains appended cut-bearing
# lines -- then the lazy-load PSF payloads are re-exported for that combo.
#
# Submit from a LOGIN node (compute nodes cannot sbatch):
#   sbatch --array=0-3 curvegen/backfill_psf.sbatch
#   sbatch --array=0   curvegen/backfill_psf.sbatch   # just revF/track
set -u
CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy

# array index -> combo.  MUST stay in step with sa_select/data/config_registry.csv
# (the campaign sbatches instead get the combo from submit_campaign.sh; here one
# array covers all four, so the mapping is listed explicitly).
COMBOS=("revF track" "revF snapshot" "revD track" "revD snapshot" "revC track")
SEL="${COMBOS[${SLURM_ARRAY_TASK_ID:-0}]:-}"
if [ -z "$SEL" ]; then
    echo "no combo for array index ${SLURM_ARRAY_TASK_ID:-0} -- nothing to do"
    exit 0
fi
set -- $SEL
export NGVLA_REV="$1" NGVLA_SIM_MODE="$2"
export NGVLA_SCRATCH="${NGVLA_SCRATCH:-$SCRATCH/ngvla_curvegen}"
export NGVLA_MS_BASE="${NGVLA_MS_BASE:-$WORK/ngvla_curvegen}"
mkdir -p "$NGVLA_MS_BASE" "$NGVLA_SCRATCH"
# CASA writes multi-GB TempLattice* images to the process cwd, which Slurm
# inherits from the SUBMISSION directory -- pin it to scratch so submitting from
# $HOME/the repo can never blow the 14 GB home quota (see campaign_sweep.sbatch;
# the 15 Jul 2026 polish core-dumped exactly this way, "Disk quota exceeded").
RUN_CWD="$NGVLA_SCRATCH/run_${SLURM_JOB_ID:-manual}${SLURM_ARRAY_TASK_ID:+_$SLURM_ARRAY_TASK_ID}"
mkdir -p "$RUN_CWD"; cd "$RUN_CWD"

echo "=== BACKFILL  rev=$NGVLA_REV  mode=$NGVLA_SIM_MODE  (cwd $RUN_CWD) ==="
"$PY" "$CG/backfill_psf.py" \
    || { echo "BACKFILL FAILED: $NGVLA_REV/$NGVLA_SIM_MODE"; exit 1; }

# refresh this combo's lazy-load PSF payloads (non-blocking, like
# campaign_collect.sbatch's export step) so the report picks up the new
# cut-bearing lines
"$PY" "$CG/export_psf_data.py" --rev "$NGVLA_REV" --sim-mode "$NGVLA_SIM_MODE" \
    --band "${NGVLA_BAND:-}" \
    || echo "PSF EXPORT FAILED (non-blocking)"
echo "backfill task ${SLURM_ARRAY_TASK_ID:-0} done -> $NGVLA_REV/$NGVLA_SIM_MODE"

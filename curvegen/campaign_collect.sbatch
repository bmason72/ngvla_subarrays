#!/bin/bash
#SBATCH -J ngvla_collect
#SBATCH -A AST25010
#SBATCH -o /work2/10240/bmason72/stampede3/collect_%j.log
#SBATCH -p icx
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 02:00:00

# CAMPAIGN COLLECT + REPORT (stage 3 of 3).  Routes this combo's sweep results
# into its registered curve CSV and builds its own HTML report.  Depends
# (afterok) on the whole sweep array.  Both collect.py and make_report.py read
# the (rev, sim_mode) from the environment, so the output lands where
# CurveLibrary.for_config(rev, sim_mode) will look for it.
set -u
CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy
: "${NGVLA_REV:?export NGVLA_REV (use submit_campaign.sh)}"
: "${NGVLA_SIM_MODE:?export NGVLA_SIM_MODE (use submit_campaign.sh)}"
export NGVLA_SCRATCH="${NGVLA_SCRATCH:-$SCRATCH/ngvla_curvegen}"
export NGVLA_MS_BASE="${NGVLA_MS_BASE:-$WORK/ngvla_curvegen}"
mkdir -p "$NGVLA_MS_BASE"
mkdir -p "$CG/reports"
# pin cwd to scratch (CASA droppings land in the cwd; never the submit dir)
RUN_CWD="$NGVLA_SCRATCH/run_${SLURM_JOB_ID:-manual}"
mkdir -p "$RUN_CWD"; cd "$RUN_CWD"

echo "=== COLLECT + REPORT  rev=$NGVLA_REV  mode=$NGVLA_SIM_MODE ==="
"$PY" "$CG/collect.py" || { echo "COLLECT FAILED"; exit 1; }

REPORT="$CG/reports/${NGVLA_REV}-${NGVLA_SIM_MODE}-curves.html"
"$PY" "$CG/make_report.py" "$REPORT" \
    --rev "$NGVLA_REV" --sim-mode "$NGVLA_SIM_MODE" \
    || { echo "REPORT FAILED"; exit 1; }
echo "collect + report done -> $REPORT"

"$PY" "$CG/export_psf_data.py" || echo "PSF EXPORT FAILED (non-blocking)"

# the flagship all-campaigns report (campaign dropdown): rebuild it from every
# registered combo's committed curve CSVs so it always reflects the newest data
"$PY" "$CG/make_report.py" --combined "$CG/reports/ngvla-curves.html" \
    || echo "COMBINED REPORT FAILED (per-combo report above still valid)"
echo "commit the routed curve CSV (+ updated caps in the metadata CSV) when happy."

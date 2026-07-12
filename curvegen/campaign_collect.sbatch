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
mkdir -p "$CG/reports"

echo "=== COLLECT + REPORT  rev=$NGVLA_REV  mode=$NGVLA_SIM_MODE ==="
"$PY" "$CG/collect.py" || { echo "COLLECT FAILED"; exit 1; }

REPORT="$CG/reports/${NGVLA_REV}-${NGVLA_SIM_MODE}-curves.html"
"$PY" "$CG/make_report.py" "$REPORT" \
    --rev "$NGVLA_REV" --sim-mode "$NGVLA_SIM_MODE" \
    || { echo "REPORT FAILED"; exit 1; }
echo "collect + report done -> $REPORT"
echo "commit the routed curve CSV (+ updated caps in the metadata CSV) when happy."

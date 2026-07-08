#!/bin/bash
#SBATCH -J ngvla_refine
#SBATCH -o /work2/10240/bmason72/stampede3/refine_%j.log
#SBATCH -p icx
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 12:00:00

# Adaptive refinement of the memo-121 long+outer-core campaign imaging curves
# (7 Jul 2026).  refine.py measures a handful of bracketing (robust, taper)
# PSF points wherever the sculpted curve jumps > --max-step in eta between
# adjacent resolutions, on top of the resumable sweep results.  It is a no-op
# where the curve is already smooth (long, mid+long, spiral+core-outer,
# mid+spiral+core-outer, long+mid+spiral+core-outer are all < 0.25 today);
# the real work is main+long (worst step 0.91) and spiral+mid+long (0.50),
# whose fine-end imaging curves step across relaxation<->trade-cap transitions.
#
# Resumable: refined points are appended to results/<sa>.csv and skipped on
# re-runs.  refine.py runs Sweep in-process (serial), and unlike
# sweep_parallel.py it does NOT chdir to scratch itself -- so we cd into a
# per-subarray scratch dir first, or CASA writes multi-GB TempLattice* files to
# $HOME and blows the 14 GB quota (see PLAN.md sec.13 / casaLocation.md).
# Sweep.ensure_ready() re-simulates the MS if scratch was purged, so this is
# self-contained.  Must be submitted from a LOGIN node (compute nodes cannot
# sbatch).

set -u
CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy
export OMP_NUM_THREADS=16          # serial refine -> give tclean more threads

if [ -z "${SCRATCH:-}" ]; then
    echo "ERROR: \$SCRATCH is not set; refusing to run CASA from \$HOME" >&2
    exit 1
fi

for SA in long mid+long spiral+mid+long main+long \
          spiral+core-outer mid+spiral+core-outer long+mid+spiral+core-outer; do
    RUN=$SCRATCH/ngvla_curvegen/run_$(echo "$SA" | tr '+-' '__')_refine
    mkdir -p "$RUN"
    echo "=== refine $SA (cwd $RUN) ==="
    ( cd "$RUN" && "$PY" "$CG/refine.py" "$SA" --rounds 3 --max-step 0.25 --budget 60 ) \
        || echo "REFINE FAILED: $SA"
done

# regenerate the collected curve data + HTML report from the refined sweeps
# (pure Python, no CASA tclean, so cwd does not matter)
echo "=== collect + report ==="
"$PY" "$CG/collect.py"                        || echo "COLLECT FAILED"
"$PY" "$CG/make_report.py" "$CG/reports/revf-curves.html" || echo "REPORT FAILED"
echo "refine job done"

#!/bin/bash
#SBATCH -J ngvla_recompute
#SBATCH -o /work2/10240/bmason72/stampede3/recompute_%j.log
#SBATCH -p icx
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 12:00:00
# ^ walltime CEILING (safety), NOT the estimate.  Expected ~4-6 h: the 10
#   non-uvrange subarrays only backfill ~34 stripped cells each (fast); the
#   cost is the 3 imsize-15000 uvrange subarrays, which must be FULLY re-imaged
#   because the >178 m filter changes every measurement.  Resumable, so a
#   re-submit continues if it ever hits the limit.

# Full-grid + spurious-shorts recompute campaign (bmason 8 Jul 2026:
# items 1 + 6a + 3).  Submit from a LOGIN node (compute nodes cannot sbatch).
#
#   1. prep: archive the uvrange subarrays' stale CSVs and strip the (now
#      removed) eta-cap/convergence 'skipped' rows from the others, so the
#      full-grid sweep re-measures every cell without stale contamination.
#   2. full-grid sweep of every offered subarray (sweep_parallel shards Briggs
#      rows, --max-procs 10 x --omp 8 ~= the 80-core icx node); the 4 uvrange
#      subarrays re-image with uvrange>178 m (sweep.py reads MIN_UVRANGE_M);
#      fill_grid tops up any cheap cells.
#   3. refine all offered subarrays, run CONCURRENTLY (refine_parallel).
#   4. collect -> revf_curves.csv, regenerate the HTML report.
# Everything is resumable; a re-submit continues where it left off (prep is
# idempotent).

set -u
CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy
if [ -z "${SCRATCH:-}" ]; then
    echo "ERROR: \$SCRATCH not set" >&2; exit 1
fi

echo "=== prep_recompute (archive uvrange + strip pruned skips) ==="
"$PY" "$CG/prep_recompute.py" || { echo "PREP FAILED"; exit 1; }

OFFERED="core-inner core spiral mid core+spiral spiral+mid main \
long mid+long spiral+mid+long main+long spiral+core-outer \
mid+spiral+core-outer long+mid+spiral+core-outer"
for SA in $OFFERED; do
    echo "=== sweep $SA ==="
    "$PY" "$CG/sweep_parallel.py" "$SA" --max-procs 10 --omp 8 \
        || echo "SWEEP FAILED: $SA"
    echo "=== fill $SA ==="
    "$PY" "$CG/fill_grid.py" "$SA" --max-procs 10 --omp 8 \
        || echo "FILL FAILED: $SA"
done

echo "=== refine (subarrays concurrent) ==="
"$PY" "$CG/refine_parallel.py" --all-offered --max-procs 4 --omp 8 \
    || echo "REFINE PARALLEL FAILED"

echo "=== collect + report ==="
"$PY" "$CG/collect.py"                                   || echo "COLLECT FAILED"
"$PY" "$CG/make_report.py" "$CG/reports/revf-curves.html" || echo "REPORT FAILED"
echo "recompute done"

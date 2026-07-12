#!/bin/bash
#SBATCH -J ngvla_campaign
#SBATCH -A AST25010
#SBATCH -o /work2/10240/bmason72/stampede3/campaign_%j.log
#SBATCH -p icx
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 24:00:00

# memo-121 campaign: heavy long-baseline lattices (7 Jul 2026).
# Each subarray: parallel row sweep, then cheap-cell fill.  All resumable.
CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy
for SA in mid+long spiral+mid+long main+long long+mid+spiral+core-outer; do
    echo "=== $SA sweep ==="
    $PY $CG/sweep_parallel.py "$SA" --max-procs 8 --omp 8 || echo "SWEEP FAILED: $SA"
    echo "=== $SA fill ==="
    $PY $CG/fill_grid.py "$SA" --max-procs 8 --omp 8 || echo "FILL FAILED: $SA"
done
echo "campaign job done"

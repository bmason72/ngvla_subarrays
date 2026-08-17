#!/bin/bash
#SBATCH -J ngvla_regen_ms
#SBATCH -A AST25010
#SBATCH -o /work2/10240/bmason72/stampede3/regen_ms_%A_%a.log
#SBATCH -p icx
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 12:00:00

# MS REGENERATION (insurance / post-purge recovery; 15 Jul 2026).  One job-
# array task per registered (rev, sim_mode) combo re-simulates every offered
# subarray MS that is missing from the persistent MS store (NGVLA_MS_BASE,
# default $WORK/ngvla_curvegen; the default revF/track combo resolves through
# the repo's curvegen/ms symlink).  make_ms skips MSes that already exist, so
# this is idempotent and safe to run any time:
#
#   sbatch --array=0-3 $HOME/Code/ngvla_subarrays/curvegen/regen_ms.sbatch
#
# A full rebuild from nothing costs a few node-hours (sims are minutes per
# subarray; the tclean sweep results themselves live in the git repo and
# never need regenerating).
set -u
CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy

COMBOS=("revF track" "revF snapshot" "revD track" "revD snapshot" "revC track")
read -r REV MODE <<< "${COMBOS[$SLURM_ARRAY_TASK_ID]}"
export NGVLA_REV=$REV NGVLA_SIM_MODE=$MODE
export NGVLA_SCRATCH="${NGVLA_SCRATCH:-$SCRATCH/ngvla_curvegen}"
export NGVLA_MS_BASE="${NGVLA_MS_BASE:-$WORK/ngvla_curvegen}"
mkdir -p "$NGVLA_MS_BASE" "$NGVLA_SCRATCH"
echo "=== REGEN MS  rev=$REV mode=$MODE ==="

# cfg files are cheap and idempotent; make sure this combo's exist
"$PY" "$CG/build_configs.py" || { echo "REGEN: build_configs FAILED"; exit 1; }

# CASA scratch products (TempLattice*, casa logs) land in the cwd: keep it on
# scratch, never $HOME (quota) and never the MS store
cd "$NGVLA_SCRATCH"
PYTHONPATH=$CG "$PY" - <<'EOF'
from config import SUBARRAYS, MS_DIR, REV, SIM_MODE
from simulate import make_ms

print("regenerating MSes for (%s, %s) -> %s" % (REV, SIM_MODE, MS_DIR))
failed = []
for sa in sorted(SUBARRAYS):
    print("== make_ms %s" % sa, flush=True)
    try:
        make_ms(sa)
    except Exception as e:
        failed.append(sa)
        print("FAILED %s: %s" % (sa, e), flush=True)
if failed:
    raise SystemExit("regen incomplete, failed: %s" % ", ".join(failed))
print("all MSes present")
EOF
rc=$?
echo "regen task $SLURM_ARRAY_TASK_ID done (rc=$rc)"
exit $rc

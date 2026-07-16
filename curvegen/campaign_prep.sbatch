#!/bin/bash
#SBATCH -J ngvla_prep
#SBATCH -A AST25010
#SBATCH -o /work2/10240/bmason72/stampede3/prep_%j.log
#SBATCH -p icx
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 06:00:00
# ^ walltime CEILING.  Prep is cheap: 2 seeds + a 4-point pilot per subarray.
#   snapshot seeds are tiny-MS fast; the cost is the imsize-15000 track seeds.
#   Resumable -- a resubmit continues.

# CAMPAIGN PREP (stage 1 of 3; see curvegen/submit_campaign.sh).  Does the
# barrier work the full-grid sweep depends on: build cfgs, run every reference
# subarray's natural seeds, and measure the beam caps into the metadata CSV.
# This is the QA GATE -- eyeball the seed beams / imsize / cell in this log
# before letting the sweep array burn node-hours (scancel the queued sweep +
# collect jobs if they look wrong).  Submit via submit_campaign.sh, which sets
# NGVLA_REV / NGVLA_SIM_MODE / NGVLA_SCRATCH and the afterok chain.
set -u
CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy
: "${NGVLA_REV:?export NGVLA_REV (use submit_campaign.sh)}"
: "${NGVLA_SIM_MODE:?export NGVLA_SIM_MODE (use submit_campaign.sh)}"
export NGVLA_SCRATCH="${NGVLA_SCRATCH:-$SCRATCH/ngvla_curvegen}"
export NGVLA_MS_BASE="${NGVLA_MS_BASE:-$WORK/ngvla_curvegen}"
mkdir -p "$NGVLA_MS_BASE"
mkdir -p "$NGVLA_SCRATCH"
# CASA writes multi-GB TempLattice* images to the process cwd, which Slurm
# inherits from the SUBMISSION directory -- pin it to scratch so submitting
# from $HOME/the repo can never blow the home quota (the 15 Jul 2026 polish
# refines core-dumped exactly this way: "FiledesIO ... Disk quota exceeded").
RUN_CWD="$NGVLA_SCRATCH/run_${SLURM_JOB_ID:-manual}${SLURM_ARRAY_TASK_ID:+_$SLURM_ARRAY_TASK_ID}"
mkdir -p "$RUN_CWD"; cd "$RUN_CWD"

echo "=== CAMPAIGN PREP  rev=$NGVLA_REV  mode=$NGVLA_SIM_MODE ==="
"$PY" -c "import config as c; print('manifest: results=%s\n          ms=%s\n          n_subarrays=%d' % (c.RESULTS_DIR, c.MS_DIR, len(c.SUBARRAYS)))"

# 1. build this rev's subarray .cfg files (into configs<suffix>/)
echo "=== build_configs ==="
"$PY" "$CG/build_configs.py" || { echo "PREP: build_configs FAILED"; exit 1; }

# NB: the subarray-metadata CSV (subarrays_<combo>.csv) is a committed artifact
# generated once by build_subarrays_csv.py -- prep does NOT regenerate it, so a
# resubmit never blanks the caps fill_beam_caps writes below.

# 2. SEEDS ONLY for every subarray a cap depends on (offered set plus any
#    non-offered cap-reference, e.g. core-outer).  Seeds-only (NOT a pilot): the
#    two seeds are cap- and lattice-invariant, so they can never strand or
#    mis-cap a lattice point the way pre-cap pilot rows would for heterogeneous
#    subarrays (they would be measured under the wrong N_TAPERS/no-cap regime
#    and, being resumable ok rows, survive into collect -- codex review 12 Jul).
#    The seeds still exercise im.advise (imsize/cell) and give the native beam +
#    axis ratio to eyeball here; the full grid measures everything else under
#    the correct caps.  Resumable.
SEEDS=$("$PY" "$CG/campaign_tasks.py" seeds) \
    || { echo "PREP: campaign_tasks seeds FAILED"; exit 1; }
echo "seed set: $SEEDS"
rc=0
for SA in $SEEDS; do
    echo "=== seeds $SA ==="
    "$PY" "$CG/sweep.py" "$SA" --seeds-only || { echo "SEED FAILED: $SA"; rc=1; }
done
[ "$rc" -eq 0 ] || { echo "PREP: one or more seeds FAILED -- fix before caps"; exit 1; }

# 3. measure the heterogeneous beam caps from those natural seeds and write them
#    into the metadata CSV (fail-closed: aborts if a reference seed is missing)
echo "=== fill_beam_caps ==="
"$PY" "$CG/fill_beam_caps.py" || { echo "PREP: fill_beam_caps FAILED"; exit 1; }

echo "=== PREP DONE -- inspect the seed beams above; the sweep array follows ==="

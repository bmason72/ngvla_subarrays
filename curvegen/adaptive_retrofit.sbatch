#!/bin/bash
#SBATCH -J ngvla_adaptive_retrofit
#SBATCH -A AST25010
#SBATCH -o /work2/10240/bmason72/stampede3/adaptive_retrofit_%A_%a.log
#SBATCH -p icx
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 47:00:00
# ^ walltime CEILING per array task (matches backfill_psf.sbatch's convention).
#   Per (subarray, combo) map the retrofit driver targets plan 40 / audit 80
#   NEW evals (spec finding #2) -- far fewer than backfill's ~949 anchors --
#   so 47h is expected to be generous headroom, kept for safety on the
#   heavy long-baseline subarrays.  FULLY RESUMABLE at every granularity:
#     - within one `casapy adaptive.py <SA>` invocation, the wave loop's
#       only state is the (subarray, combo) results CSV (sweep.Sweep's own
#       keyed, resumable path) -- a kill mid-wave loses at most the points
#       already recorded (rows are appended as each completes), so a
#       resubmit of the SAME array index just continues that subarray from
#       wherever the table stands (see adaptive.py's run_wave_loop
#       docstring for the one known limitation: a retrofit run's own
#       audit-cap BOOKKEEPING resets per process invocation, since retrofit
#       deliberately counts "new evals only" and there is no on-disk record
#       of how much a PRIOR invocation already spent -- the underlying
#       measurements/topology stay perfectly resumable regardless; only the
#       cap could in principle be re-spent across a kill+resubmit pair);
#     - across subarrays within one task, an already-adaptive'd subarray is
#       cheap to re-visit (it will just converge or hit its cap again
#       quickly) -- a resubmit simply re-loops `for SA in $SA_LIST`;
#     - across the array, each of the 4 combo tasks is independent.

# PSF INSPECTOR / MFS-2 adaptive sampler, TASK 2e RETROFIT DEPLOYMENT.  A
# Slurm JOB ARRAY (0-3), one task per (rev, sim_mode) mono-campaign combo,
# that runs the certification-first warm-start adaptive sampler (curvegen/
# adaptive.py, task 2b) in FULL MEASURING MODE over every offered subarray of
# that combo, then re-collects + re-reports + re-exports exactly as
# campaign_collect.sbatch does.  Each `adaptive.py <SA>` call auto-detects
# "retrofit" (the combo's results CSV is already populated by the prior
# sweep/refine campaign) and only adds the certification pass's unretired
# remainder -- it NEVER re-images anything already on the table.
#
# ORDERING (spec "Retrofit / warm-start mode", finding #13): retrofit
# deployment is bmason-ordered and supersedes the V1 replay gate for
# retrofit specifically, but ONLY after the in-flight revD/track canary
# campaign completes -- adaptive.py is a NEW module untouched by the
# canary, but this sbatch still MEASURES (mutates the same combo result
# CSVs the canary/other campaign jobs write to), so:
#
#   *** DO NOT SUBMIT until: ***
#     1. the in-flight revD/track canary chain has finished (sweep -> collect
#        afterok chain fully afterok'd, no queued/running jobs for it);
#     2. `squeue -u $USER` shows NO other campaign job (sweep/refine/collect/
#        backfill) queued or running against ANY of the four mono combos
#        this array touches (revF/track, revF/snapshot, revD/track,
#        revD/snapshot) -- verify job ids with `squeue -u $USER -o
#        "%.10i %.30j %.8T"` and cross-check against the ids the canary chain
#        was submitted under before running the command below;
#     3. bmason has reviewed the certification-pass estimate (plan-only,
#        --budget matching PLAN_RETRO=40 if a dry run is wanted first) and
#        given the go-ahead for the expected new-eval counts.
#
# Submit from a LOGIN node (compute nodes cannot sbatch), only after the
# checks above:
#   sbatch --array=0-3 curvegen/adaptive_retrofit.sbatch
#   sbatch --array=2   curvegen/adaptive_retrofit.sbatch   # just revD/track
set -u
CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy

# array index -> combo.  MUST stay in step with sa_select/data/config_registry.csv
# (same COMBOS mapping as backfill_psf.sbatch; kept explicit here rather than
# derived, for the same reason -- one array covers all four).
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
mkdir -p "$CG/reports"
# CASA writes multi-GB TempLattice* images to the process cwd, which Slurm
# inherits from the SUBMISSION directory -- pin it to scratch so submitting
# from $HOME/the repo can never blow the 14 GB home quota (see
# backfill_psf.sbatch / campaign_sweep.sbatch; the 15 Jul 2026 polish
# core-dumped exactly this way, "Disk quota exceeded").
RUN_CWD="$NGVLA_SCRATCH/run_${SLURM_JOB_ID:-manual}${SLURM_ARRAY_TASK_ID:+_$SLURM_ARRAY_TASK_ID}"
mkdir -p "$RUN_CWD"; cd "$RUN_CWD"

echo "=== ADAPTIVE RETROFIT  rev=$NGVLA_REV  mode=$NGVLA_SIM_MODE  (cwd $RUN_CWD) ==="

# discover this combo's offered subarrays -- same computation backfill_psf.py
# uses for its own default target list (make_report.offered_order over the
# combo's registered subarrays CSV), just printed here so bash can loop
# `casapy adaptive.py <SA>` once per subarray (adaptive.py's CLI takes
# exactly one subarray positional argument, unlike backfill_psf.py's own
# internal multi-subarray loop).
SA_LIST=$("$PY" -c "
import sys
sys.path.insert(0, '$CG')
from make_report import offered_order, registry_paths
from config import REV, SIM_MODE
print(' '.join(offered_order(registry_paths(REV, SIM_MODE)[0])))
") || { echo "ADAPTIVE RETROFIT FAILED: could not discover offered subarrays for $NGVLA_REV/$NGVLA_SIM_MODE"; exit 1; }
if [ -z "$SA_LIST" ]; then
    echo "no offered subarrays for $NGVLA_REV/$NGVLA_SIM_MODE -- nothing to do"; exit 0
fi
echo "offered subarrays: $SA_LIST"

# rc tracks per-SA adaptive FAILURES only (a subarray whose driver call itself
# exits nonzero) -- one bad subarray must not stop the rest of the combo, but
# it SHOULD make this task's own exit code nonzero so a resubmit is obviously
# warranted (mirrors campaign_sweep.sbatch's rc convention).
rc=0
for SA in $SA_LIST; do
    echo "=== adaptive $SA  ($NGVLA_REV/$NGVLA_SIM_MODE) ==="
    "$PY" "$CG/adaptive.py" "$SA" \
        || { echo "ADAPTIVE FAILED (non-blocking, continuing combo): $SA"; rc=1; }
done

# collect + report (per-combo) + export + combined report, exactly the way
# campaign_collect.sbatch does (same three calls, same order) -- but ALL
# non-blocking here (campaign_collect.sbatch treats collect/report as
# blocking; this task already ran the expensive measuring work above, so a
# collect/report hiccup must not be allowed to look like the whole task
# failed when the real payload -- the updated results CSVs -- is safely on
# disk either way).
"$PY" "$CG/collect.py" \
    || echo "COLLECT FAILED (non-blocking): $NGVLA_REV/$NGVLA_SIM_MODE"

REPORT="$CG/reports/${NGVLA_REV}-${NGVLA_SIM_MODE}-curves.html"
"$PY" "$CG/make_report.py" "$REPORT" \
    --rev "$NGVLA_REV" --sim-mode "$NGVLA_SIM_MODE" \
    || echo "REPORT FAILED (non-blocking): $REPORT"

"$PY" "$CG/export_psf_data.py" \
    || echo "PSF EXPORT FAILED (non-blocking)"

# the flagship all-campaigns report (campaign dropdown): rebuild it from
# every registered combo's committed curve CSVs (make_report.py writes via
# tmp + os.replace, so concurrent array tasks racing this combined report
# never see a half-written file -- see make_report.py's report-writing note)
"$PY" "$CG/make_report.py" --combined "$CG/reports/ngvla-curves.html" \
    || echo "COMBINED REPORT FAILED (non-blocking; per-combo report above still valid)"

echo "adaptive retrofit task ${SLURM_ARRAY_TASK_ID:-0} done (rc=$rc) -> $NGVLA_REV/$NGVLA_SIM_MODE"
exit $rc

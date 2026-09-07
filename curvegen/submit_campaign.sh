#!/bin/bash
# Submit a full (rev, sim_mode) curve-generation campaign as a 3-stage Slurm
# pipeline: prep (seeds + beam caps) -> sweep (job array, one node per heavy
# subarray) -> collect+report, chained with --dependency=afterok.  Run from a
# LOGIN node (compute nodes cannot sbatch).
#
#   bash curvegen/submit_campaign.sh revF snapshot --time 24:00:00
#   bash curvegen/submit_campaign.sh revD track     --time 48:00:00
#   bash curvegen/submit_campaign.sh revD track     --prep-only   # QA gate first
#   bash curvegen/submit_campaign.sh revF snapshot --mode mfs \
#       --refine-budget 200 --refine-rounds 8 --time 24:00:00    # MFS snapshot production
#
# --mode selects the internal NGVLA_BAND key, but never names it: "1chan"
# (the default) is the single-channel 30 GHz campaign (NGVLA_BAND unset);
# "mfs" is the registered broadband fixed-window campaign for this
# (rev, sim_mode) -- its band is looked up from config_registry.csv (there
# must be exactly one MFS row for the combo).  There is no --band option;
# a registry fix, not a flag, is how a second MFS band per combo would be
# chosen.
#
# Env (NGVLA_REV / NGVLA_SIM_MODE / NGVLA_SCRATCH, plus NGVLA_BAND when
# --mode mfs resolves one) is exported to EVERY stage: a Slurm dependency
# does NOT inherit the submitter's environment, so each sbatch gets it
# explicitly via --export.  Everything is resumable; re-running this script
# (or resubmitting a single stage) continues where it left off.
set -euo pipefail

REV=${1:-}; MODE=${2:-}
if [ -z "$REV" ] || [ -z "$MODE" ]; then
    echo "usage: submit_campaign.sh <rev> <sim_mode> [--time HH:MM:SS] [--prep-only]" \
         "[--mode mfs|1chan]" >&2
    exit 2
fi
shift 2
WALL="48:00:00"; PREP_ONLY=0; RBUDGET=60; RROUNDS=3; RSCAN=8; RUNMODE="1chan"
while [ $# -gt 0 ]; do
    case "$1" in
        --time) WALL=${2:?}; shift 2 ;;
        --prep-only) PREP_ONLY=1; shift ;;
        --refine-budget) RBUDGET=${2:?}; shift 2 ;;   # polish pass: e.g. 200
        --refine-rounds) RROUNDS=${2:?}; shift 2 ;;   # polish pass: e.g. 8
        --refine-scan-points) RSCAN=${2:?}; shift 2 ;;  # E2 taper levels: e.g. 12
        --mode) RUNMODE=${2:?}; shift 2 ;;            # mfs | 1chan (default)
        --band) echo "--band was removed; use --mode mfs (the band is" \
                     "looked up from config_registry.csv)" >&2; exit 2 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done
case "$RUNMODE" in
    mfs|1chan) ;;
    *) echo "--mode must be 'mfs' or '1chan', got '$RUNMODE'" >&2; exit 2 ;;
esac
case "$RBUDGET$RROUNDS$RSCAN" in *[!0-9]*)
    echo "--refine-budget/--refine-rounds/--refine-scan-points must be positive integers" >&2; exit 2 ;;
esac
# the digit-only regex still admits 0; require strictly positive (a 0 budget
# does nothing, and scan-points 0 would make E2 classify without measuring)
if [ "$RBUDGET" -le 0 ] || [ "$RROUNDS" -le 0 ] || [ "$RSCAN" -le 0 ]; then
    echo "--refine-budget/--refine-rounds/--refine-scan-points must be > 0" >&2; exit 2
fi

CG=$HOME/Code/ngvla_subarrays/curvegen
PY=/work2/10240/bmason72/stampede3/casaenv/bin/casapy
ACCT="-A AST25010"      # TACC allocation (also in every .sbatch header)

if [ "$RUNMODE" = "mfs" ]; then
    BAND=$(NGVLA_REV=$REV NGVLA_SIM_MODE=$MODE "$PY" "$CG/campaign_tasks.py" mfs_band) || exit 1
else
    BAND=""
fi

export NGVLA_REV=$REV NGVLA_SIM_MODE=$MODE NGVLA_BAND=$BAND
export NGVLA_SCRATCH="${NGVLA_SCRATCH:-$SCRATCH/ngvla_curvegen}"
# MSes persist on $WORK (SCRATCH is purged; 15 Jul 2026); tclean work dirs
# stay on scratch (disposable TempLattice churn)
export NGVLA_MS_BASE="${NGVLA_MS_BASE:-$WORK/ngvla_curvegen}"
# refine knobs are ALWAYS exported explicitly (defaults 60/3/8): with
# --export=ALL a stale NGVLA_REFINE_* in the submitting shell would otherwise
# silently turn a default campaign into a polish pass (codex review).  BAND
# is "" for --mode 1chan (mono, unchanged); NGVLA_NOISE_POLICY is left unset
# so config.py always falls back to the registry's noise_policy.
EXP="ALL,NGVLA_REV=$REV,NGVLA_SIM_MODE=$MODE,NGVLA_BAND=$BAND,NGVLA_SCRATCH=$NGVLA_SCRATCH,NGVLA_MS_BASE=$NGVLA_MS_BASE,NGVLA_REFINE_BUDGET=$RBUDGET,NGVLA_REFINE_ROUNDS=$RROUNDS,NGVLA_REFINE_SCAN_POINTS=$RSCAN"

# guard: the combo must be registered and its metadata CSV must exist
"$PY" "$CG/campaign_tasks.py" narray >/dev/null || {
    echo "campaign_tasks failed -- is ($REV,$MODE) in config_registry.csv with a metadata CSV?" >&2
    exit 1; }
N=$("$PY" "$CG/campaign_tasks.py" narray)
if [ -n "$BAND" ]; then
    echo "campaign $REV/$MODE mode=$RUNMODE (registry $BAND): $N sweep array tasks, sweep walltime $WALL, scratch $NGVLA_SCRATCH"
else
    echo "campaign $REV/$MODE mode=$RUNMODE: $N sweep array tasks, sweep walltime $WALL, scratch $NGVLA_SCRATCH"
fi

# TACC's sbatch wrapper prints a "Welcome to Stampede3" banner to stdout, so
# a bare $(sbatch --parsable ...) capture is polluted with banner text and a
# downstream --dependency=afterok:$prep becomes a malformed multi-line string
# ("Job dependency problem").  Extract only the parsable job-id line, which is
# the sole line starting with a bare digit (banner lines start with -/>/space).
submit() {
    local out id
    out=$(sbatch --parsable "$@") || return 1
    id=$(printf '%s\n' "$out" | grep -oE '^[0-9]+' | tail -n1)
    [ -n "$id" ] || { echo "could not parse a job id from sbatch output:" >&2
                      printf '%s\n' "$out" >&2; return 1; }
    printf '%s\n' "$id"
}

prep=$(submit $ACCT --export="$EXP" "$CG/campaign_prep.sbatch") || exit 1
echo "prep job:    $prep   (QA gate -- check prep_${prep}.log seed beams)"
if [ "$PREP_ONLY" -eq 1 ]; then
    echo "--prep-only: stopping.  After eyeballing prep, submit the rest with:"
    echo "  sweep=\$(sbatch --parsable $ACCT --dependency=afterok:$prep --array=0-$((N-1)) --time=$WALL --export=\"$EXP\" $CG/campaign_sweep.sbatch | grep -oE '^[0-9]+' | tail -n1)"
    echo "  sbatch $ACCT --dependency=afterok:\$sweep --export=\"$EXP\" $CG/campaign_collect.sbatch"
    exit 0
fi

sweep=$(submit $ACCT --dependency=afterok:"$prep" --array=0-$((N-1)) \
        --time="$WALL" --export="$EXP" "$CG/campaign_sweep.sbatch") || exit 1
echo "sweep array: $sweep  (0-$((N-1)))"
collect=$(submit $ACCT --dependency=afterok:"$sweep" \
          --export="$EXP" "$CG/campaign_collect.sbatch") || exit 1
echo "collect job: $collect"
echo "submitted.  monitor: squeue -u $USER   |   cancel downstream: scancel $sweep $collect"

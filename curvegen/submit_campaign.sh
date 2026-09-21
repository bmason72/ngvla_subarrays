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
#   bash curvegen/submit_campaign.sh revF track \
#       --subarrays "spiral+5 spiral+10 mid+spiral+5 mid+spiral+10" \
#       --prep-only --time 48:00:00   # D14 backfill: restrict to just the new subarrays
#
# --subarrays "a b c" (D14, docs/plans/spiral-plus-campaign-plan.md) restricts
# the run to a comma- or space-separated subset of the combo's offered
# subarrays, so a backfill provably cannot add points to, or otherwise touch,
# the already-released curves for the rest.  It is OPT-IN: omitting it leaves
# every stage's behaviour byte-identical to before this flag existed.
# campaign_tasks.py fails closed on any name not in the combo's metadata CSV.
# collect.py deliberately ignores the restriction (see its module docstring)
# -- it always rewrites the full routed curves CSV.
#
# Hardening (S2 review, 21 Sep 2026): Slurm's --export string is
# comma-delimited, so the operator's "a b c"/"a,b,c" form is normalized here
# into a single colon-joined token (colon is safe: no subarray name uses it)
# before it goes into EXP -- a space or comma surviving into an --export item
# is fragile.  Names containing ':' or ',' are rejected up front.  A
# companion NGVLA_SUBARRAYS_N (the name count) travels alongside it; if
# NGVLA_SUBARRAYS ever arrives at a stage empty or truncated,
# campaign_tasks.py's fail-closed check aborts that stage instead of silently
# sweeping the unrestricted offered set.
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
         "[--mode mfs|1chan] [--subarrays \"a b c\"]" >&2
    exit 2
fi
shift 2
WALL="48:00:00"; PREP_ONLY=0; RBUDGET=60; RROUNDS=3; RSCAN=8; RUNMODE="1chan"
SUBARRAYS=""
while [ $# -gt 0 ]; do
    case "$1" in
        --time) WALL=${2:?}; shift 2 ;;
        --prep-only) PREP_ONLY=1; shift ;;
        --refine-budget) RBUDGET=${2:?}; shift 2 ;;   # polish pass: e.g. 200
        --refine-rounds) RROUNDS=${2:?}; shift 2 ;;   # polish pass: e.g. 8
        --refine-scan-points) RSCAN=${2:?}; shift 2 ;;  # E2 taper levels: e.g. 12
        --mode) RUNMODE=${2:?}; shift 2 ;;            # mfs | 1chan (default)
        --subarrays) SUBARRAYS=${2:?}; shift 2 ;;     # D14: restrict the offered set
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

# Normalize --subarrays into a colon-joined token with no spaces and no
# commas (S2 hardening): a space or comma inside one comma-delimited
# --export item is fragile, and colon cannot appear in a subarray name.
# Accept whatever mix of spaces/commas the operator typed; reject any name
# that itself contains ':' or ',' (both would break re-parsing downstream).
SUBARRAYS_TOKEN=""
SUBARRAYS_N=0
if [ -n "$SUBARRAYS" ]; then
    norm=${SUBARRAYS//,/ }
    read -r -a _sa_names <<< "$norm"
    for n in "${_sa_names[@]}"; do
        case "$n" in
            *:*|*,*)
                echo "--subarrays name '$n' contains ':' or ',' -- not allowed" \
                     "(':' is the internal join delimiter; ',' cannot survive" \
                     "Slurm's --export parsing)" >&2
                exit 2 ;;
        esac
    done
    SUBARRAYS_TOKEN=$(IFS=:; echo "${_sa_names[*]}")
    SUBARRAYS_N=${#_sa_names[@]}
fi

export NGVLA_REV=$REV NGVLA_SIM_MODE=$MODE NGVLA_BAND=$BAND
export NGVLA_SUBARRAYS="$SUBARRAYS_TOKEN"
export NGVLA_SUBARRAYS_N="$SUBARRAYS_N"
export NGVLA_SCRATCH="${NGVLA_SCRATCH:-$SCRATCH/ngvla_curvegen}"
# MSes persist on $WORK (SCRATCH is purged; 15 Jul 2026); tclean work dirs
# stay on scratch (disposable TempLattice churn)
export NGVLA_MS_BASE="${NGVLA_MS_BASE:-$WORK/ngvla_curvegen}"
# refine knobs are ALWAYS exported explicitly (defaults 60/3/8): with
# --export=ALL a stale NGVLA_REFINE_* in the submitting shell would otherwise
# silently turn a default campaign into a polish pass (codex review).  BAND
# is "" for --mode 1chan (mono, unchanged); NGVLA_NOISE_POLICY is left unset
# so config.py always falls back to the registry's noise_policy.  NGVLA_SUBARRAYS
# is "" (SUBARRAYS_N=0) unless --subarrays was given (D14): prep and sweep
# both need it, so it goes in EXP like every other campaign-wide knob, always
# explicitly (never left to inherit) so a stale value in the submitting shell
# can't leak through.  NGVLA_SUBARRAYS_N is the fail-closed companion:
# campaign_tasks.py aborts a stage rather than sweep unrestricted if the
# parsed name count doesn't match it.  collect deliberately does not read
# either variable (curvegen/collect.py's module docstring).
EXP="ALL,NGVLA_REV=$REV,NGVLA_SIM_MODE=$MODE,NGVLA_BAND=$BAND,NGVLA_SUBARRAYS=$NGVLA_SUBARRAYS,NGVLA_SUBARRAYS_N=$NGVLA_SUBARRAYS_N,NGVLA_SCRATCH=$NGVLA_SCRATCH,NGVLA_MS_BASE=$NGVLA_MS_BASE,NGVLA_REFINE_BUDGET=$RBUDGET,NGVLA_REFINE_ROUNDS=$RROUNDS,NGVLA_REFINE_SCAN_POINTS=$RSCAN"

# guard: the combo must be registered, its metadata CSV must exist, and (with
# --subarrays) every requested name must be offered and buildable -- this is
# the same campaign_tasks.py check the sweep itself uses, so a bad
# --subarrays name is caught here, before any node is allocated.
"$PY" "$CG/campaign_tasks.py" narray >/dev/null || {
    echo "campaign_tasks failed -- is ($REV,$MODE) in config_registry.csv with a metadata CSV, and is --subarrays (if given) a valid subset?" >&2
    exit 1; }
N=$("$PY" "$CG/campaign_tasks.py" narray)
if [ -n "$BAND" ]; then
    echo "campaign $REV/$MODE mode=$RUNMODE (registry $BAND): $N sweep array tasks, sweep walltime $WALL, scratch $NGVLA_SCRATCH"
else
    echo "campaign $REV/$MODE mode=$RUNMODE: $N sweep array tasks, sweep walltime $WALL, scratch $NGVLA_SCRATCH"
fi
if [ -n "$SUBARRAYS" ]; then
    echo "*** RESTRICTED RUN (--subarrays): only { $SUBARRAYS } will be swept/seeded -- the rest of the offered set is untouched ***"
    echo "    exported as NGVLA_SUBARRAYS=$NGVLA_SUBARRAYS  NGVLA_SUBARRAYS_N=$NGVLA_SUBARRAYS_N"
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

"""
Campaign job topology for the active (rev, sim_mode) -- the single source of
truth the sbatch scripts use to lay out a Slurm job array.

bmason's rule (8 Jul 2026): any subarray with baselines longer than ~2600 km
gets its OWN node; everything else shares one node.  So the sweep is a job
array of (one task per heavy subarray) + (one grouped task for all the light
ones).  The heavy set is read from the combo's subarrays CSV by b_max_m
(> 2.6e6 m == > 2600 km); the light set is the remaining offered subarrays.

Subcommands:
  groups     one line per array task: heavy tasks first (one subarray each),
             then a final line of the space-joined light subarrays.  The
             sweep sbatch runs line SLURM_ARRAY_TASK_ID.  Reads the registry
             + config for the active NGVLA_REV/SIM_MODE.
  narray     number of array tasks (= number of `groups` lines).  The submit
             wrapper uses it to size --array=0-(narray-1).
  seeds      space-joined set of subarrays to SEED in prep: every offered
             subarray plus any non-offered cap-reference subarray (e.g.
             core-outer backs the outer-core combos' caps but is not
             offered).
  mfs_band   the registered MFS band for NGVLA_REV/NGVLA_SIM_MODE, i.e. the
             config_registry.csv row for that (rev, sim_mode) whose `band`
             column is non-empty.  Used by submit_campaign.sh's `--mode mfs`
             to resolve the internal NGVLA_BAND key from a rev/sim_mode
             alone, so it must work BEFORE NGVLA_BAND is set -- it reads the
             registry directly and does NOT import config (config's
             module-level BAND validation would need NGVLA_BAND already
             decided).  Errors (no row, or more than one) exit non-zero.

NGVLA_SUBARRAYS (D14, docs/plans/spiral-plus-campaign-plan.md, S2): an
OPT-IN list of subarray names, colon-, comma- or space-separated (any mix),
that narrows the offered set read by `groups`/`narray`/`seeds` -- so a
backfill run can be provably restricted to just the new subarrays and cannot
add points to, or otherwise touch, the already-released ones.  Unset (the
default) leaves `_offered` -- and therefore every subcommand -- byte-identical
to before this flag existed.  A named subarray absent from the combo's
metadata CSV is a fail-closed error (never a silent drop, which would quietly
shrink the job array below what the operator asked for).  `collect.py`
deliberately does NOT read this variable -- see its module docstring.
`submit_campaign.sh` normalizes whatever the operator typed into a single
colon-joined token before exporting it, because Slurm's `--export` string is
comma-delimited and a space or comma inside one item is fragile; colon is
safe because no subarray name may contain one.

NGVLA_SUBARRAYS_N is an OPT-IN companion: when set and non-zero, it records
how many names the submitter intended to restrict to, and `_requested_subarrays`
checks the parsed name list against it.  A mismatch (propagation dropped or
truncated NGVLA_SUBARRAYS somewhere between the submitter and this stage)
raises SystemExit rather than silently falling back to "no restriction" --
that fallback is exactly the failure mode this flag exists to prevent.
Leaving NGVLA_SUBARRAYS_N unset (interactive use) skips the check; leaving
both variables unset is exactly today's unrestricted behaviour.

Run:  NGVLA_REV=revD NGVLA_SIM_MODE=track casapy campaign_tasks.py groups
      NGVLA_REV=revF NGVLA_SIM_MODE=snapshot casapy campaign_tasks.py mfs_band
      NGVLA_SUBARRAYS="spiral+5 spiral+10" casapy campaign_tasks.py groups
      NGVLA_SUBARRAYS="spiral+5:spiral+10" NGVLA_SUBARRAYS_N=2 \\
          casapy campaign_tasks.py groups
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO, "sa_select", "data")
HEAVY_BMAX_M = 2.6e6          # > 2600 km baselines -> own node


def _registry_rows():
    reg = os.path.join(DATA_DIR, "config_registry.csv")
    with open(reg, newline="") as f:
        return list(csv.DictReader(f))


def mfs_band(rev, sim_mode):
    """The single registered MFS band for (rev, sim_mode), reading the
    registry CSV directly (no config import -- see module docstring)."""
    hits = [r["band"].strip() for r in _registry_rows()
            if r["rev"].strip() == rev and r["sim_mode"].strip() == sim_mode
            and (r.get("band") or "").strip()]
    if not hits:
        raise SystemExit("no MFS combo registered for %s/%s" % (rev, sim_mode))
    if len(hits) > 1:
        raise SystemExit(
            "more than one MFS band registered for %s/%s: %s -- fix "
            "config_registry.csv (there must be exactly one)"
            % (rev, sim_mode, ", ".join(sorted(set(hits)))))
    return hits[0]


def _subarrays_csv(rev, sim_mode, band):
    for r in _registry_rows():
        if (r["rev"].strip() == rev and r["sim_mode"].strip() == sim_mode
                and (r.get("band") or "").strip().lower() == band):
            return os.path.join(DATA_DIR, r["subarrays_csv"].strip())
    raise SystemExit("no config_registry.csv row for (rev=%r, sim_mode=%r, "
                     "band=%r)" % (rev, sim_mode, band))


def _requested_subarrays():
    """Parse NGVLA_SUBARRAYS (colon-, comma- and/or space-separated, any mix)
    into a list of names, or None if the variable is unset/blank -- None
    means "no restriction" and every caller must treat it that way (D14:
    unset must be byte-identical to before this flag existed).

    Fail-closed propagation check (S2 hardening): if the companion
    NGVLA_SUBARRAYS_N is set and non-zero, it must equal the number of names
    just parsed.  A mismatch means the restriction was dropped or truncated
    somewhere between the submitter and this stage -- e.g. Slurm's
    comma-delimited --export string silently losing part of the value -- and
    we abort rather than fall back to "no restriction", which would silently
    sweep the entire offered set (including already-released subarrays) on a
    backfill run.  NGVLA_SUBARRAYS_N unset skips the check, so setting the
    plain env var by hand (interactive use) still works without it."""
    raw = os.environ.get("NGVLA_SUBARRAYS", "")
    names = [n for n in raw.replace(",", " ").replace(":", " ").split() if n]
    n_raw = os.environ.get("NGVLA_SUBARRAYS_N", "").strip()
    if n_raw:
        try:
            n_expected = int(n_raw)
        except ValueError:
            raise SystemExit(
                "NGVLA_SUBARRAYS_N=%r is not an integer -- the subset "
                "restriction's propagation cannot be verified; aborting "
                "rather than silently widening the run to the full offered "
                "set." % n_raw)
        if n_expected != 0 and n_expected != len(names):
            raise SystemExit(
                "NGVLA_SUBARRAYS restriction failed to propagate to this "
                "stage: NGVLA_SUBARRAYS_N=%d but %d name(s) were parsed "
                "from NGVLA_SUBARRAYS=%r -- aborting rather than silently "
                "widening the run to the full offered set." %
                (n_expected, len(names), raw))
    return names or None


def _offered(rev, sim_mode, band):
    """[(name, b_max_m)] in the CSV's order (the offered set for this combo),
    narrowed to NGVLA_SUBARRAYS when it is set (D14).  A requested name not
    present in the CSV fails closed -- never a silent drop -- naming the
    offender and listing the valid names."""
    with open(_subarrays_csv(rev, sim_mode, band), newline="") as f:
        rows = [(r["name"].strip(), float(r["b_max_m"])) for r in csv.DictReader(f)]
    requested = _requested_subarrays()
    if requested is None:
        return rows
    by_name = dict(rows)
    unknown = [n for n in requested if n not in by_name]
    if unknown:
        raise SystemExit(
            "NGVLA_SUBARRAYS names not offered by %s/%s%s: %s -- valid names "
            "are: %s" % (rev, sim_mode, ("/" + band if band else ""),
                        ", ".join(unknown), ", ".join(n for n, _ in rows)))
    # preserve the CSV's row order for the names that are kept
    requested_set = set(requested)
    return [(n, bmax) for n, bmax in rows if n in requested_set]


def _check_buildable(offered_names):
    """Fail-closed preflight (S3, docs/plans/spiral-plus-campaign-plan.md):
    every offered subarray must be buildable (config.SUBARRAYS) AND sizeable
    (config.IMSIZE), or a sweep will die mid-run with a bare KeyError after
    nodes are already allocated (facts 5/6 in the plan).  Fires before any
    node is allocated because `groups()` calls it before returning.  Does
    NOT check seed_set()'s cap-reference extras (e.g. core-outer) -- those
    are deliberately allowed to be non-offered."""
    from config import SUBARRAYS, IMSIZE
    missing_subarrays = [n for n in offered_names if n not in SUBARRAYS]
    missing_imsize = [n for n in offered_names if n not in IMSIZE]
    if missing_subarrays or missing_imsize:
        parts = []
        if missing_subarrays:
            parts.append("missing from config.SUBARRAYS: %s"
                         % ", ".join(missing_subarrays))
        if missing_imsize:
            parts.append("missing from config.IMSIZE: %s"
                         % ", ".join(missing_imsize))
        raise SystemExit(
            "campaign_tasks: offered subarray(s) cannot be built/sized -- "
            + "; ".join(parts))


def groups():
    from config import REV, SIM_MODE, BAND
    offered = _offered(REV, SIM_MODE, BAND)
    _check_buildable([n for n, _ in offered])
    heavy = [n for n, bmax in offered if bmax > HEAVY_BMAX_M]
    light = [n for n, bmax in offered if bmax <= HEAVY_BMAX_M]
    lines = [n for n in heavy]                   # one task per heavy subarray
    if light:
        lines.append(" ".join(light))            # one grouped task
    return lines


def seed_set():
    from config import REV, SIM_MODE, BAND, CAP_REFERENCE, SUBARRAYS
    offered = [n for n, _ in _offered(REV, SIM_MODE, BAND)]
    seeds = list(offered)
    for name in offered:
        ref = CAP_REFERENCE.get(name)
        if ref and ref not in seeds and ref in SUBARRAYS:
            seeds.append(ref)
    return seeds


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "groups"
    if cmd == "groups":
        print("\n".join(groups()))
    elif cmd == "narray":
        print(len(groups()))
    elif cmd == "seeds":
        print(" ".join(seed_set()))
    elif cmd == "mfs_band":
        print(mfs_band(os.environ.get("NGVLA_REV", "revF"),
                       os.environ.get("NGVLA_SIM_MODE", "track")))
    else:
        raise SystemExit("usage: campaign_tasks.py "
                         "{groups|narray|seeds|mfs_band}")

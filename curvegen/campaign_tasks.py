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

Run:  NGVLA_REV=revD NGVLA_SIM_MODE=track casapy campaign_tasks.py groups
      NGVLA_REV=revF NGVLA_SIM_MODE=snapshot casapy campaign_tasks.py mfs_band
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


def _offered(rev, sim_mode, band):
    """[(name, b_max_m)] in the CSV's order (the offered set for this combo)."""
    with open(_subarrays_csv(rev, sim_mode, band), newline="") as f:
        return [(r["name"].strip(), float(r["b_max_m"])) for r in csv.DictReader(f)]


def groups():
    from config import REV, SIM_MODE, BAND
    offered = _offered(REV, SIM_MODE, BAND)
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

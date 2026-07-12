"""
Campaign job topology for the active (rev, sim_mode) -- the single source of
truth the sbatch scripts use to lay out a Slurm job array.

bmason's rule (8 Jul 2026): any subarray with baselines longer than ~2600 km
gets its OWN node; everything else shares one node.  So the sweep is a job
array of (one task per heavy subarray) + (one grouped task for all the light
ones).  The heavy set is read from the combo's subarrays CSV by b_max_m
(> 2.6e6 m == > 2600 km); the light set is the remaining offered subarrays.

Subcommands (all read the registry + config for the active NGVLA_REV/SIM_MODE):
  groups   one line per array task: heavy tasks first (one subarray each),
           then a final line of the space-joined light subarrays.  The sweep
           sbatch runs line SLURM_ARRAY_TASK_ID.
  narray   number of array tasks (= number of `groups` lines).  The submit
           wrapper uses it to size --array=0-(narray-1).
  seeds    space-joined set of subarrays to SEED in prep: every offered
           subarray plus any non-offered cap-reference subarray (e.g.
           core-outer backs the outer-core combos' caps but is not offered).

Run:  NGVLA_REV=revD NGVLA_SIM_MODE=track casapy campaign_tasks.py groups
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import REV, SIM_MODE, CAP_REFERENCE, SUBARRAYS, REPO   # noqa: E402

DATA_DIR = os.path.join(REPO, "sa_select", "data")
HEAVY_BMAX_M = 2.6e6          # > 2600 km baselines -> own node


def _subarrays_csv():
    reg = os.path.join(DATA_DIR, "config_registry.csv")
    with open(reg, newline="") as f:
        for r in csv.DictReader(f):
            if r["rev"].strip() == REV and r["sim_mode"].strip() == SIM_MODE:
                return os.path.join(DATA_DIR, r["subarrays_csv"].strip())
    raise SystemExit("no config_registry.csv row for (rev=%r, sim_mode=%r)"
                     % (REV, SIM_MODE))


def _offered():
    """[(name, b_max_m)] in the CSV's order (the offered set for this combo)."""
    with open(_subarrays_csv(), newline="") as f:
        return [(r["name"].strip(), float(r["b_max_m"])) for r in csv.DictReader(f)]


def groups():
    offered = _offered()
    heavy = [n for n, bmax in offered if bmax > HEAVY_BMAX_M]
    light = [n for n, bmax in offered if bmax <= HEAVY_BMAX_M]
    lines = [n for n in heavy]                   # one task per heavy subarray
    if light:
        lines.append(" ".join(light))            # one grouped task
    return lines


def seed_set():
    """Offered subarrays plus non-offered cap-reference subarrays -- the caps
    need those references' natural seeds even though they are not offered."""
    offered = [n for n, _ in _offered()]
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
    else:
        raise SystemExit("usage: campaign_tasks.py {groups|narray|seeds}")

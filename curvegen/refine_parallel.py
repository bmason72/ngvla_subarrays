"""Run refine.py for several subarrays CONCURRENTLY (bmason 8 Jul 2026, item 3).

Each subarray is an independent process with its OWN scratch cwd (CASA writes
multi-GB TempLattice* to the process cwd) and its own results CSV, so there is
no write contention.  Refinement WITHIN a subarray stays serial -- its adaptive
rounds depend on each other -- but the ~7 subarrays run in parallel, which is
the win over the old one-at-a-time loop.

Run under casapy (the wrapper fixes the TACC library env, inherited by the
children); needs $SCRATCH set:

  casapy refine_parallel.py long mid+long --max-procs 4 --omp 8
  casapy refine_parallel.py --all-offered --max-procs 4 --omp 8
"""
import argparse
import csv
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import REPO   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def offered():
    with open(os.path.join(REPO, "sa_select", "data", "subarrays.csv")) as f:
        return [r["name"].strip() for r in csv.DictReader(f)]


def scratch_cwd(sa):
    scratch = os.environ.get("SCRATCH")
    if not scratch:
        raise RuntimeError("$SCRATCH is not set; refusing to run CASA from cwd")
    d = os.path.join(scratch, "ngvla_curvegen",
                     "run_%s_refine" % sa.replace("+", "_").replace("-", "_"))
    os.makedirs(d, exist_ok=True)
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("subarrays", nargs="*")
    ap.add_argument("--all-offered", action="store_true")
    ap.add_argument("--max-procs", type=int, default=4)
    ap.add_argument("--omp", type=int, default=8)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--max-step", type=float, default=0.25)
    args = ap.parse_args()
    sas = offered() if args.all_offered else args.subarrays
    if not sas:
        ap.error("give subarray names or --all-offered")

    refine = os.path.join(HERE, "refine.py")
    env = dict(os.environ)
    env["OMP_NUM_THREADS"] = str(args.omp)
    queue, running, logs = list(sas), {}, {}
    failed = []
    while queue or running:
        while queue and len(running) < args.max_procs:
            sa = queue.pop(0)
            cwd = scratch_cwd(sa)
            log = open(os.path.join(cwd, "refine.log"), "w")
            p = subprocess.Popen(
                [sys.executable, refine, sa, "--rounds", str(args.rounds),
                 "--max-step", str(args.max_step)],
                cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
            running[p] = sa
            logs[p] = log
            print("started %-28s pid %d  cwd %s" % (sa, p.pid, cwd),
                  flush=True)
        time.sleep(2)
        for p in list(running):
            rc = p.poll()
            if rc is None:
                continue
            sa = running.pop(p)
            logs.pop(p).close()
            print("finished %-28s rc %d" % (sa, rc), flush=True)
            if rc != 0:
                failed.append(sa)
    if failed:
        print("REFINE FAILED: %s" % ", ".join(failed))
    print("refine_parallel done")


if __name__ == "__main__":
    main()

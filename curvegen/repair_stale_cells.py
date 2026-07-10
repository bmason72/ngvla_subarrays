"""Repair stale wrong-cell measurements (9 Jul 2026 incident).

68 v1-era "sculpt block" points (robust in {-2, -1.5, -1, -0.5} x the largest
sculpt tapers; core, spiral, mid, core+spiral, spiral+mid) were imaged before
run_point gained the adaptive cell rule, i.e. with the NATIVE cell instead of
cell = max(native, taper_mas/OVERSAMPLE/1e3).  Briggs weights depend on the
gridded uv density (uv cell = 1/(imsize*cell)), so those rows are measured
under a different weighting convention: beams up to 35% off the correctly
imaged rows at the same taper, spuriously low skirts, non-monotonic
res-vs-taper along rows.  They formed fake "strict islands" the imaging
curves jumped onto.  The resumable sweep never re-ran them (status ok ==
skipped forever) so the 8 Jul full-grid recompute preserved them.

This script, per affected subarray: archives the results CSV once to
results/attic-badcell/, strips the stale rows, and re-measures the same
(weighting, robust, taper) points with the current sweep.run_point.
Resumable: the stale keys are re-derived from the attic copy, and points
already re-recorded are skipped.

Run under casapy.  The parent mode spawns one worker per subarray with its
own $SCRATCH cwd (CASA writes multi-GB TempLattice* to the process cwd):

  casapy repair_stale_cells.py                # all affected subarrays
  casapy repair_stale_cells.py --worker core  # one subarray, in-process
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import RESULTS_DIR, OVERSAMPLE   # noqa: E402

ATTIC_DIR = os.path.join(RESULTS_DIR, "attic-badcell")


def results_path(subarray):
    return os.path.join(
        RESULTS_DIR, subarray.replace("+", "_").replace("-", "_") + ".csv")


def stale_keys(path):
    """[(weighting, robust, taper_mas)] of ok rows violating the cell rule."""
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["status"] != "ok" or not r["cell_arcsec"]:
                continue
            need = float(r["taper_mas"]) / OVERSAMPLE / 1e3
            if float(r["cell_arcsec"]) < need * 0.999:
                out.append((r["weighting"], float(r["robust"]),
                            float(r["taper_mas"])))
    return out


def affected_subarrays():
    from config import SUBARRAYS
    out = []
    for sa in sorted(SUBARRAYS):
        path = results_path(sa)
        attic = os.path.join(ATTIC_DIR, os.path.basename(path))
        if os.path.isfile(attic) or (
                os.path.isfile(path) and stale_keys(path)):
            out.append(sa)
    return out


def strip_and_archive(subarray):
    """Archive the CSV once, drop stale rows; return the stale key list."""
    path = results_path(subarray)
    attic = os.path.join(ATTIC_DIR, os.path.basename(path))
    if not os.path.isfile(attic):
        bad = stale_keys(path)
        if not bad:
            return []
        os.makedirs(ATTIC_DIR, exist_ok=True)
        shutil.copy2(path, attic)
        badset = set(bad)
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
            keep = [r for r in reader
                    if not (r["status"] == "ok" and r["cell_arcsec"] and
                            (r["weighting"], float(r["robust"]),
                             float(r["taper_mas"])) in badset)]
        tmp = path + ".tmp"
        with open(tmp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(keep)
        os.replace(tmp, path)
        print("%s: archived -> %s; stripped %d stale rows"
              % (subarray, attic, len(bad)))
    return stale_keys(attic)


def worker(subarray):
    keys = strip_and_archive(subarray)
    if not keys:
        print("%s: nothing to repair" % subarray)
        return True
    from sweep import Sweep    # deferred: imports casatasks
    sweep = Sweep(subarray)
    n_fail = 0
    for weighting, robust, taper in keys:
        row = sweep.run_point(weighting, robust, taper)
        if row["status"] == "failed":
            n_fail += 1
        else:
            print("    %s r=%s t=%s -> beam %s\" skirt %s (%ss)"
                  % (weighting, robust, taper, row["res_geo_arcsec"],
                     row["skirt"], row["elapsed_s"]))
    print("%s: re-measured %d points, %d failed"
          % (subarray, len(keys), n_fail))
    return n_fail == 0


def scratch_cwd(sa):
    scratch = os.environ.get("SCRATCH")
    if not scratch:
        raise RuntimeError("$SCRATCH is not set; refusing to run CASA from cwd")
    d = os.path.join(scratch, "ngvla_curvegen",
                     "run_%s_repair" % sa.replace("+", "_").replace("-", "_"))
    os.makedirs(d, exist_ok=True)
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--worker", metavar="SUBARRAY",
                    help="repair one subarray in-process (internal)")
    ap.add_argument("--max-procs", type=int, default=5)
    ap.add_argument("--omp", type=int, default=8)
    args = ap.parse_args()

    if args.worker:
        sys.exit(0 if worker(args.worker) else 1)

    sas = affected_subarrays()
    if not sas:
        print("no stale-cell rows anywhere; nothing to do")
        return
    print("repairing:", ", ".join(sas))
    here = os.path.abspath(__file__)
    env = dict(os.environ)
    env["OMP_NUM_THREADS"] = str(args.omp)
    queue, running, logs, failed = list(sas), {}, {}, []
    while queue or running:
        while queue and len(running) < args.max_procs:
            sa = queue.pop(0)
            cwd = scratch_cwd(sa)
            log = open(os.path.join(cwd, "repair.log"), "w")
            p = subprocess.Popen([sys.executable, here, "--worker", sa],
                                 cwd=cwd, env=env, stdout=log,
                                 stderr=subprocess.STDOUT)
            running[p], logs[p] = sa, log
            print("started %-14s pid %d  cwd %s" % (sa, p.pid, cwd), flush=True)
        time.sleep(2)
        for p in list(running):
            if p.poll() is None:
                continue
            sa = running.pop(p)
            logs.pop(p).close()
            print("finished %-14s rc %d" % (sa, p.returncode), flush=True)
            if p.returncode != 0:
                failed.append(sa)
    if failed:
        print("REPAIR FAILED:", ", ".join(failed))
        sys.exit(1)
    print("repair done")


if __name__ == "__main__":
    main()

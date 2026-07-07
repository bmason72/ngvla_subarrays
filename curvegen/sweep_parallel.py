"""
Run the curvegen lattice one row per subprocess.

The natural row is completed first in-process because Briggs rows use it for
the natural-edge convergence prune.  Each Briggs row then writes to its own CSV
shard, with CASA's process cwd placed under $SCRATCH so TempLattice* products do
not land under $HOME.

Run (from the curvegen/ directory, CASA's python3 wrapper):
  .../casapy sweep_parallel.py core+mid --max-procs 5 --omp 8
  .../casapy sweep_parallel.py main --dry-run
"""

import argparse
import csv
import os
import subprocess
import sys
import time

from config import SUBARRAYS
from sweep import FIELDS, Sweep, point_key, result_shards


def row_spec(weighting, robust):
    return "%s:%s" % (weighting, robust)


def shard_for(results_path, robust):
    return "%s.shard_r%s.csv" % (results_path, robust)


def log_for(shard_path):
    return shard_path[:-4] + ".log" if shard_path.endswith(".csv") \
        else shard_path + ".log"


def safe_part(value):
    return "".join(c if c.isalnum() or c in "._-" else "_"
                   for c in str(value))


def row_cwd(subarray, robust):
    scratch = os.environ.get("SCRATCH")
    if not scratch:
        raise RuntimeError("$SCRATCH is not set; refusing to run CASA from cwd")
    return os.path.join(scratch, "ngvla_curvegen",
                        "run_%s_row%s" % (safe_part(subarray),
                                          safe_part(robust)))


def phase0_cwd(subarray):
    scratch = os.environ.get("SCRATCH")
    if not scratch:
        raise RuntimeError("$SCRATCH is not set; refusing to run CASA from cwd")
    return os.path.join(scratch, "ngvla_curvegen",
                        "run_%s_phase0" % safe_part(subarray))


def warn(path, line_num, message):
    print("warning: skipping malformed result row in %s line %s: %s"
          % (path, line_num, message), file=sys.stderr)


def valid_result_rows(path):
    """Yield valid result rows; malformed crash-tail lines are warnings only."""
    if not os.path.isfile(path):
        return
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return
        if reader.fieldnames != FIELDS:
            print("warning: skipping %s: unexpected CSV header" % path,
                  file=sys.stderr)
            return
        for row in reader:
            if row.get(None) is not None:
                warn(path, reader.line_num, "wrong field count")
                continue
            if any(row.get(field) is None for field in FIELDS):
                warn(path, reader.line_num, "wrong field count")
                continue
            try:
                point_key(row["weighting"], row["robust"], row["taper_mas"])
            except Exception as e:
                warn(path, reader.line_num, str(e))
                continue
            yield row


def existing_keys(results_path):
    return set(existing_rows(results_path))


def existing_rows(results_path):
    rows = {}
    for row in valid_result_rows(results_path):
        rows[point_key(row["weighting"], row["robust"],
                       row["taper_mas"])] = row
    return rows


def merge_shards(results_path, replace_statuses=None):
    """Append shard rows to the main CSV, then remove shards.

    By default existing keys are skipped.  Callers doing targeted remeasurement
    may pass replace_statuses={"skipped"} to append a new row that supersedes a
    main-CSV skipped row; read_results keeps the later main row.
    """
    replace_statuses = set(replace_statuses or ())
    shards = result_shards(results_path)
    if not shards:
        print("merge: no shards found")
        return 0

    rows_by_key = existing_rows(results_path)
    total = 0
    for shard in shards:
        new_main = not os.path.isfile(results_path)
        n_add = 0
        n_replace = 0
        n_skip = 0
        with open(results_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            if new_main:
                writer.writeheader()
                new_main = False
            for row in valid_result_rows(shard):
                key = point_key(row["weighting"], row["robust"],
                                row["taper_mas"])
                old = rows_by_key.get(key)
                if old is not None:
                    if (old["status"] not in replace_statuses
                            or row["status"] == old["status"]):
                        n_skip += 1
                        continue
                    n_replace += 1
                writer.writerow(row)
                rows_by_key[key] = row
                n_add += 1
            f.flush()
            os.fsync(f.fileno())
        os.remove(shard)
        total += n_add
        if n_replace:
            print("merge: %s -> %d appended (%d replacements), %d already present"
                  % (os.path.basename(shard), n_add, n_replace, n_skip))
        else:
            print("merge: %s -> %d new, %d already present"
                  % (os.path.basename(shard), n_add, n_skip))
    return total


def result_counts(results_path):
    counts = dict(ok=0, skipped=0, capped=0, failed=0)
    for row in valid_result_rows(results_path):
        status = row["status"]
        if status in counts:
            counts[status] += 1
    return counts


def print_summary(subarray, results_path):
    counts = result_counts(results_path)
    print("%s done: %d ok, %d skipped, %d beam-capped, %d failed"
          % (subarray, counts["ok"], counts["skipped"], counts["capped"],
             counts["failed"]))


def row_complete(sweep, row):
    weighting, robust, tapers = row
    return sweep.row_complete(weighting, robust, tapers)


def print_row_statuses(sweep, rows):
    for weighting, robust, tapers in rows:
        state = "complete" if sweep.row_complete(weighting, robust, tapers) \
            else "pending"
        print("  %-12s %s" % (row_spec(weighting, robust), state))


def launch_row(args, sweep, row):
    weighting, robust, _tapers = row
    shard = shard_for(sweep.results_path, robust)
    log_path = log_for(shard)
    cwd = row_cwd(args.subarray, robust)
    os.makedirs(cwd, exist_ok=True)
    os.makedirs(os.path.dirname(shard), exist_ok=True)

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "sweep.py")
    cmd = [sys.executable, script, args.subarray,
           "--only-row", row_spec(weighting, robust),
           "--shard", shard]
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(args.omp)

    log = open(log_path, "a")
    log.write("\n=== %s ===\n" % " ".join(cmd))
    log.write("cwd: %s\n" % cwd)
    log.flush()
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log,
                            stderr=subprocess.STDOUT)
    print("started %-12s pid %s -> %s"
          % (row_spec(weighting, robust), proc.pid, log_path))
    return dict(row=row, proc=proc, log=log, log_path=log_path, shard=shard)


def close_entry(entry):
    if not entry["log"].closed:
        entry["log"].close()


def terminate_entries(entries):
    for entry in entries:
        if entry["proc"].poll() is None:
            entry["proc"].terminate()
    for entry in entries:
        proc = entry["proc"]
        if proc.poll() is None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        close_entry(entry)


def run_pending_rows(args, sweep, pending):
    queue = list(pending)
    running = []
    done = []
    try:
        while queue or running:
            while queue and len(running) < args.max_procs:
                running.append(launch_row(args, sweep, queue.pop(0)))
            progressed = False
            for entry in list(running):
                code = entry["proc"].poll()
                if code is None:
                    continue
                entry["returncode"] = code
                close_entry(entry)
                running.remove(entry)
                done.append(entry)
                state = "ok" if code == 0 else "failed"
                print("finished %-12s %s (exit %s)"
                      % (row_spec(entry["row"][0], entry["row"][1]), state,
                         code))
                progressed = True
            if running and not progressed:
                time.sleep(2)
    except KeyboardInterrupt:
        print("interrupt: terminating row subprocesses", file=sys.stderr)
        terminate_entries(running)
        raise
    finally:
        if running:
            terminate_entries(running)
    return done


def phase0(args, sweep):
    print("phase 0: seeds + natural row")
    ok = sweep.run(only_row=("natural", 2.0), require_seeds=False)
    if not ok:
        raise RuntimeError("could not complete seeds + natural row")
    prepared = sweep.prepare_lattice(require_existing=True, announce=False)
    if prepared is None:
        raise RuntimeError("could not reconstruct lattice after phase 0")
    rows = prepared[3]
    natural = [r for r in rows if r[0] == "natural"][0]
    if not row_complete(sweep, natural):
        raise RuntimeError("natural row is still incomplete after phase 0")
    return rows


def known_rows_if_natural_complete(sweep):
    try:
        prepared = sweep.prepare_lattice(require_existing=True, announce=False)
    except RuntimeError:
        return None
    if prepared is None:
        return None
    rows = prepared[3]
    natural = [r for r in rows if r[0] == "natural"][0]
    return rows if row_complete(sweep, natural) else None


def enter_scratch_cwd(subarray):
    cwd = phase0_cwd(subarray)
    os.makedirs(cwd, exist_ok=True)
    os.chdir(cwd)
    print("driver cwd:", cwd)


def dry_run(args):
    sweep = Sweep(args.subarray, include_shards=True)
    prepared = sweep.prepare_lattice(dry_run=True)
    if prepared is None:
        return 0
    rows = prepared[3]
    print("rows:")
    print_row_statuses(sweep, rows)
    pending = [r for r in rows if r[0] == "briggs" and not row_complete(sweep, r)]
    print("%d Briggs rows pending, %d complete"
          % (len(pending), len([r for r in rows if r[0] == "briggs"]) - len(pending)))
    return 0


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("subarray", choices=sorted(SUBARRAYS))
    ap.add_argument("--max-procs", type=int, default=5)
    ap.add_argument("--omp", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.max_procs < 1:
        ap.error("--max-procs must be >= 1")
    if args.omp < 1:
        ap.error("--omp must be >= 1")
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.dry_run:
        return dry_run(args)

    sweep = Sweep(args.subarray, include_shards=True)
    in_scratch = False
    try:
        rows = known_rows_if_natural_complete(sweep)
        if rows is None:
            enter_scratch_cwd(args.subarray)
            in_scratch = True
            rows = phase0(args, sweep)
        else:
            print("phase 0: seeds + natural row already complete")
        briggs_rows = [r for r in rows if r[0] == "briggs"]
        pending = [r for r in briggs_rows if not row_complete(sweep, r)]
        print("phase 1: Briggs rows")
        print_row_statuses(sweep, briggs_rows)

        done = []
        if pending:
            if not in_scratch:
                enter_scratch_cwd(args.subarray)
                in_scratch = True
            # Create/reuse the MS once before parallel children can race on it.
            sweep.ensure_ready()
            done = run_pending_rows(args, sweep, pending)
        else:
            print("phase 1: no pending Briggs rows")

        print("phase 2: merge shards")
        merge_shards(sweep.results_path)
        print_summary(args.subarray, sweep.results_path)

        failures = [e for e in done if e.get("returncode") != 0]
        if failures:
            print("row failures:")
            for entry in failures:
                print("  %-12s exit %s log %s"
                      % (row_spec(entry["row"][0], entry["row"][1]),
                         entry["returncode"], entry["log_path"]))
            return 1
        return 0
    except KeyboardInterrupt:
        return 130
    except RuntimeError as e:
        print("error:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

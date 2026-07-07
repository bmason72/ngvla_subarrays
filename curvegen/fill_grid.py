"""
Fill plausibly-cheap holes in a completed v2 curvegen lattice.

The normal sweep deliberately prunes rows once eta becomes uninteresting, so
the report heatmaps contain blank cells.  This script re-opens only the cheap
part of those blanks: points recorded as skipped, plus lattice points not yet
recorded at all.  Points already recorded as ok, failed or capped are left
alone.

Candidate selection is deliberately crude.  Eta is predicted from nearby ok
measurements on the current v2 lattice: log-taper interpolation within the
same row when a candidate is bracketed, nearest same-row measurement for row
edges, and the same-taper measurements in adjacent Briggs robust rows.  The
lowest of those eta estimates is used as a "plausibly cheap" test; the margin
is there because this is a go/no-go triage, not a science interpolation.

For heterogeneous arrays with a beam cap, the same-row resolution predictor is
used to avoid spending CASA time beyond the physical domain that sweep.py will
record as capped anyway.

Run (from the curvegen/ directory, CASA's python3 wrapper):
  .../casapy fill_grid.py core+mid --dry-run
  .../casapy fill_grid.py main --eta-max 2.5 --margin 1.15 --max-procs 4 --omp 6
"""

import argparse
import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict

from config import BEAM_CAP_ARCSEC, SUBARRAYS
from sweep import Sweep, point_key, result_shards
from sweep_parallel import merge_shards, existing_rows, log_for, safe_part


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("subarray", choices=sorted(SUBARRAYS))
    ap.add_argument("--eta-max", type=float, default=2.5)
    ap.add_argument("--margin", type=float, default=1.15)
    ap.add_argument("--max-procs", type=int, default=4)
    ap.add_argument("--omp", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.eta_max <= 0:
        ap.error("--eta-max must be > 0")
    if args.margin <= 0:
        ap.error("--margin must be > 0")
    if args.max_procs < 1:
        ap.error("--max-procs must be >= 1")
    if args.omp < 1:
        ap.error("--omp must be >= 1")
    return args


def row_spec(weighting, robust):
    return "%s:%g" % (weighting, robust)


def row_sort_key(row_key):
    if row_key[0] == "natural":
        return 0, 0.0
    return 1, -row_key[1]


def row_part(weighting, robust):
    return safe_part("%s_r%g" % (weighting, robust))


def fill_shard_for(results_path, weighting, robust):
    return "%s.shard_fill_%s.csv" % (results_path, row_part(weighting, robust))


def fill_row_cwd(subarray, weighting, robust):
    scratch = os.environ.get("SCRATCH")
    if not scratch:
        raise RuntimeError("$SCRATCH is not set; refusing to run CASA from cwd")
    return os.path.join(scratch, "ngvla_curvegen",
                        "fill_%s_%s" % (safe_part(subarray),
                                         row_part(weighting, robust)))


def fill_driver_cwd(subarray):
    scratch = os.environ.get("SCRATCH")
    if not scratch:
        raise RuntimeError("$SCRATCH is not set; refusing to run CASA from cwd")
    return os.path.join(scratch, "ngvla_curvegen",
                        "fill_%s_driver" % safe_part(subarray))


def enter_driver_cwd(subarray):
    cwd = fill_driver_cwd(subarray)
    os.makedirs(cwd, exist_ok=True)
    os.chdir(cwd)
    print("driver cwd:", cwd)


def build_lattice(rows):
    row_keys = []
    row_tapers = {}
    cell_indices = {}
    briggs_rows = []
    for weighting, robust, tapers in rows:
        row_key = (weighting, float(robust))
        row_keys.append(row_key)
        row_tapers[row_key] = list(tapers)
        if weighting == "briggs":
            briggs_rows.append(row_key)
        for col, taper in enumerate(tapers):
            cell_indices[point_key(weighting, robust, taper)] = (row_key, col)
    briggs_rows = sorted(briggs_rows, key=lambda r: r[1])
    briggs_pos = dict((row_key, i) for i, row_key in enumerate(briggs_rows))
    return dict(row_keys=row_keys, row_tapers=row_tapers,
                cell_indices=cell_indices, briggs_rows=briggs_rows,
                briggs_pos=briggs_pos)


def sample_from_row(row, sigma_nat):
    try:
        return dict(
            eta=float(row["sigma_dirty"]) / sigma_nat,
            res=float(row["res_geo_arcsec"]),
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def build_samples(sweep, lattice, sigma_nat):
    samples = {}
    for key in lattice["cell_indices"]:
        row = sweep.rows.get(key)
        if row and row.get("status") == "ok":
            sample = sample_from_row(row, sigma_nat)
            if sample is not None:
                samples[key] = sample
    return samples


def metric_at(samples, weighting, robust, taper, metric):
    sample = samples.get(point_key(weighting, robust, taper))
    return None if sample is None else sample[metric]


def taper_distance(taper_a, col_a, taper_b, col_b):
    if taper_a > 0 and taper_b > 0:
        return abs(math.log(taper_a) - math.log(taper_b))
    return abs(col_a - col_b)


def row_metric_points(row_key, lattice, samples, metric):
    out = []
    weighting, robust = row_key
    for col, taper in enumerate(lattice["row_tapers"][row_key]):
        value = metric_at(samples, weighting, robust, taper, metric)
        if value is not None:
            out.append((col, taper, value))
    return out


def row_interpolated(row_key, col, taper, lattice, samples, metric):
    if taper <= 0:
        return None
    points = row_metric_points(row_key, lattice, samples, metric)
    left = [p for p in points if 0 < p[1] < taper]
    right = [p for p in points if p[1] > taper]
    if not left or not right:
        return None
    left = max(left, key=lambda p: p[1])
    right = min(right, key=lambda p: p[1])
    _lcol, ltaper, lvalue = left
    _rcol, rtaper, rvalue = right
    frac = ((math.log(taper) - math.log(ltaper))
            / (math.log(rtaper) - math.log(ltaper)))
    value = lvalue + frac * (rvalue - lvalue)
    return value, "row-interp"


def row_nearest(row_key, col, taper, lattice, samples, metric):
    points = row_metric_points(row_key, lattice, samples, metric)
    if not points:
        return None
    ncol, ntaper, value = min(
        points,
        key=lambda p: (taper_distance(taper, col, p[1], p[0]),
                       abs(col - p[0])))
    return value, "row-nearest t=%g" % ntaper


def column_adjacent(row_key, col, taper, lattice, samples, metric):
    if row_key[0] != "briggs":
        return []
    pos = lattice["briggs_pos"][row_key]
    out = []
    for npos in (pos - 1, pos + 1):
        if npos < 0 or npos >= len(lattice["briggs_rows"]):
            continue
        nkey = lattice["briggs_rows"][npos]
        ntapers = lattice["row_tapers"][nkey]
        if col >= len(ntapers) or abs(ntapers[col] - taper) > 1e-6:
            continue
        value = metric_at(samples, nkey[0], nkey[1], ntapers[col], metric)
        if value is not None:
            out.append((value, "column %s" % row_spec(nkey[0], nkey[1])))
    return out


def predict_eta(row_key, col, taper, lattice, samples):
    sources = []
    row_source = row_interpolated(row_key, col, taper, lattice, samples, "eta")
    if row_source is None:
        row_source = row_nearest(row_key, col, taper, lattice, samples, "eta")
    if row_source is not None:
        sources.append(row_source)
    sources.extend(column_adjacent(row_key, col, taper, lattice, samples, "eta"))
    if not sources:
        return None
    return min(sources, key=lambda item: item[0])


def predict_resolution(row_key, col, taper, lattice, samples):
    row_source = row_interpolated(row_key, col, taper, lattice, samples, "res")
    if row_source is None:
        row_source = row_nearest(row_key, col, taper, lattice, samples, "res")
    if row_source is not None:
        return row_source
    cols = column_adjacent(row_key, col, taper, lattice, samples, "res")
    if not cols:
        return None
    return min(cols, key=lambda item: item[0])


def evaluate_candidates(sweep, rows, sigma_nat, eta_max, margin):
    lattice = build_lattice(rows)
    samples = build_samples(sweep, lattice, sigma_nat)
    eta_limit = eta_max * margin
    beam_cap = BEAM_CAP_ARCSEC.get(sweep.subarray)
    out = []

    for row_key in lattice["row_keys"]:
        weighting, robust = row_key
        for col, taper in enumerate(lattice["row_tapers"][row_key]):
            key = point_key(weighting, robust, taper)
            row = sweep.rows.get(key)
            if row is None:
                prior = "missing"
            elif row.get("status") == "skipped":
                prior = "skipped"
            else:
                continue

            pred_eta = predict_eta(row_key, col, taper, lattice, samples)
            pred_res = predict_resolution(row_key, col, taper, lattice, samples)
            keep = False
            if pred_eta is None:
                reason = "drop: no ok eta neighbor"
            elif pred_eta[0] > eta_limit:
                reason = "drop: eta %.3g > %.3g (%s)" % (
                    pred_eta[0], eta_limit, pred_eta[1])
            elif (beam_cap is not None and pred_res is not None
                    and pred_res[0] > beam_cap):
                reason = "drop: beam-cap res %.4g > %.4g arcsec (%s)" % (
                    pred_res[0], beam_cap, pred_res[1])
            else:
                keep = True
                reason = "keep: eta %.3g <= %.3g (%s)" % (
                    pred_eta[0], eta_limit, pred_eta[1])
                if beam_cap is not None and pred_res is None:
                    reason += "; no beam-cap predictor"
            out.append(dict(weighting=weighting, robust=robust, taper=taper,
                            key=key, prior=prior, pred_eta=pred_eta,
                            pred_res=pred_res, keep=keep, reason=reason))
    return out


def fmt_pred(pred):
    return "--" if pred is None else "%.4g" % pred[0]


def print_candidate_table(evals):
    if not evals:
        print("no skipped or missing lattice cells")
        return
    by_row = defaultdict(list)
    for ev in evals:
        by_row[(ev["weighting"], ev["robust"])].append(ev)

    total_keep = 0
    total_drop = 0
    for row_key in sorted(by_row, key=row_sort_key):
        print("%s:" % row_spec(row_key[0], row_key[1]))
        print("  %-12s %-8s %-9s %-9s %s"
              % ("taper_mas", "prior", "eta_pred", "res_pred", "decision"))
        for ev in by_row[row_key]:
            total_keep += 1 if ev["keep"] else 0
            total_drop += 0 if ev["keep"] else 1
            print("  %-12g %-8s %-9s %-9s %s"
                  % (ev["taper"], ev["prior"], fmt_pred(ev["pred_eta"]),
                     fmt_pred(ev["pred_res"]), ev["reason"]))
    print("totals: %d keep, %d drop, %d candidates"
          % (total_keep, total_drop, len(evals)))


def kept_groups(evals):
    groups = defaultdict(list)
    for ev in evals:
        if ev["keep"]:
            groups[(ev["weighting"], ev["robust"])].append(ev)
    return groups


def write_points_file(cwd, evals):
    path = os.path.join(cwd, "points.json")
    points = [dict(weighting=ev["weighting"], robust=ev["robust"],
                   taper_mas=ev["taper"]) for ev in evals]
    with open(path, "w") as f:
        json.dump(points, f, indent=2, sort_keys=True)
        f.write("\n")
    return path


def launch_group(args, sweep, row_key, evals):
    weighting, robust = row_key
    cwd = fill_row_cwd(args.subarray, weighting, robust)
    os.makedirs(cwd, exist_ok=True)
    os.makedirs(os.path.dirname(sweep.results_path), exist_ok=True)
    points_file = write_points_file(cwd, evals)
    shard = fill_shard_for(sweep.results_path, weighting, robust)
    log_path = log_for(shard)
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "sweep.py")
    cmd = [sys.executable, script, args.subarray,
           "--points-file", points_file, "--shard", shard]
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(args.omp)

    log = open(log_path, "a")
    log.write("\n=== %s ===\n" % " ".join(cmd))
    log.write("cwd: %s\n" % cwd)
    log.flush()
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log,
                            stderr=subprocess.STDOUT)
    print("started %-12s %3d points pid %s -> %s"
          % (row_spec(weighting, robust), len(evals), proc.pid, log_path))
    return dict(row=row_key, proc=proc, log=log, log_path=log_path,
                shard=shard, points=len(evals))


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


def run_groups(args, sweep, groups):
    queue = [(row_key, groups[row_key])
             for row_key in sorted(groups, key=row_sort_key)]
    running = []
    done = []
    try:
        while queue or running:
            while queue and len(running) < args.max_procs:
                row_key, evals = queue.pop(0)
                running.append(launch_group(args, sweep, row_key, evals))
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


def summarize_fill(results_path, kept, sigma_nat, eta_max):
    rows_by_key = existing_rows(results_path)
    measured = 0
    over_eta = 0
    capped = 0
    failed = 0
    pending = 0
    for ev in kept:
        row = rows_by_key.get(ev["key"])
        if row is None or row.get("status") == "skipped":
            pending += 1
            continue
        status = row.get("status")
        if status == "ok":
            measured += 1
            sample = sample_from_row(row, sigma_nat)
            if sample is not None and sample["eta"] > eta_max:
                over_eta += 1
        elif status == "capped":
            capped += 1
        elif status == "failed":
            failed += 1
        else:
            pending += 1
    print("fill summary: %d ok, %d actual eta > %.3g, "
          "%d capped, %d failed, %d still pending"
          % (measured, over_eta, eta_max, capped, failed, pending))


def prepare_sweep(subarray):
    sweep = Sweep(subarray, include_shards=True)
    prepared = sweep.prepare_lattice(require_existing=True)
    if prepared is None:
        raise RuntimeError("could not reconstruct lattice")
    return sweep, prepared


def dry_run(args):
    sweep, prepared = prepare_sweep(args.subarray)
    sigma_nat, _res_fine, _res_nat, rows = prepared
    evals = evaluate_candidates(sweep, rows, sigma_nat,
                                args.eta_max, args.margin)
    print_candidate_table(evals)
    return 0


def main(argv=None):
    args = parse_args(argv)
    if args.dry_run:
        try:
            return dry_run(args)
        except RuntimeError as e:
            print("error:", e, file=sys.stderr)
            return 1

    sweep = Sweep(args.subarray, include_shards=True)
    if result_shards(sweep.results_path):
        print("phase 0: merge existing shards")
        merge_shards(sweep.results_path, replace_statuses={"skipped"})

    try:
        sweep, prepared = prepare_sweep(args.subarray)
        sigma_nat, _res_fine, _res_nat, rows = prepared
        evals = evaluate_candidates(sweep, rows, sigma_nat,
                                    args.eta_max, args.margin)
        groups = kept_groups(evals)
        n_keep = sum(len(v) for v in groups.values())
        n_drop = len(evals) - n_keep
        print("planned fill: %d keep, %d drop, %d candidates"
              % (n_keep, n_drop, len(evals)))
        if not groups:
            print("no fill points selected")
            return 0

        enter_driver_cwd(args.subarray)
        # Create/reuse the MS once before parallel children can race on it,
        # and do it from scratch so CASA TempLattice files do not hit $HOME.
        sweep.ensure_ready()
        done = run_groups(args, sweep, groups)

        print("phase 2: merge shards")
        merge_shards(sweep.results_path, replace_statuses={"skipped"})
        kept = [ev for ev in evals if ev["keep"]]
        summarize_fill(sweep.results_path, kept, sigma_nat, args.eta_max)

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

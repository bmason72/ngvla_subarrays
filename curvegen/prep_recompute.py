"""Prepare results/ for the full-grid + spurious-shorts recompute campaign
(bmason 8 Jul 2026).  Run ONCE (plain python3, no CASA) before the recompute
sweep.  Two jobs, both required for a clean re-run because the sweep is
resumable and treats recorded ok/skipped rows as present (so stale data would
otherwise contaminate the new curves -- codex Q5):

  1. ARCHIVE the uvrange subarrays' result CSVs + shards -- their existing
     points were imaged WITHOUT the >178 m cut, so every beam/rms/skirt is
     stale.  They get a clean full-grid re-image.
  2. STRIP the eta-cap / natural+taper-convergence 'skipped' rows from the
     other offered subarrays (keeping ok, capped, and beam-cap skips) so the
     now-full-grid sweep re-measures those previously-pruned cells.

Archived CSVs go to results/attic-uvrange/ (collect.py globs only the top
level, so they are ignored).  Idempotent: re-running is safe (already-archived
subarrays have no top-level CSV; already-stripped files have no matching rows).
"""
import csv
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import MIN_UVRANGE_M, RESULTS_DIR, REPO   # noqa: E402

ATTIC = os.path.join(RESULTS_DIR, "attic-uvrange")


def result_basenames(sa):
    """Result filename for a subarray (cf. sweep.Sweep.results_path)."""
    return {sa.replace("+", "_").replace("-", "_") + ".csv"}


def offered():
    with open(os.path.join(REPO, "sa_select", "data", "subarrays.csv")) as f:
        return [r["name"].strip() for r in csv.DictReader(f)]


def strip_pruned(path):
    """Drop status=='skipped' rows whose reason is the (now-removed) eta cap or
    natural+taper convergence; keep ok/capped/failed and beam-cap skips."""
    with open(path, newline="") as f:
        rdr = csv.DictReader(f)
        fields = rdr.fieldnames
        rows = list(rdr)
    keep = [r for r in rows if not (
        r.get("status") == "skipped"
        and ("eta cap" in (r.get("error") or "")
             or "converged" in (r.get("error") or "")))]
    n = len(rows) - len(keep)
    if n:
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(keep)
    return n, len(keep)


def main():
    os.makedirs(ATTIC, exist_ok=True)
    uv = set(MIN_UVRANGE_M)
    for sa in offered():
        names = result_basenames(sa)
        present = [f for f in os.listdir(RESULTS_DIR)
                   if any(f == n or f.startswith(n + ".shard_") for n in names)]
        if sa in uv:
            if not present:
                print("%-30s already archived" % sa)
                continue
            for f in present:
                shutil.move(os.path.join(RESULTS_DIR, f),
                            os.path.join(ATTIC, f))
            print("%-30s ARCHIVED %d files (uvrange >%.0f m re-image)"
                  % (sa, len(present), MIN_UVRANGE_M[sa]))
        else:
            csvs = [f for f in present if f in names]
            if not csvs:
                print("%-30s (no results file)" % sa)
                continue
            n, kept = strip_pruned(os.path.join(RESULTS_DIR, csvs[0]))
            print("%-30s stripped %d eta/convergence skips, %d rows kept"
                  % (sa, n, kept))


if __name__ == "__main__":
    main()

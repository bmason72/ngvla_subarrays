"""
Measure the heterogeneous beam caps for a NON-default (rev, sim_mode) campaign
from its OWN natural seeds and write them into that combo's subarray-metadata
CSV -- the second half of the campaign two-step (seeds first, then caps into
the metadata, then the full grids).

The cap for a composite subarray is its coarsest-component / largest-contained
offered subarray's NATURAL beam (config.CAP_REFERENCE): a beam coarser than that
is a false economy (tapering a composite down into its coarse component's
regime), so the sweep prunes rows past the cap and the selector refuses beams
beyond it.  Those caps are known a priori only for (revF, track) -- there they
are hardcoded in config.  For any other combination the native beams differ
(snapshot beams are elliptical/sparse; Rev D geometry differs), so they must be
MEASURED here from the campaign's natural seeds.

FAILS CLOSED: if a required reference seed is missing or not status=ok this
aborts, because running the full grid with silently-empty caps would let the
capped subarrays sweep into the false-economy regime.  Overwrites the cap column
deliberately (a stale cap from a previous partial run is worse than a fresh one).

Prerequisite: seeds must already be measured (RESULTS_DIR/<ref>.csv exists with
the natural/untapered ok row) for every reference subarray -- run this AFTER the
seed pass and BEFORE the full-grid sweep.

Run:  NGVLA_REV=revD NGVLA_SIM_MODE=track casapy fill_beam_caps.py
      ... --dry-run       # print the caps it would write, change nothing
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (REV, SIM_MODE, RESULTS_DIR, CAP_REFERENCE,   # noqa: E402
                    SUBARRAYS, REPO)

DATA_DIR = os.path.join(REPO, "sa_select", "data")


def _results_csv(name):
    """sweep.py's results filename for a subarray (mirrors Sweep.results_path)."""
    return os.path.join(RESULTS_DIR,
                        name.replace("+", "_").replace("-", "_") + ".csv")


def natural_beam_arcsec(name):
    """res_geo (arcsec) of a subarray's measured natural/untapered seed, or a
    RuntimeError if that seed is missing / not status=ok."""
    path = _results_csv(name)
    if not os.path.isfile(path):
        raise RuntimeError("reference seed file missing: %s (seed %s first)"
                           % (path, name))
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if (r["weighting"] == "natural" and float(r["robust"]) == 2.0
                    and float(r["taper_mas"]) == 0.0):
                if r["status"] != "ok":
                    raise RuntimeError("reference natural seed for %s is "
                                       "status=%s (not ok): %s"
                                       % (name, r["status"], path))
                return float(r["res_geo_arcsec"])
    raise RuntimeError("no natural/untapered seed row in %s" % path)


def registry_subarrays_csv():
    reg = os.path.join(DATA_DIR, "config_registry.csv")
    with open(reg, newline="") as f:
        for r in csv.DictReader(f):
            if r["rev"].strip() == REV and r["sim_mode"].strip() == SIM_MODE:
                return os.path.join(DATA_DIR, r["subarrays_csv"].strip())
    raise SystemExit("no config_registry.csv row for (rev=%r, sim_mode=%r)"
                     % (REV, SIM_MODE))


def _read_metadata(subs_csv):
    with open(subs_csv, newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys()) if rows else []
    if "beam_cap_arcsec_30ghz" not in fields:
        raise SystemExit("%s has no beam_cap_arcsec_30ghz column" % subs_csv)
    return rows, fields


def required_cap_subarrays(rows):
    """Offered subarrays that MUST carry a measured cap (they have a cap
    reference), in the CSV's order."""
    return [r["name"].strip() for r in rows
            if r["name"].strip() in CAP_REFERENCE]


def verify():
    """Preflight for the full-grid sweep: assert every offered subarray that
    needs a cap actually has a non-empty one in the metadata CSV.  Fail closed
    (nonzero) so a non-default full grid never runs uncapped -- covers a direct
    sweep that skipped prep, a blanked CSV, or a partial cap column."""
    if (REV, SIM_MODE) == ("revF", "track"):
        print("(revF, track): caps hardcoded in config; verify is a no-op.")
        return
    rows, _ = _read_metadata(registry_subarrays_csv())
    have = {r["name"].strip(): (r.get("beam_cap_arcsec_30ghz") or "").strip()
            for r in rows}
    missing = [n for n in required_cap_subarrays(rows) if not have.get(n)]
    if missing:
        raise SystemExit("fill_beam_caps --verify: %d offered subarray(s) have "
                         "NO beam cap: %s -- run fill_beam_caps.py (after the "
                         "seed pass) before the full-grid sweep"
                         % (len(missing), ", ".join(missing)))
    print("verify OK: all %d capped subarrays have caps"
          % len(required_cap_subarrays(rows)))


def main(dry_run=False):
    if (REV, SIM_MODE) == ("revF", "track"):
        # SUCCESSFUL no-op, exactly like verify(): the default combo's caps
        # are hardcoded in config.py.  This used to exit nonzero, which
        # failed the whole campaign_prep stage the first time a revF/track
        # campaign was submitted through submit_campaign.sh (polish pass,
        # 15 Jul 2026 job 3314391).
        print("(revF, track): caps hardcoded in config; nothing to fill.")
        return
    subs_csv = registry_subarrays_csv()
    rows, fields = _read_metadata(subs_csv)

    # every offered subarray that HAS a cap reference, capped at that
    # reference's measured natural beam (order-stable for logging)
    caps = {}
    for name in required_cap_subarrays(rows):
        ref = CAP_REFERENCE[name]
        cap = natural_beam_arcsec(ref)          # raises -> fail closed
        caps[name] = cap
        print("  %-24s cap = %-12s natural beam = %.6g arcsec"
              % (name, ref, cap))
    if not caps:
        print("no heterogeneous subarrays for (%s, %s) -- nothing to write"
              % (REV, SIM_MODE))
        return

    if dry_run:
        print("--dry-run: would write %d caps into %s"
              % (len(caps), os.path.basename(subs_csv)))
        return

    # BLANK the whole cap column first, then write the freshly measured caps:
    # a stale non-blank cap on any other row would otherwise be loaded by
    # config._load_caps_from_metadata (codex review, 12 Jul 2026).
    for r in rows:
        r["beam_cap_arcsec_30ghz"] = "%.4g" % caps[r["name"].strip()] \
            if r["name"].strip() in caps else ""
    tmp = subs_csv + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, subs_csv)                    # atomic
    print("wrote %d caps -> %s" % (len(caps), subs_csv))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the caps it would write, change nothing")
    ap.add_argument("--verify", action="store_true",
                    help="preflight: assert all needed caps are present, "
                         "measure nothing (for the full-grid sweep to gate on)")
    args = ap.parse_args()
    try:
        if args.verify:
            verify()
        else:
            main(dry_run=args.dry_run)
    except RuntimeError as e:
        raise SystemExit("fill_beam_caps: %s" % e)

"""
Export captured PSF profiles as lazy-load JavaScript payloads for the reports.

Profile JSONL is append-only and may contain duplicate or malformed lines from
parallel sweep jobs.  This exporter keeps the last valid line for each lattice
point and writes script-tag JSONP rather than JSON: the reports are opened from
file://, where Chrome blocks fetch(), but locally loaded scripts still work.

Run (from the curvegen/ directory, system or CASA python3):
  python3 export_psf_data.py
  NGVLA_REV=revD NGVLA_SIM_MODE=track python3 export_psf_data.py \
      --rev revD --sim-mode track
  python3 export_psf_data.py --all
"""

import argparse
import csv
import json
import os
import subprocess
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(REPO, "sa_select", "data")
REPORT_PSF_DIR = os.path.join(SCRIPT_DIR, "reports", "psf")

PROFILE_FIELDS = ("res_geo_arcsec", "r_arcsec", "psf")
OPTIONAL_FIELDS = ("bmaj_arcsec", "bmin_arcsec", "bpa_deg",
                   "cut_r_arcsec", "cut_maj", "cut_min", "cut_rmax_fwhm")
CUT_FIELDS = ("cut_r_arcsec", "cut_maj", "cut_min")


def normalize_key(key):
    """Match JavaScript's toFixed() spelling of negative zero."""
    return key.replace("_-0.00_", "_0.00_")


# Exceptions parse_profile_line can raise for an invalid line; callers catch
# exactly this tuple (never a bare `except Exception`, so a genuine bug does
# not get silently swallowed as "just a malformed line").
PROFILE_LINE_ERRORS = (json.JSONDecodeError, KeyError, TypeError, ValueError)


def parse_profile_line(line):
    """Parse and validate one profile JSONL line.

    THIS is the definition of a valid profile line, shared by the exporter
    (transform_profile_lines) and backfill's planner (backfill_psf.
    cut_bearing_keys) so the two can never disagree about which line is a
    key's "last valid line" -- a line the exporter falls back past must be
    equally invisible to the planner, or the report can go stale while the
    planner thinks nothing needs re-imaging.

    Valid means: parses as JSON; is a JSON object; has a string "key"; has
    every PROFILE_FIELDS entry; and survives strict (allow_nan=False)
    re-serialization -- the release page embeds this data as literal
    JS/JSON, and a NaN/Infinity that Python's json module happily reads back
    out is not valid JSON a browser (or esprima) can parse.

    Returns (normalized_key, record) on success.  Raises one of
    PROFILE_LINE_ERRORS on any invalidity.
    """
    record = json.loads(line)
    if not isinstance(record, dict):
        raise ValueError("expected a JSON object")
    key = record["key"]
    if not isinstance(key, str):
        raise ValueError("'key' must be a string")
    missing = [field for field in PROFILE_FIELDS if field not in record]
    if missing:
        raise ValueError("missing field(s): %s" % ", ".join(missing))
    json.dumps(record, allow_nan=False)   # reject NaN/Infinity here
    return normalize_key(key), record


def transform_profile_lines(lines):
    """Return ({key: payload}, warnings) from append-ordered JSONL lines.

    The transform has no filesystem, environment, or configuration
    dependencies.  Later lines replace earlier lines after key normalization,
    using parse_profile_line's definition of "valid" -- an invalid last line
    never overwrites an earlier valid one for the same key.
    """
    profiles = {}
    warnings = []
    allowed = PROFILE_FIELDS + OPTIONAL_FIELDS
    for line_num, line in enumerate(lines, 1):
        try:
            key, record = parse_profile_line(line)
        except PROFILE_LINE_ERRORS as e:
            warnings.append("line %d: %s" % (line_num, e))
            continue
        payload = {field: record[field] for field in allowed
                   if field in record}
        profiles[key] = payload
    return profiles, warnings


def _atomic_write(out_path, text):
    """Write through a process-specific temporary file, then replace."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp = out_path + ".tmp.%d" % os.getpid()
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, out_path)


def _stem(subarray):
    return subarray.replace("+", "_").replace("-", "_")


def export_subarray(combo_key, subarray, profile_dir):
    """Export one offered subarray; return counts, or None when absent."""
    stem = _stem(subarray)
    in_path = os.path.join(profile_dir, stem + ".jsonl")
    if not os.path.isfile(in_path):
        print("%s/%s: skipped (no profile file %s)"
              % (combo_key, subarray, in_path))
        return None

    with open(in_path) as f:
        profiles, warnings = transform_profile_lines(f)
    for warning in warnings:
        print("warning: skipping malformed profile in %s %s"
              % (in_path, warning), file=sys.stderr)

    register_id = "%s/%s" % (combo_key, subarray)
    statement = "window.PSF_REGISTER(%s, %s);\n" % (
        json.dumps(register_id),
        json.dumps(profiles, separators=(",", ":"), sort_keys=True))
    out_path = os.path.join(REPORT_PSF_DIR, combo_key, stem + ".js")
    _atomic_write(out_path, statement)
    n_cuts = sum(all(field in payload for field in CUT_FIELDS)
                 for payload in profiles.values())
    print("%s/%s: %d points, %d with cuts"
          % (combo_key, subarray, len(profiles), n_cuts))
    return len(profiles), n_cuts


def export_active(rev, sim_mode):
    """Export every offered subarray for the active environment combo."""
    from config import PROFILE_DIR, REV, SIM_MODE
    from make_report import offered_order, registry_paths

    if (rev, sim_mode) != (REV, SIM_MODE):
        raise ValueError("--rev/--sim-mode (%s/%s) disagree with the "
                         "environment (NGVLA_REV=%s NGVLA_SIM_MODE=%s); "
                         "export those to match, so RESULTS_DIR points at "
                         "the right results dir"
                         % (rev, sim_mode, REV, SIM_MODE))

    subarrays_csv, _samples_csv = registry_paths(rev, sim_mode)
    combo_key = "%s_%s" % (rev, sim_mode)
    offered = offered_order(subarrays_csv)
    # "+"/"-" both stem to "_", so two display names could in principle share
    # an output filename; refuse rather than silently overwrite one of them
    stems = [_stem(s) for s in offered]
    if len(set(stems)) != len(stems):
        raise SystemExit("stem collision among offered subarrays: %s"
                         % ", ".join(sorted(offered)))
    for subarray in offered:
        export_subarray(combo_key, subarray, PROFILE_DIR)


def export_all():
    """Export every registered combo in its own env-routed subprocess.

    One combo's failure must not abandon the rest (QA review 16 Jul 2026);
    the exit status still reports any failure at the end."""
    reg = os.path.join(DATA_DIR, "config_registry.csv")
    with open(reg, newline="") as f:
        rows = list(csv.DictReader(f))
    failed = []
    for row in rows:
        # MFS profiles use band-qualified keys and are wired in MFS-5.  Do not
        # accidentally re-run the corresponding mono combo under a duplicate
        # (rev, mode) key while those rows share the registry.
        if (row.get("band") or "").strip():
            continue
        rev = row["rev"].strip()
        sim_mode = row["sim_mode"].strip()
        env = dict(os.environ, NGVLA_REV=rev, NGVLA_SIM_MODE=sim_mode)
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__),
             "--rev", rev, "--sim-mode", sim_mode],
            env=env)
        if proc.returncode != 0:
            failed.append("%s/%s" % (rev, sim_mode))
            print("export FAILED for %s/%s (continuing)" % (rev, sim_mode),
                  file=sys.stderr)
    if failed:
        raise SystemExit("export_psf_data --all: failed combos: %s"
                         % ", ".join(failed))


def main():
    env_rev = os.environ.get("NGVLA_REV", "revF")
    env_sim_mode = os.environ.get("NGVLA_SIM_MODE", "track")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rev", default=env_rev,
                    help="config revision (default: $NGVLA_REV or revF)")
    ap.add_argument("--sim-mode", default=env_sim_mode, dest="sim_mode",
                    help="simulation mode (default: $NGVLA_SIM_MODE or track)")
    ap.add_argument("--all", action="store_true",
                    help="export every config_registry.csv combo in routed "
                         "subprocesses; ignores --rev/--sim-mode")
    args = ap.parse_args()

    if args.all:
        export_all()
        return
    try:
        export_active(args.rev, args.sim_mode)
    except ValueError as e:
        ap.error(str(e))


if __name__ == "__main__":
    main()

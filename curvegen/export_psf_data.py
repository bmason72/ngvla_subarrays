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
import math
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
ARCSEC_TO_RAD = math.pi / (180.0 * 3600.0)


def _profile_points(record):
    """Finite radial-profile samples sorted by non-negative radius."""
    points = []
    for radius, value in zip(record.get("r_arcsec", []),
                             record.get("psf", [])):
        try:
            radius, value = float(radius), float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(radius) and math.isfinite(value) and radius >= 0:
            points.append((radius, value))
    points.sort()
    # A radial bin normally starts slightly off-axis and is diluted relative
    # to the raw peak used to normalize the profile.  The PSF origin is known
    # exactly, so supply it when the capture does not.
    if not points or points[0][0] > 0:
        points.insert(0, (0.0, 1.0))
    else:
        points[0] = (0.0, 1.0)
    return points


def _level_crossing(points, level, start_radius=0.0):
    """First downward crossing of ``level`` at/after ``start_radius``."""
    previous = None
    for radius, value in points:
        if radius < start_radius:
            previous = (radius, value)
            continue
        if previous is not None:
            r0, y0 = previous
            if y0 > level and value <= level and value != y0:
                return r0 + (radius - r0) * (y0 - level) / (y0 - value)
        previous = (radius, value)
    return None


def _first_null_or_radial_minimum(points, start_radius):
    """Locate a zero crossing, or the first resolved radial minimum.

    Composite-array radial averages can sit on a broad positive pedestal and
    therefore never cross zero even though the core has ended.  In that case
    the first sustained local minimum is the profile-equivalent null.  The
    returned method makes this fallback explicit in the payload.
    """
    smoothed = []
    for index in range(len(points)):
        lo, hi = max(0, index - 2), min(len(points), index + 3)
        smoothed.append(sum(value for _radius, value in points[lo:hi]) /
                        (hi - lo))
    for index in range(1, len(points)):
        r0, y0 = points[index - 1]
        radius, value = points[index]
        if radius < start_radius:
            continue
        if y0 > 0 and value <= 0 and value != y0:
            crossing = r0 + (radius - r0) * y0 / (y0 - value)
            return crossing, 0.0, "zero_crossing"
        if index + 2 >= len(points):
            continue
        if (smoothed[index] <= smoothed[index - 1]
                and smoothed[index] < smoothed[index + 1]
                and smoothed[index + 2] > smoothed[index]
                and value < 0.5):
            return radius, max(0.0, value), "radial_minimum"
    return None


def derive_psf_metrics(record):
    """Measure half-power width, first-null volume, and volume ratios.

    All angular radii in the returned mapping are arcsec and volumes are sr.
    Missing crossings are represented by absent fields, rather than treating
    a profile's capture boundary as a physical null. A resolved positive
    minimum in a composite-array profile is retained and explicitly flagged
    as a null proxy. Omega_G (``gaussian_volume_sr``) is the volume of the
    tclean restoring beam (an elliptical Gaussian of the record's bmaj/bmin),
    not a fit to the PSF -- CASA already produces it as part of imaging.
    Azimuthal averaging conserves the integral of B, so the first-null volume
    ratio against Omega_G is exact; the same average's integral of B^2
    slightly underestimates the true 2-D value for an elongated beam (Cauchy-
    Schwarz: the squared azimuthal average is <= the true 2-D integral), so
    the squared-volume ratio -- and the confusion scaling built on it -- is a
    mild underestimate in that case. For two-scale PSFs (composite subarrays,
    mostly at Briggs+taper points) the restoring beam is systematically wider
    than the core half-power width, because tclean's psfcutoff=0.35 fit
    picks up the PSF shoulder; ``restoring_to_halfpower_ratio`` is the
    diagnostic for that.
    """
    points = _profile_points(record)
    if len(points) < 2:
        return {}
    hwhm = _level_crossing(points, 0.5)
    if hwhm is None or not math.isfinite(hwhm) or hwhm <= 0:
        return {}
    measured_fwhm = 2.0 * hwhm
    metrics = {
        "hwhm_arcsec": hwhm,
        "measured_fwhm_arcsec": measured_fwhm,
    }
    bmaj = record.get("bmaj_arcsec")
    bmin = record.get("bmin_arcsec")
    if (isinstance(bmaj, (int, float)) and isinstance(bmin, (int, float))
            and math.isfinite(bmaj) and math.isfinite(bmin)
            and bmaj > 0 and bmin > 0):
        metrics["restoring_bmaj_arcsec"] = bmaj
        metrics["restoring_bmin_arcsec"] = bmin
        metrics["restoring_fwhm_geo_arcsec"] = math.sqrt(bmaj * bmin)
        bmaj_rad = bmaj * ARCSEC_TO_RAD
        bmin_rad = bmin * ARCSEC_TO_RAD
        metrics["gaussian_volume_sr"] = (
            math.pi * bmaj_rad * bmin_rad / (4.0 * math.log(2.0)))
        metrics["restoring_to_halfpower_ratio"] = (
            metrics["restoring_fwhm_geo_arcsec"] / measured_fwhm)

    null_result = _first_null_or_radial_minimum(points, hwhm)
    if null_result is None:
        return metrics
    first_null, null_value, null_method = null_result
    if first_null <= hwhm:
        return metrics
    integration_points = [(0.0, 1.0)]
    integration_points.extend((radius, value)
                              for radius, value in points
                              if 0 < radius < first_null)
    integration_points.append((first_null, null_value))
    radial_integral = 0.0
    squared_radial_integral = 0.0
    for (r0, y0), (r1, y1) in zip(integration_points,
                                  integration_points[1:]):
        radial_integral += 0.5 * (y0 * r0 + y1 * r1) * (r1 - r0)
        squared_radial_integral += (
            0.5 * (y0 * y0 * r0 + y1 * y1 * r1) * (r1 - r0))
    volume_sr = 2.0 * math.pi * radial_integral * ARCSEC_TO_RAD ** 2
    squared_volume_sr = (2.0 * math.pi * squared_radial_integral
                         * ARCSEC_TO_RAD ** 2)
    if math.isfinite(volume_sr) and volume_sr > 0:
        metrics["first_null_arcsec"] = first_null
        metrics["first_null_value"] = null_value
        metrics["first_null_method"] = null_method
        metrics["first_null_is_proxy"] = null_method != "zero_crossing"
        metrics["psf_volume_first_null_sr"] = volume_sr
        gaussian_volume = metrics.get("gaussian_volume_sr")
        if gaussian_volume:
            metrics["psf_to_gaussian_volume_ratio"] = (
                volume_sr / gaussian_volume)
    if math.isfinite(squared_volume_sr) and squared_volume_sr > 0:
        metrics["psf_squared_volume_first_null_sr"] = squared_volume_sr
        metrics["confusion_beam_sqrt_sr"] = math.sqrt(squared_volume_sr)
        gaussian_volume = metrics.get("gaussian_volume_sr")
        if gaussian_volume:
            # For a unit-peak Gaussian, integral(B^2) = Omega_G / 2.
            metrics["psf_to_gaussian_squared_volume_ratio"] = (
                squared_volume_sr / (0.5 * gaussian_volume))
    return metrics


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
        payload.update(derive_psf_metrics(record))
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


def export_active(rev, sim_mode, band=""):
    """Export every offered subarray for the active environment combo."""
    from config import PROFILE_DIR, REV, SIM_MODE, BAND, combo_key as _combo_key
    from make_report import offered_order, registry_paths

    band = (band or "").strip().lower()
    if (rev, sim_mode, band) != (REV, SIM_MODE, BAND):
        raise ValueError("--rev/--sim-mode/--band (%s/%s/%s) disagree with "
                         "the environment (NGVLA_REV=%s NGVLA_SIM_MODE=%s "
                         "NGVLA_BAND=%s); export those to match, so "
                         "RESULTS_DIR points at the right results dir"
                         % (rev, sim_mode, band, REV, SIM_MODE, BAND))

    subarrays_csv, _samples_csv = registry_paths(rev, sim_mode, band)
    combo_key = _combo_key(rev, sim_mode, band)
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
        rev = row["rev"].strip()
        sim_mode = row["sim_mode"].strip()
        band = (row.get("band") or "").strip().lower()
        env = dict(os.environ, NGVLA_REV=rev, NGVLA_SIM_MODE=sim_mode,
                  NGVLA_BAND=band)
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__),
             "--rev", rev, "--sim-mode", sim_mode, "--band", band],
            env=env)
        combo = "%s/%s/%s" % (rev, sim_mode, band) if band \
            else "%s/%s" % (rev, sim_mode)
        if proc.returncode != 0:
            failed.append(combo)
            print("export FAILED for %s (continuing)" % combo,
                  file=sys.stderr)
    if failed:
        raise SystemExit("export_psf_data --all: failed combos: %s"
                         % ", ".join(failed))


def main():
    env_rev = os.environ.get("NGVLA_REV", "revF")
    env_sim_mode = os.environ.get("NGVLA_SIM_MODE", "track")
    env_band = os.environ.get("NGVLA_BAND", "")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rev", default=env_rev,
                    help="config revision (default: $NGVLA_REV or revF)")
    ap.add_argument("--sim-mode", default=env_sim_mode, dest="sim_mode",
                    help="simulation mode (default: $NGVLA_SIM_MODE or track)")
    ap.add_argument("--band", default=env_band,
                    help="MFS band, e.g. band4 (default: $NGVLA_BAND or "
                         "empty for the mono campaigns)")
    ap.add_argument("--all", action="store_true",
                    help="export every config_registry.csv combo in routed "
                         "subprocesses; ignores --rev/--sim-mode/--band")
    args = ap.parse_args()

    if args.all:
        export_all()
        return
    try:
        export_active(args.rev, args.sim_mode, args.band)
    except ValueError as e:
        ap.error(str(e))


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""
Build the bootstrap data tables for the NGVLA subarray-selection tool.

Produces two CSVs under sa_select/data/ (schemas are documented in the module
docstring of sa_select/schema.py):

  subarrays.csv        -- one row per subarray: baselines (from the Rev F
                           .cfg antenna position files), the memo-67 LAS
                           coefficient, and the sensitivity-calculator key.

  bootstrap_curves.csv -- one row per (resolution, eta, skirt) sample, built
                           from Viviana Rosero's memo-121 use-case simulation
                           tables (memo121artifacts/*Cln.csv). These are a
                           stand-in for proper Rev F taperability/sculpting
                           curves (see docs/plans/PLAN.md Track 2) -- they cover a
                           scattering of science-case resolutions rather than
                           a dense scan, and are unevenly distributed across
                           subarrays and frequencies.

Run with the CASA python (has numpy):
    /Applications/CASA.app/Contents/MacOS/python3 build_bootstrap_data.py

Only stdlib csv + numpy are used, so any Python 3 with numpy also works.
"""

import csv
import os

import numpy as np

# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))  # .../sa_select/data
SA_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))  # .../sa
DATA_DIR = HERE

CFG_DIR = os.path.join(SA_ROOT, "ngvla-configurations", "Rev F", "CASA Files")
CFG_FILES = {
    "core": os.path.join(CFG_DIR, "RevF_Core_2025_01_27_xyz.cfg"),
    "spiral": os.path.join(CFG_DIR, "RevF_Spiral_2025_01_16_xyz.cfg"),
    "mid": os.path.join(CFG_DIR, "RevF_MidSitesPreferred_2025_01_16_xyz.cfg"),
}

MEMO121_DIR = os.path.join(SA_ROOT, "memo121artifacts")

# Curve-sample source files, in dedup PRIORITY ORDER (first one wins when the
# same (CaseName, name_sub) key shows up more than once across files). All of
# PerformanceCln.csv turns out to be a byte-for-byte subset of
# EfficientPlusPerformanceCln.csv, and MainCln.csv has a couple of cases that
# also appear (as successful runs) in EfficientPlusPerformanceCln -- so this
# ordering makes EfficientPlusPerformanceCln authoritative and the other two
# only contribute genuinely new rows.
CURVE_SOURCE_FILES = [
    "EfficientPlusPerformanceCln.csv",
    "PerformanceCln.csv",
    "MainCln.csv",
]

# ----------------------------------------------------------------------
# Physical constants
# ----------------------------------------------------------------------

C_M_S = 299792458.0          # speed of light, m/s
RAD_TO_ARCSEC = 206264.8062  # arcsec per radian
REF_FREQ_GHZ = 30.0          # curve-table reference frequency

# ======================================================================
# Part 1: subarrays.csv -- baselines from the Rev F .cfg files
# ======================================================================


def read_cfg_positions(path):
    """Read a CASA antenna-config file (X Y Z diam name, '#'-comments).

    Positions are geocentric (ECEF) XYZ in meters. We only need pairwise
    separations, so we use the 3D vector norm directly -- correct to within
    a small projection effect from Earth's curvature over the array extent,
    which is negligible for LAS/baseline bookkeeping at this level.
    """
    xyz = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
            xyz.append((x, y, z))
    return np.array(xyz)


def baseline_minmax(xyz):
    """Shortest and longest pairwise baseline length (m) among antennas."""
    n = xyz.shape[0]
    diffs = xyz[:, None, :] - xyz[None, :, :]
    dist = np.sqrt((diffs ** 2).sum(axis=-1))
    iu = np.triu_indices(n, k=1)
    d = dist[iu]
    return float(d.min()), float(d.max())


def inner_core_positions(core_xyz, n_inner=57):
    """The innermost `n_inner` core antennas, by 3D distance from the core
    centroid.  Matches memo 121's CoreInner (57 antennas = half the 114-
    antenna core); the by-radius selection is our reading of "the smallest
    allowable inner part of the array" -- verify against Viviana's list if
    exact antenna membership ever matters.
    """
    centroid = core_xyz.mean(axis=0)
    r = np.sqrt(((core_xyz - centroid) ** 2).sum(axis=1))
    return core_xyz[np.argsort(r)[:n_inner]]


# The v1 subarrays: subsets of {Core, Spiral, Mid} plus memo 121's CoreInner.
SUBARRAY_COMPONENTS = {
    "core-inner": ["core-inner"],
    "core": ["core"],
    "spiral": ["spiral"],
    "mid": ["mid"],
    "core+spiral": ["core", "spiral"],
    # core+mid: measured (curvegen/results) but dropped from the offered set
    # (bmason, 6 Jul 2026): no science case; poor uv coverage without spiral
    "spiral+mid": ["spiral", "mid"],
    "main": ["core", "spiral", "mid"],
}

# Sensitivity-calculator subarray keys (ngVLA_sensitivity_calculator.py /
# subarray_data.pkl support: sba, core, spiral, mid, long, main, main+long,
# spiral+mid, spiral+core, mid+long). core+mid has no calculator entry.
CALC_NAME = {
    "core-inner": "",
    "core": "core",
    "spiral": "spiral",
    "mid": "mid",
    "core+spiral": "spiral+core",
    "core+mid": "",
    "spiral+mid": "spiral+mid",
    "main": "main",
}

# ---- LAS coefficient ---------------------------------------------------
# memo 67 measured LAS_core ~ 0.8 * lambda / b_min from disk-simulation
# fidelity analysis (Sec. 2), and LAS_SBA = 0.58 * lambda / b_min for the
# 6-m SBA.  Per bmason (5 Jul 2026): use ~0.8 for ALL the 18-m subarrays --
# a uniform, memo-67-anchored value -- until per-subarray disk simulations
# are done.  (The SBA value stays 0.58 when the SBA is added later.)
LAS_COEFF_18M = 0.80

LAS_NOTE_18M = (
    "0.80*lambda/b_min for all 18-m subarrays (memo 67 core measurement, "
    "applied uniformly per bmason 5 Jul 2026); replace with per-subarray "
    "disk-simulation measurements (memo 67 Sec. 2 method) eventually."
)


def build_subarrays_table():
    positions = {name: read_cfg_positions(path) for name, path in CFG_FILES.items()}
    positions["core-inner"] = inner_core_positions(positions["core"])

    rows = []
    for name, comps in SUBARRAY_COMPONENTS.items():
        xyz = np.concatenate([positions[c] for c in comps], axis=0)
        n_ant = xyz.shape[0]
        b_min, b_max = baseline_minmax(xyz)

        las_coeff, note = LAS_COEFF_18M, LAS_NOTE_18M

        rows.append(
            {
                "name": name,
                "components": "+".join(comps),
                "n_ant": n_ant,
                "b_min_m": round(b_min, 2),
                "b_max_m": round(b_max, 2),
                "las_coeff": las_coeff,
                "calc_name": CALC_NAME[name],
                "las_coeff_note": note,
            }
        )
    return rows


SUBARRAYS_FIELDS = [
    "name",
    "components",
    "n_ant",
    "b_min_m",
    "b_max_m",
    "las_coeff",
    "calc_name",
    "las_coeff_note",
]


# ======================================================================
# Part 2: bootstrap_curves.csv -- samples from the memo-121 use-case tables
# ======================================================================
#
# Units in the raw memo121artifacts/*Cln.csv files (confirmed against
# memos/NGVLA_121.txt, e.g. "the angular resolution in units of mas" and
# "we present the taper in mas, the achieved resolution in mas"):
#   Frequency          GHz
#   Resolution         target beam FWHM, mas, at `Frequency`
#   res_nat            achieved natural(+taper) resolution, mas
#   TA_nat, TA_rob     uv-taper FWHM, mas
#   level_nat/level_rob  PSF level at r = 1 FWHM (dimensionless, 0..1)
#   eta_nat/eta_rob    inefficiency factor (sigma / sigma_natural)
#   robust             Briggs robust parameter
# A value of -1 (or -2.00 for robust, which is a real edge-of-grid value --
# NOT a sentinel) in level/eta/resolution columns marks a failed simulation
# (memo 121 Sec. 4-5 describes some cases failing to reach the target); such
# rows are dropped.

# name_sub (raw) -> canonical subarray name. Anything not in this dict is
# skipped (it's a Long-containing combo, an "outer50core"/"CW_28_MOD" variant,
# a failed-assignment placeholder, or blank).
NAME_SUB_MAP = {
    "main": "main",
    "spiral_core": "core+spiral",
    "core": "core",
    "spiral": "spiral",
    "spiral_mid": "spiral+mid",
    "mid": "mid",
    "coreInner": "core-inner",
}


def skirt_note(level):
    """Flag skirt values outside the physically-expected [0, 1] range.

    One row (memo121:MainCln.csv:NGA10, Main, briggs) has level_rob = 1.48
    at the robust-grid edge (robust = -2) with a high eta (4.34) -- almost
    certainly a failed/unconverged sculpting fit rather than a real PSF
    level. We keep the row (it is not a -1 sentinel) but flag it so
    downstream code can decide whether to trust it.
    """
    if level is not None and level >= 0 and level > 1.0:
        return "skirt > 1.0 in source data -- likely a failed/unconverged fit, treat with caution"
    return ""


def to_float(s):
    """Parse a possibly comma-thousands-separated numeric CSV field."""
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_curve_rows():
    samples = []
    seen_keys = set()  # (CaseName, name_sub) already used, across files

    counts = {
        "skipped_name_sub": 0,
        "deduped": 0,
        "dropped_missing_natural": 0,
        "dropped_missing_briggs": 0,
        "kept_natural": 0,
        "kept_briggs": 0,
    }

    for fname in CURVE_SOURCE_FILES:
        path = os.path.join(MEMO121_DIR, fname)
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                case = row["CaseName"]
                name_sub = row["name_sub"]

                canonical = NAME_SUB_MAP.get(name_sub)
                if canonical is None:
                    counts["skipped_name_sub"] += 1
                    continue

                key = (case, name_sub)
                if key in seen_keys:
                    counts["deduped"] += 1
                    continue
                seen_keys.add(key)

                freq = to_float(row["Frequency"])
                target_res = to_float(row["Resolution"])
                source_base = "memo121:%s:%s" % (fname, case)

                # --- natural-weighting sample ---
                res_nat = to_float(row["res_nat"])
                eta_nat = to_float(row["eta_nat"])
                level_nat = to_float(row["level_nat"])
                ta_nat = to_float(row["TA_nat"])
                if (
                    freq is None
                    or res_nat is None
                    or eta_nat is None
                    or res_nat <= 0
                    or eta_nat <= 0
                ):
                    counts["dropped_missing_natural"] += 1
                else:
                    scale = freq / REF_FREQ_GHZ
                    samples.append(
                        {
                            "subarray": canonical,
                            "resolution_arcsec_30ghz": (res_nat / 1000.0) * scale,
                            "eta": eta_nat,
                            "skirt": ("" if level_nat is None or level_nat < 0 else level_nat),
                            "weighting": "natural",
                            "robust": "",
                            "taper_arcsec_30ghz": (
                                "" if not ta_nat or ta_nat <= 0 else (ta_nat / 1000.0) * scale
                            ),
                            "freq_orig_ghz": freq,
                            "source": source_base,
                            "note": skirt_note(level_nat),
                        }
                    )
                    counts["kept_natural"] += 1

                # --- briggs (robust+taper) sample ---
                # Per the build spec: resolution = the "Resolution" column
                # (the requested/target resolution the robust+taper
                # combination was tuned to achieve) -- there is no separate
                # "achieved robust resolution" column in the source table.
                eta_rob = to_float(row["eta_rob"])
                level_rob = to_float(row["level_rob"])
                ta_rob = to_float(row["TA_rob"])
                robust = to_float(row["robust"])
                if (
                    freq is None
                    or target_res is None
                    or eta_rob is None
                    or target_res <= 0
                    or eta_rob <= 0
                ):
                    counts["dropped_missing_briggs"] += 1
                else:
                    scale = freq / REF_FREQ_GHZ
                    samples.append(
                        {
                            "subarray": canonical,
                            "resolution_arcsec_30ghz": (target_res / 1000.0) * scale,
                            "eta": eta_rob,
                            "skirt": ("" if level_rob is None or level_rob < 0 else level_rob),
                            "weighting": "briggs",
                            "robust": ("" if robust is None else robust),
                            "taper_arcsec_30ghz": (
                                "" if not ta_rob or ta_rob <= 0 else (ta_rob / 1000.0) * scale
                            ),
                            "freq_orig_ghz": freq,
                            "source": source_base,
                            "note": skirt_note(level_rob),
                        }
                    )
                    counts["kept_briggs"] += 1

    return samples, counts


CURVES_FIELDS = [
    "subarray",
    "resolution_arcsec_30ghz",
    "eta",
    "skirt",
    "weighting",
    "robust",
    "taper_arcsec_30ghz",
    "freq_orig_ghz",
    "source",
    "note",
]


def format_row(row, fields, float_fields):
    out = {}
    for k in fields:
        v = row[k]
        if k in float_fields and isinstance(v, float):
            out[k] = "%.6g" % v
        else:
            out[k] = v
    return out


# ======================================================================
# main
# ======================================================================


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # --- subarrays.csv ---
    subarray_rows = build_subarrays_table()
    subarrays_path = os.path.join(DATA_DIR, "subarrays.csv")
    with open(subarrays_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SUBARRAYS_FIELDS)
        w.writeheader()
        for row in subarray_rows:
            w.writerow(row)
    print("wrote %s (%d rows)" % (subarrays_path, len(subarray_rows)))
    for row in subarray_rows:
        print(
            "  %-12s n_ant=%3d  b_min=%10.2f m  b_max=%12.2f m  "
            "las_coeff=%.2f  calc_name=%r"
            % (
                row["name"],
                row["n_ant"],
                row["b_min_m"],
                row["b_max_m"],
                row["las_coeff"],
                row["calc_name"],
            )
        )

    # --- bootstrap_curves.csv ---
    curve_samples, counts = load_curve_rows()
    curves_path = os.path.join(DATA_DIR, "bootstrap_curves.csv")
    float_fields = {"resolution_arcsec_30ghz", "taper_arcsec_30ghz", "skirt", "eta", "robust"}
    with open(curves_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CURVES_FIELDS)
        w.writeheader()
        for row in curve_samples:
            w.writerow(format_row(row, CURVES_FIELDS, float_fields))
    print("\nwrote %s (%d rows)" % (curves_path, len(curve_samples)))
    print("  parse/dedup bookkeeping:", counts)

    per_sub = {}
    for row in curve_samples:
        key = (row["subarray"], row["weighting"])
        per_sub[key] = per_sub.get(key, 0) + 1
    print("  sample counts by (subarray, weighting):")
    for key in sorted(per_sub):
        print("   ", key, "->", per_sub[key])


if __name__ == "__main__":
    main()

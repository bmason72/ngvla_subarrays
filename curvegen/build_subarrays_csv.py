"""
Generate the subarray-metadata CSV for a NON-default (rev, sim_mode) campaign
(sa_select/data/<subarrays_csv>, schema per sa_select/schema.py).

Everything geometric -- n_ant, b_min_m, b_max_m -- is computed from the
component .cfg files for the active NGVLA_REV; b_min honors the same
spurious-short-baseline cut the sweep uses (config.MIN_UVRANGE_M), so b_min and
hence LAS reflect the real long-baseline uv coverage (cf. Rev F's subarrays.csv
notes).  las_coeff is 0.80 (memo 67, applied uniformly, as for Rev F).
beam_cap_arcsec_30ghz is left EMPTY here: it is measured from the campaign's own
natural seeds and written in by curvegen/fill_beam_caps.py (the two-step:
seeds -> caps into the metadata -> full grids).  calc_name maps each subarray to
its ngVLA sensitivity-calculator (memo-96 pkl) key.

REFUSES to touch the default (revF, track) subarrays.csv -- that file is
authoritative and hand-maintained.  For revF/snapshot the geometry is identical
to Rev F, so this instead copies subarrays.csv and blanks the cap column (see
--from-default).

Run:  NGVLA_REV=revD NGVLA_SIM_MODE=track casapy build_subarrays_csv.py
      NGVLA_REV=revF NGVLA_SIM_MODE=snapshot casapy build_subarrays_csv.py --from-default
"""

import argparse
import csv
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (REV, SIM_MODE, BAND, MFS, SUBARRAYS, MIN_UVRANGE_M, REPO,  # noqa: E402
                    COMPONENT_CFGS, COMPONENT_DIR)
from build_configs import read_antenna_lines                         # noqa: E402

DATA_DIR = os.path.join(REPO, "sa_select", "data")
FIELDS = ["name", "components", "n_ant", "b_min_m", "b_max_m", "las_coeff",
          "beam_cap_arcsec_30ghz", "calc_name", "las_coeff_note"]

# each offered subarray -> its ngVLA sensitivity-calculator (memo-96 pkl) key,
# or "" if the calculator has no matching entry (the selector then falls back
# to a donor rescale; see sa_select/sensitivity.py).  Rev D combos map cleanly
# because the pkl is itself Rev-D vintage.
CALC_NAME = {
    "revD": {
        "core": "core", "spiral": "spiral", "mid": "mid",
        "core+spiral": "spiral+core", "spiral+mid": "spiral+mid",
        "main": "main", "long": "long", "mid+long": "mid+long",
        "main+long": "main+long",
    },
    # Rev C offers the same subarray shapes; the memo-96 pkl keys are shape
    # names and the sensitivity anchor is N_ant-based (from OUR csv), so the
    # same mapping applies.
    "revC": {
        "core": "core", "spiral": "spiral", "mid": "mid",
        "core+spiral": "spiral+core", "spiral+mid": "spiral+mid",
        "main": "main", "long": "long", "mid+long": "mid+long",
        "main+long": "main+long",
    },
}

_NOTE_STD = ("0.80*lambda/b_min for all 18-m subarrays (memo 67 core "
             "measurement, applied uniformly per bmason 5 Jul 2026); replace "
             "with per-subarray disk-simulation measurements (memo 67 Sec. 2 "
             "method) eventually.")
_NOTE_FILTERED = ("b_min/LAS reflect the uvrange>%gm spurious-shorts filter "
                  "(the lba's few-antenna cluster/site-internal baselines "
                  "removed; see config.MIN_UVRANGE_M). 0.80*lambda/b_min "
                  "(memo 67, applied uniformly per bmason). NB: the ngECT "
                  "sensitivity anchor is N_ant-based and does not model the "
                  "removed baselines.")
_NOTE_MAINLONG = ("lba b_min is RAW (spurious ~36 m short baselines NOT "
                  "filtered, per bmason 7 Jul 2026: the core's legitimate ~39 m "
                  "baselines live below any cut); LAS is therefore likely "
                  "overstated for lba-containing subarrays -- revisit if LAS "
                  "binds. 0.80*lambda/b_min (memo 67, applied uniformly).")


def component_xyz(name):
    """N x 3 antenna positions for one offered subarray (union of components)."""
    lines = []
    for comp in SUBARRAYS[name]:
        lines += read_antenna_lines(comp)
    return np.array([[float(v) for v in ln.split()[:3]] for ln in lines])


def baseline_stats(xyz, min_uvrange_m=None):
    """(n_ant, b_min_m, b_max_m).  b_min honors the spurious-short cut: the
    shortest baseline STRICTLY longer than min_uvrange_m (mirrors sweep.py's
    uvrange>cut imaging), or the raw shortest when no cut applies."""
    n = len(xyz)
    d = xyz[:, None, :] - xyz[None, :, :]
    bl = np.sqrt((d ** 2).sum(-1))
    iu = np.triu_indices(n, 1)
    lengths = bl[iu]
    b_max = float(lengths.max())
    if min_uvrange_m is not None:
        kept = lengths[lengths > min_uvrange_m]
        if kept.size == 0:
            raise RuntimeError("uvrange cut %g m removed ALL baselines for a "
                               "subarray" % min_uvrange_m)
        b_min = float(kept.min())
    else:
        b_min = float(lengths.min())
    return n, b_min, b_max


def note_for(name):
    if name in MIN_UVRANGE_M:
        return _NOTE_FILTERED % MIN_UVRANGE_M[name]
    if name == "main+long":
        return _NOTE_MAINLONG
    return _NOTE_STD


def build_from_geometry(out_path):
    calc = CALC_NAME.get(REV)
    if calc is None:
        raise SystemExit("no CALC_NAME map for rev=%r -- add one" % REV)
    rows = []
    for name in SUBARRAYS:
        xyz = component_xyz(name)
        n, b_min, b_max = baseline_stats(xyz, MIN_UVRANGE_M.get(name))
        rows.append({
            "name": name,
            "components": "+".join(SUBARRAYS[name]),
            "n_ant": n,
            "b_min_m": "%.2f" % b_min,
            "b_max_m": "%.2f" % b_max,
            "las_coeff": "0.8",
            "beam_cap_arcsec_30ghz": "",        # filled by fill_beam_caps.py
            "beam_cap_arcsec_native": "",
            "calc_name": calc.get(name, ""),
            "las_coeff_note": note_for(name),
        })
    _write(out_path, rows)
    print("wrote %d subarrays -> %s" % (len(rows), out_path))


def build_from_default(out_path):
    """revF/snapshot: identical geometry to Rev F -> copy subarrays.csv but
    blank the cap column (snapshot native beams differ; fill_beam_caps.py
    re-measures them)."""
    src = os.path.join(DATA_DIR, "subarrays.csv")
    with open(src, newline="") as f:
        rows = list(csv.DictReader(f))
    if MFS:
        rows = [r for r in rows if r["name"].strip() in SUBARRAYS]
    for r in rows:
        r["beam_cap_arcsec_30ghz"] = ""
        if MFS:
            r["beam_cap_arcsec_native"] = ""
    _write(out_path, rows)
    print("wrote %d subarrays (from subarrays.csv, caps blanked) -> %s"
          % (len(rows), out_path))


def _write(out_path, rows):
    fields = FIELDS + (["beam_cap_arcsec_native"] if MFS else [])
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def registry_subarrays_csv():
    """The subarrays_csv filename registered for the active (REV, SIM_MODE)."""
    reg = os.path.join(DATA_DIR, "config_registry.csv")
    with open(reg, newline="") as f:
        for r in csv.DictReader(f):
            if (r["rev"].strip() == REV
                    and r["sim_mode"].strip() == SIM_MODE
                    and (r.get("band") or "").strip().lower() == BAND):
                return r["subarrays_csv"].strip()
    raise SystemExit("no config_registry.csv row for (rev=%r, sim_mode=%r, "
                     "band=%r) -- add it first" % (REV, SIM_MODE, BAND))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-default", action="store_true",
                    help="copy subarrays.csv geometry (same rev) and blank "
                         "caps, instead of computing from cfgs")
    args = ap.parse_args()
    if not MFS and (REV, SIM_MODE) == ("revF", "track"):
        raise SystemExit("refusing to regenerate the authoritative default "
                         "subarrays.csv; set NGVLA_REV/NGVLA_SIM_MODE")
    out = os.path.join(DATA_DIR, registry_subarrays_csv())
    if args.from_default:
        build_from_default(out)
    else:
        build_from_geometry(out)

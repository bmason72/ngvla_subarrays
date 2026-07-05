"""
Collect sweep results into the sa_select curve-sample table.

Reads curvegen/results/<subarray>.csv files, computes eta for every point as
sigma_dirty / sigma_dirty(natural, untapered), and writes all subarrays'
samples to sa_select/data/revf_curves.csv in the schema documented in
sa_select/schema.py (same columns as bootstrap_curves.csv, freq_orig = 30).

Run:  .../python3 collect.py            # all result files
"""

import csv
import glob
import os

from config import RESULTS_DIR, REPO

OUT = os.path.join(REPO, "sa_select", "data", "revf_curves.csv")
OUT_FIELDS = ["subarray", "resolution_arcsec_30ghz", "eta", "skirt",
              "weighting", "robust", "taper_arcsec_30ghz", "freq_orig_ghz",
              "source", "note"]


def collect_one(path):
    with open(path, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "ok"]
    if not rows:
        return []
    nat = [r for r in rows
           if r["weighting"] == "natural" and float(r["taper_mas"]) == 0]
    if not nat:
        raise RuntimeError("%s has no natural/untapered reference point" % path)
    sigma_nat = float(nat[0]["sigma_dirty"])

    out = []
    for r in rows:
        taper_mas = float(r["taper_mas"])
        eta = float(r["sigma_dirty"]) / sigma_nat
        out.append(dict(
            subarray=r["subarray"],
            resolution_arcsec_30ghz="%.6g" % float(r["res_geo_arcsec"]),
            eta="%.4f" % eta,
            skirt=r["skirt"],
            weighting=r["weighting"],
            robust="" if r["weighting"] == "natural" else r["robust"],
            taper_arcsec_30ghz="" if taper_mas == 0 else "%.6g" % (taper_mas / 1e3),
            freq_orig_ghz="30.0",
            source="revf-sim:%s:%s_r%s_t%s" % (r["subarray"], r["weighting"],
                                               r["robust"], r["taper_mas"]),
            note="",
        ))
    return out


def main():
    samples = []
    for path in sorted(glob.glob(os.path.join(RESULTS_DIR, "*.csv"))):
        got = collect_one(path)
        print("%-28s %3d samples" % (os.path.basename(path), len(got)))
        samples += got
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(samples)
    print("wrote %d samples -> %s" % (len(samples), OUT))


if __name__ == "__main__":
    main()

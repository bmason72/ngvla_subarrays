"""
Build the HTML curve-inspection report from the current sweep results.

Reads sa_select/data/revf_curves.csv + subarrays.csv and injects the data as
JSON into report_template.html.  The output is a self-contained page (no
external resources) suitable for publishing as a Claude artifact or opening
directly in a browser.

Run:  .../python3 make_report.py [output.html]
"""

import csv
import json
import os
import sys

from config import REPO, RESULTS_DIR

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "report_template.html")

# fixed series order & display names (color slots assigned in the template;
# 'main' keeps its slot even while pending so colors never re-map)
ORDER = ["core", "spiral", "mid", "core+spiral", "spiral+mid", "core+mid", "main"]


def lower_envelope(samples, side, res_nat):
    """Non-dominated (res, eta) points on one side of the natural resolution.

    A point is dominated if another point closer to (or at) the same distance
    from native offers equal-or-lower eta.  Walking away from the natural
    point this yields the clean V-shaped taperability curve of the memos.
    """
    if side == "left":
        branch = [s for s in samples if s["res"] <= res_nat]
        dominated = lambda p, q: q["res"] >= p["res"] and q["eta"] <= p["eta"]
    else:
        branch = [s for s in samples if s["res"] >= res_nat]
        dominated = lambda p, q: q["res"] <= p["res"] and q["eta"] <= p["eta"]
    keep = [p for p in branch
            if not any(q is not p and dominated(p, q) for q in branch)]
    return sorted(keep, key=lambda s: s["res"])


def build_curve(samples, skirt_max=None):
    """V-shaped min-eta curve (list of sample dicts), optionally sculpted."""
    if skirt_max is not None:
        samples = [s for s in samples if s["skirt"] is not None
                   and s["skirt"] <= skirt_max]
    if not samples:
        return []
    nat = min(samples, key=lambda s: s["eta"])
    left = lower_envelope(samples, "left", nat["res"])
    right = lower_envelope(samples, "right", nat["res"])
    seen, out = set(), []
    for s in left + right:
        k = (s["res"], s["eta"])
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


def main(out_path):
    samples_by = {name: [] for name in ORDER}
    with open(os.path.join(REPO, "sa_select", "data", "revf_curves.csv")) as f:
        for r in csv.DictReader(f):
            samples_by[r["subarray"]].append(dict(
                res=float(r["resolution_arcsec_30ghz"]) * 1e3,   # mas
                eta=float(r["eta"]),
                skirt=float(r["skirt"]) if r["skirt"] else None,
                weighting=r["weighting"],
                robust=float(r["robust"]) if r["robust"] else None,
                taper=float(r["taper_arcsec_30ghz"]) * 1e3
                      if r["taper_arcsec_30ghz"] else 0.0,
            ))

    las = {}
    with open(os.path.join(REPO, "sa_select", "data", "subarrays.csv")) as f:
        for r in csv.DictReader(f):
            lam = 0.299792458 / 30.0
            las[r["name"]] = dict(
                mas=float(r["las_coeff"]) * lam / float(r["b_min_m"])
                    * 206264.8 * 1e3,
                coeff=float(r["las_coeff"]),
                provisional="PROVISIONAL" in r["las_coeff_note"],
                n_ant=int(r["n_ant"]))

    data = dict(order=ORDER, las=las, samples=samples_by,
                imaging={n: build_curve(samples_by[n], 0.10) for n in ORDER},
                pointsource={n: build_curve(samples_by[n]) for n in ORDER},
                counts={n: len(samples_by[n]) for n in ORDER})

    # core+spiral natural-PSF radial profile measured 5 Jul 2026 (subsampled
    # diagnostic dump; regenerate with the snippet in PLAN.md if needed)
    data["profile"] = dict(
        subarray="core+spiral", fitted_fwhm_mas=285.7, memo121_fwhm_mas=147.7,
        r_arcsec=[0.0055, 0.0495, 0.0935, 0.1375, 0.1815, 0.2255, 0.2695,
                  0.3135, 0.3575, 0.4015, 0.4455, 0.4895, 0.5335, 0.5775,
                  0.6215, 0.6655, 0.7095, 0.7535, 0.7975, 0.8415, 0.8855,
                  0.9295, 0.9735, 1.0175, 1.0615, 1.1055, 1.1495, 1.1935,
                  1.2375, 1.2815, 1.3255, 1.3695, 1.4135, 1.4575, 1.5015,
                  1.5455, 1.5895, 1.6335],
        psf=[1.000, 0.754, 0.537, 0.468, 0.395, 0.342, 0.291, 0.249, 0.209,
             0.176, 0.147, 0.120, 0.100, 0.080, 0.070, 0.058, 0.050, 0.048,
             0.042, 0.038, 0.039, 0.039, 0.035, 0.033, 0.036, 0.038, 0.036,
             0.032, 0.029, 0.026, 0.028, 0.024, 0.019, 0.016, 0.016, 0.016,
             0.018, 0.018])

    # QA cross-check vs the sensitivity calculator's native beams
    data["qa"] = [
        dict(sa="core", nat_sim=710.1, nat_calc=725.6, skirt_nat=0.116),
        dict(sa="spiral", nat_sim=76.13, nat_calc=76.15, skirt_nat=0.088),
        dict(sa="mid", nat_sim=2.96, nat_calc=2.91, skirt_nat=0.227),
        dict(sa="core+spiral", nat_sim=285.7, nat_calc=147.7, skirt_nat=0.274),
        dict(sa="spiral+mid", nat_sim=11.12, nat_calc=4.37, skirt_nat=0.308),
        dict(sa="core+mid", nat_sim=17.81, nat_calc=None, skirt_nat=0.507),
        dict(sa="main", nat_sim=None, nat_calc=2.42, skirt_nat=None),
    ]

    with open(TEMPLATE) as f:
        html = f.read()
    html = html.replace("__DATA__", json.dumps(data))
    with open(out_path, "w") as f:
        f.write(html)
    print("wrote", out_path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "revf-curves.html")

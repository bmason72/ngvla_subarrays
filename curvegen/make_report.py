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

sys.path.insert(0, REPO)                    # for the shared curve engine
from sa_select.envelope import Envelope, ETA_CAP   # noqa: E402

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "report_template.html")

# fixed series order & display names (color slots assigned in the template;
# deferred subarrays keep their slots so colors never re-map)
ORDER = ["core", "spiral", "mid", "core+spiral", "spiral+mid",
         "main", "core-inner"]   # core+mid measured but dropped (see collect.py)
DEFERRED = []    # all 8 subarrays live (heterogeneous rework landed 6 Jul 2026)


GRID_DEX = 0.01      # target-resolution grid spacing of the plotted curves
MARK_EVERY = 8       # cadence of tooltip markers along smooth curve runs


def build_curve(samples, skirt_max=None):
    """The curve as the shared engine computes it: at each target resolution
    on a fine log grid, the cheapest interpolated-family operating point at
    EXACTLY that resolution (see sa_select/envelope.py; this replaced the
    sliding-window sample min after the 6 Jul 2026 anomaly post-mortem).

    Angular resolution is the primary requirement: where nothing under the
    skirt threshold exists at some resolution, the criterion is RELAXED to
    the best achievable skirt there (memo 121's 'partial' cases) and the
    point is flagged relaxed=True.  Real coverage gaps stay gaps.

    Each point carries: the interpolated (weighting, robust, taper), its
    measured anchor keys (env_keys, for the lattice heatmaps), and a marker
    flag (tooltip markers at winner changes and every MARK_EVERY points).
    """
    curve = []
    prev_key, run = None, 0
    for c in Envelope(samples).curve(skirt_max=skirt_max, grid_dex=GRID_DEX):
        key = (c.weighting, c.robust, c.relaxed, c.traded)
        run = run + 1 if key == prev_key else 0
        curve.append(dict(
            res=c.res, eta=c.eta, skirt=c.skirt, weighting=c.weighting,
            robust=c.robust, taper=c.taper, relaxed=c.relaxed,
            traded=c.traded,
            marker=(run % MARK_EVERY == 0),
            env_keys=[(a.weighting, a.robust, a.taper) for a in c.anchors],
        ))
        prev_key = key
    return curve


def build_heatmap(samples, imaging_curve):
    """The (robust, taper) lattice as a rectangular cell table.

    Columns are the v2 lattice tapers (values appearing in >= 6 rows of the
    lattice -- this drops stray v1-era taper values, which sit in only one
    or two rows).  Rows are natural + robust descending (+2 -> -2), i.e.
    from the sensitivity edge toward uniform weighting.  Cells absent from
    the results (pruned by the eta cap / edge convergence) are null.
    """
    from collections import Counter
    tcount = Counter(s["taper"] for s in samples)
    tapers = sorted(t for t, c in tcount.items() if t == 0.0 or c >= 6)
    # a lattice cell is "on the envelope" when it anchors an imaging-curve
    # interpolant (curve points themselves sit between cells)
    on_env = set()
    for s in imaging_curve:
        on_env.update(tuple(k) for k in s.get("env_keys", []))

    def row_label(w, r):
        return "natural" if w == "natural" else "%+.1f" % r

    rows = []
    robusts = sorted({s["robust"] for s in samples
                      if s["weighting"] == "briggs"}, reverse=True)
    for w, r in [("natural", None)] + [("briggs", r) for r in robusts]:
        cells = []
        for t in tapers:
            m = [s for s in samples if s["weighting"] == w and
                 s["robust"] == r and abs(s["taper"] - t) < 1e-6]
            if not m:
                cells.append(None)
            else:
                s = m[0]
                cells.append(dict(eta=s["eta"], skirt=s["skirt"], res=s["res"],
                                  env=(w, r, s["taper"]) in on_env))
        # stray robust values from the v1 sweeps populate almost no lattice
        # columns; keep only substantive rows
        if sum(c is not None for c in cells) >= 3:
            rows.append(dict(label=row_label(w, r), cells=cells))
    return dict(tapers=tapers, rows=rows)


def build_sens_table(las):
    """{subarray: {freq_ghz: [...], sigma_nat_ujy: [...]}} -- natural rms in
    microJy/beam for 1 h in a 1 MHz channel, per offered subarray, on a
    0.02-dex grid over the ngVLA receiver ranges (1.2-50.5, 70-116 GHz).
    Uses the line-mode calculator path (no continuum band re-centering) via
    sa_select.sensitivity, incl. donor rescaling for subarrays the memo-96
    calculator lacks."""
    import csv as _csv
    import math
    from sa_select import sensitivity as sens

    calc_names = {}
    with open(os.path.join(REPO, "sa_select", "data", "subarrays.csv")) as f:
        for r in _csv.DictReader(f):
            calc_names[r["name"]] = r["calc_name"].strip() or r["name"]

    freqs = []
    for lo, hi in ((1.2, 50.5), (70.0, 116.0)):
        x = math.log10(lo)
        while 10 ** x < hi:
            freqs.append(round(10 ** x, 4))
            x += 0.02
        freqs.append(hi)

    C_M_S = 2.99792458e8
    out = {}
    for name in ORDER:
        calc = calc_names.get(name, name)
        sig = []
        for f_ghz in freqs:
            try:
                delta_v = C_M_S * 1e6 / (f_ghz * 1e9)     # 1 MHz channel
                s = sens.natural_rms(calc, f_ghz, t_obs_hr=1.0,
                                     delta_v=delta_v)
                sig.append(round(s * 1e6, 4))             # uJy/beam
            except ValueError:
                sig.append(None)                          # outside a band edge
        out[name] = dict(freq_ghz=freqs, sigma_nat_ujy=sig)
    return out


def main(out_path):
    samples_by = {name: [] for name in ORDER}
    with open(os.path.join(REPO, "sa_select", "data", "revf_curves.csv")) as f:
        for r in csv.DictReader(f):
            s = dict(
                res=float(r["resolution_arcsec_30ghz"]) * 1e3,   # mas
                eta=float(r["eta"]),
                skirt=float(r["skirt"]) if r["skirt"] else None,
                weighting=r["weighting"],
                robust=float(r["robust"]) if r["robust"] else None,
                taper=float(r["taper_arcsec_30ghz"]) * 1e3
                      if r["taper_arcsec_30ghz"] else 0.0,
            )
            if s["eta"] <= ETA_CAP:      # the eta > ~5 regime is not of interest
                samples_by[r["subarray"]].append(s)

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

    imaging = {n: build_curve(samples_by[n], 0.10) for n in ORDER}
    heatmaps = {n: build_heatmap(samples_by[n], imaging[n])
                for n in ORDER if samples_by[n]}
    for curve in imaging.values():          # anchors only feed the heatmaps
        for p in curve:
            p.pop("env_keys", None)
    pointsource = {n: build_curve(samples_by[n]) for n in ORDER}
    for curve in pointsource.values():
        for p in curve:
            p.pop("env_keys", None)
    data = dict(order=ORDER, deferred=DEFERRED, las=las, samples=samples_by,
                imaging=imaging,
                pointsource=pointsource,
                counts={n: len(samples_by[n]) for n in ORDER},
                heatmaps=heatmaps)

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

    # natural-weighting point-source rms basis for the in-page calculator:
    # sigma_nat (Jy/beam) for 1 h on-source in a 1 MHz channel, on a log
    # frequency grid over the receiver bands.  Scales exactly as
    # 1/sqrt(bandwidth * time); the page applies the curve engine's eta.
    data["sens"] = build_sens_table(las)

    # QA cross-check vs the sensitivity calculator's native beams
    data["qa"] = [
        dict(sa="core-inner", nat_sim=2036.65, nat_calc=None, skirt_nat=0.104),
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

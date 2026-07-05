"""
Sweep the (weighting, robust, taper) grid for one subarray: tclean each point
(niter=0 -> dirty image + PSF), measure beam / rms / skirt, append to the
results CSV, delete the image products.

Resumable: grid points already present in results/<subarray>.csv are skipped,
so a killed run (or an extended grid in config.py) just picks up where it
left off.  Failures are caught and recorded with status=failed so one bad
point never aborts a sweep (PLAN.md section 9).

Run (from the curvegen/ directory, CASA's python3):
  .../python3 sweep.py core            # simulate if needed, then sweep
  .../python3 sweep.py core --limit 4  # first 4 pending points (pilot)
  .../python3 sweep.py core --dry-run  # list pending points and exit
"""

import argparse
import csv
import os
import shutil
import sys
import time
import traceback

import numpy as np
import casatools
from casatasks import tclean, casalog

from config import (SUBARRAYS, IMSIZE, OVERSAMPLE, WORK_DIR, RESULTS_DIR,
                    grid_points)
from simulate import make_ms
from measure import beam_arcsec, image_rms, psf_skirt

FIELDS = ["subarray", "weighting", "robust", "taper_mas", "imsize",
          "cell_arcsec", "bmaj_arcsec", "bmin_arcsec", "bpa_deg",
          "res_geo_arcsec", "sigma_dirty", "skirt", "status", "error",
          "elapsed_s"]

TCLEAN_EXTS = [".psf", ".image", ".residual", ".pb", ".sumwt", ".model",
               ".mask", ".weight"]


def point_key(weighting, robust, taper_mas):
    return "%s_%.2f_%.3f" % (weighting, robust, taper_mas)


def done_keys(results_path):
    """Keys of points already measured successfully (failed ones re-run)."""
    done = set()
    if os.path.isfile(results_path):
        with open(results_path, newline="") as f:
            for row in csv.DictReader(f):
                if row["status"] == "ok":
                    done.add(point_key(row["weighting"], float(row["robust"]),
                                       float(row["taper_mas"])))
    return done


def append_row(results_path, row):
    new = not os.path.isfile(results_path)
    with open(results_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def advise_cell(vis, oversample=OVERSAMPLE):
    """Cell size in arcsec from im.advise (same recipe as tclean_wrapper.py)."""
    im = casatools.imager()
    im.open(vis)
    adv = im.advise()
    im.close()
    return adv[2]["value"] * 2.0 / oversample


def cell_string(cell_arcsec):
    """Format like tclean_wrapper.py: enough decimals for tiny cells."""
    try:
        prec = int("{0:.1e}".format(cell_arcsec).split("e-")[1]) + 1
    except IndexError:
        prec = 1
    return "{0:.{prec}f}arcsec".format(cell_arcsec, prec=prec)


def run_point(vis, workdir, subarray, weighting, robust, taper_mas,
              imsize, cell_arcsec):
    """tclean one grid point and measure it; returns a results row."""
    # large natural tapers get a coarser (adaptive) cell so the beam still
    # fits comfortably in the image (cf. --cs_adapt in the old pipeline)
    cell_pt = cell_arcsec
    if weighting == "natural" and taper_mas > 0:
        cell_pt = max(cell_arcsec, taper_mas / OVERSAMPLE / 1e3)

    name = os.path.join(workdir, "pt_" + point_key(weighting, robust, taper_mas))
    uvtaper = [] if taper_mas == 0 else \
        ["%gmarcsec" % taper_mas, "%gmarcsec" % taper_mas, "0deg"]
    t0 = time.time()
    tclean(vis=vis, imagename=name, cell=cell_string(cell_pt), imsize=imsize,
           datacolumn="data", weighting=weighting, robust=robust,
           uvtaper=uvtaper, niter=0, savemodel="none", pblimit=-0.02)
    bmaj, bmin, bpa = beam_arcsec(name + ".image")
    res_geo = np.sqrt(bmaj * bmin)
    sigma = image_rms(name + ".image")
    skirt, _ = psf_skirt(name + ".psf", res_geo)
    for ext in TCLEAN_EXTS:
        if os.path.isdir(name + ext):
            shutil.rmtree(name + ext)
    return dict(subarray=subarray, weighting=weighting, robust=robust,
                taper_mas=taper_mas, imsize=imsize,
                cell_arcsec="%.6g" % cell_pt,
                bmaj_arcsec="%.6g" % bmaj, bmin_arcsec="%.6g" % bmin,
                bpa_deg="%.4g" % bpa, res_geo_arcsec="%.6g" % res_geo,
                sigma_dirty="%.6g" % sigma, skirt="%.4g" % skirt,
                status="ok", error="", elapsed_s="%.1f" % (time.time() - t0))


def sweep(subarray, limit=None, dry_run=False):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    results_path = os.path.join(RESULTS_DIR, subarray.replace("+", "_") + ".csv")
    pts = grid_points(subarray)
    done = done_keys(results_path)
    pending = [p for p in pts
               if point_key(*p) not in done]
    print("%s: %d grid points, %d done, %d pending"
          % (subarray, len(pts), len(done), len(pending)))
    if dry_run or not pending:
        for p in pending:
            print("  pending:", p)
        return
    if limit:
        pending = pending[:limit]

    vis = make_ms(subarray)                      # reuses existing MS
    workdir = os.path.join(WORK_DIR, subarray.replace("+", "_"))
    os.makedirs(workdir, exist_ok=True)
    casalog.setlogfile(os.path.join(workdir, "casa.log"))
    imsize = IMSIZE[subarray]
    cell = advise_cell(vis)
    print("imsize %d, native cell %.6g arcsec" % (imsize, cell))

    for i, (weighting, robust, taper) in enumerate(pending):
        label = point_key(weighting, robust, taper)
        print("[%d/%d] %s ..." % (i + 1, len(pending), label), flush=True)
        try:
            row = run_point(vis, workdir, subarray, weighting, robust, taper,
                            imsize, cell)
        except Exception as e:
            traceback.print_exc()
            row = dict(subarray=subarray, weighting=weighting, robust=robust,
                       taper_mas=taper, imsize=imsize, cell_arcsec="",
                       bmaj_arcsec="", bmin_arcsec="", bpa_deg="",
                       res_geo_arcsec="", sigma_dirty="", skirt="",
                       status="failed", error=str(e)[:200], elapsed_s="")
            # clean up any partial products
            for f in os.listdir(workdir):
                if f.startswith("pt_" + label):
                    shutil.rmtree(os.path.join(workdir, f), ignore_errors=True)
        append_row(results_path, row)
        if row["status"] == "ok":
            print("    beam %s\" eta-ref sigma %s skirt %s  (%ss)"
                  % (row["res_geo_arcsec"], row["sigma_dirty"], row["skirt"],
                     row["elapsed_s"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("subarray", choices=sorted(SUBARRAYS))
    ap.add_argument("--limit", type=int, default=None,
                    help="run at most N pending points")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sweep(args.subarray, limit=args.limit, dry_run=args.dry_run)

"""
Sweep the (robust, taper) lattice for one subarray: tclean each point
(niter=0 -> dirty image + PSF), measure beam / rms / skirt, append to the
results CSV, delete the image products.

How a sweep runs (v2 -- see config.py for the grid rationale):
  1. the two SEED points (natural and robust=-2, both untapered) run first;
     their beams anchor the subarray's taper grid, and the natural seed's
     rms is the eta = 1 reference;
  2. the lattice is walked row by row (a row = one weighting/robust value,
     tapers ascending); each point's eta is computed on the fly, and once a
     row exceeds ETA_CAP the rest of the row is recorded as 'skipped';
  3. everything is resumable: measured and skipped points are read back
     from results/<subarray>.csv and never re-run, so a killed run or an
     extended grid just picks up where it left off.  Failures are caught
     and recorded (status=failed) so one bad point never aborts a sweep.

Run (from the curvegen/ directory, CASA's python3):
  .../python3 sweep.py core             # simulate if needed, then sweep
  .../python3 sweep.py core --limit 4   # at most 4 new points (pilot)
  .../python3 sweep.py core --dry-run   # list pending points and exit
"""

import argparse
import csv
import os
import shutil
import time
import traceback

import numpy as np
import casatools
from casatasks import tclean, casalog

from config import (SUBARRAYS, IMSIZE, OVERSAMPLE, WORK_DIR, RESULTS_DIR,
                    SEEDS, ETA_CAP, grid_rows)
from simulate import make_ms
from measure import beam_arcsec, image_rms, psf_skirt

FIELDS = ["subarray", "weighting", "robust", "taper_mas", "imsize",
          "cell_arcsec", "bmaj_arcsec", "bmin_arcsec", "bpa_deg",
          "res_geo_arcsec", "sigma_dirty", "skirt", "status", "error",
          "elapsed_s"]

TCLEAN_EXTS = [".psf", ".image", ".residual", ".pb", ".sumwt", ".model",
               ".mask", ".weight"]


def point_key(weighting, robust, taper_mas):
    return "%s_%.2f_%.3f" % (weighting, float(robust), float(taper_mas))


def read_results(results_path):
    """{key: row} for every point already recorded (ok, failed or skipped)."""
    rows = {}
    if os.path.isfile(results_path):
        with open(results_path, newline="") as f:
            for row in csv.DictReader(f):
                rows[point_key(row["weighting"], row["robust"],
                               row["taper_mas"])] = row
    return rows


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


class Sweep:
    def __init__(self, subarray, limit=None):
        self.subarray = subarray
        self.limit = limit
        self.n_run = 0
        self.results_path = os.path.join(
            RESULTS_DIR, subarray.replace("+", "_").replace("-", "_") + ".csv")
        # keep backward compatibility with v1 result filenames (no '-')
        legacy = os.path.join(RESULTS_DIR, subarray.replace("+", "_") + ".csv")
        if os.path.isfile(legacy):
            self.results_path = legacy
        os.makedirs(RESULTS_DIR, exist_ok=True)
        self.rows = read_results(self.results_path)
        self.vis = None
        self.workdir = os.path.join(
            WORK_DIR, subarray.replace("+", "_").replace("-", "_"))
        self.imsize = IMSIZE[subarray]
        self.cell = None

    # -- lazy CASA setup so --dry-run stays cheap ------------------------- #
    def ensure_ready(self):
        if self.vis is None:
            self.vis = make_ms(self.subarray)
            os.makedirs(self.workdir, exist_ok=True)
            casalog.setlogfile(os.path.join(self.workdir, "casa.log"))
            self.cell = advise_cell(self.vis)
            print("imsize %d, native cell %.6g arcsec"
                  % (self.imsize, self.cell))

    def record(self, row):
        append_row(self.results_path, row)
        self.rows[point_key(row["weighting"], row["robust"],
                            row["taper_mas"])] = row

    def measured(self, weighting, robust, taper):
        row = self.rows.get(point_key(weighting, robust, taper))
        return row if row and row["status"] == "ok" else None

    # -- run one lattice point --------------------------------------------- #
    def run_point(self, weighting, robust, taper_mas):
        key = point_key(weighting, robust, taper_mas)
        if key in self.rows:               # ok, failed or skipped: don't redo
            return self.rows[key]
        if self.limit is not None and self.n_run >= self.limit:
            return None
        self.ensure_ready()
        self.n_run += 1
        print("  %s ..." % key, flush=True)

        # large tapers get a coarser (adaptive) cell so the beam stays well
        # resolved without a huge image (cf. --cs_adapt in the old pipeline)
        cell_pt = max(self.cell, taper_mas / OVERSAMPLE / 1e3)
        name = os.path.join(self.workdir, "pt_" + key)
        uvtaper = [] if taper_mas == 0 else \
            ["%gmarcsec" % taper_mas, "%gmarcsec" % taper_mas, "0deg"]
        t0 = time.time()
        try:
            tclean(vis=self.vis, imagename=name, cell=cell_string(cell_pt),
                   imsize=self.imsize, datacolumn="data", weighting=weighting,
                   robust=robust, uvtaper=uvtaper, niter=0, savemodel="none",
                   pblimit=-0.02)
            bmaj, bmin, bpa = beam_arcsec(name + ".image")
            res_geo = float(np.sqrt(bmaj * bmin))
            sigma = image_rms(name + ".image")
            skirt, _ = psf_skirt(name + ".psf", res_geo)
            row = dict(subarray=self.subarray, weighting=weighting,
                       robust=robust, taper_mas=taper_mas, imsize=self.imsize,
                       cell_arcsec="%.6g" % cell_pt,
                       bmaj_arcsec="%.6g" % bmaj, bmin_arcsec="%.6g" % bmin,
                       bpa_deg="%.4g" % bpa, res_geo_arcsec="%.6g" % res_geo,
                       sigma_dirty="%.6g" % sigma, skirt="%.4g" % skirt,
                       status="ok", error="",
                       elapsed_s="%.1f" % (time.time() - t0))
        except Exception as e:
            traceback.print_exc()
            row = dict(subarray=self.subarray, weighting=weighting,
                       robust=robust, taper_mas=taper_mas, imsize=self.imsize,
                       cell_arcsec="", bmaj_arcsec="", bmin_arcsec="",
                       bpa_deg="", res_geo_arcsec="", sigma_dirty="",
                       skirt="", status="failed", error=str(e)[:200],
                       elapsed_s="")
        finally:
            for ext in TCLEAN_EXTS:
                shutil.rmtree(name + ext, ignore_errors=True)
        self.record(row)
        return row

    def skip_point(self, weighting, robust, taper_mas, why):
        key = point_key(weighting, robust, taper_mas)
        if key in self.rows:
            return
        self.record(dict(subarray=self.subarray, weighting=weighting,
                         robust=robust, taper_mas=taper_mas,
                         imsize=self.imsize, cell_arcsec="", bmaj_arcsec="",
                         bmin_arcsec="", bpa_deg="", res_geo_arcsec="",
                         sigma_dirty="", skirt="", status="skipped",
                         error=why, elapsed_s=""))

    # -- the sweep ----------------------------------------------------------- #
    def run(self, dry_run=False):
        # seeds first: they anchor the grid and the eta reference
        for weighting, robust, taper in SEEDS:
            if not self.measured(weighting, robust, taper):
                if dry_run:
                    print("  seed pending:", point_key(weighting, robust, taper))
                    return
                if self.run_point(weighting, robust, taper) is None:
                    return                       # --limit exhausted
        nat = self.measured(*SEEDS[0])
        fine = self.measured(*SEEDS[1])
        if not (nat and fine):
            print("seed point failed -- fix before sweeping"); return
        sigma_nat = float(nat["sigma_dirty"])
        res_nat = float(nat["res_geo_arcsec"]) * 1e3     # mas
        res_fine = float(fine["res_geo_arcsec"]) * 1e3
        rows = grid_rows(res_fine, res_nat)
        n_total = sum(len(t) for _, _, t in rows)
        n_have = len(self.rows)
        print("%s: lattice %d points (res_fine %.4g mas, res_nat %.4g mas); "
              "%d already recorded" % (self.subarray, n_total, res_fine,
                                       res_nat, n_have))
        if dry_run:
            return
        nat_row = {}          # taper -> natural-row measurement, filled first
        for weighting, robust, tapers in rows:
            capped = None
            for taper in tapers:
                if capped:
                    self.skip_point(weighting, robust, taper, capped)
                    continue
                row = self.run_point(weighting, robust, taper)
                if row is None:
                    print("stopping: --limit reached"); return
                if row["status"] == "ok":
                    eta = float(row["sigma_dirty"]) / sigma_nat
                    print("    beam %s\"  eta %.3f  skirt %s  (%ss)"
                          % (row["res_geo_arcsec"], eta, row["skirt"],
                             row["elapsed_s"]))
                    if weighting == "natural":
                        nat_row[taper] = row
                    if eta > ETA_CAP:
                        capped = "eta cap %.2g exceeded earlier in row" % ETA_CAP
                    # once a briggs row has converged onto the natural+taper
                    # edge (same beam, same eta), larger tapers add nothing
                    nr = nat_row.get(taper)
                    if weighting == "briggs" and nr and taper > 0:
                        eta_n = float(nr["sigma_dirty"]) / sigma_nat
                        res_b = float(row["res_geo_arcsec"])
                        res_n = float(nr["res_geo_arcsec"])
                        if (abs(eta / eta_n - 1) < 0.01
                                and abs(res_b / res_n - 1) < 0.02):
                            capped = "converged to natural+taper edge"
        n_ok = sum(1 for r in self.rows.values() if r["status"] == "ok")
        n_skip = sum(1 for r in self.rows.values() if r["status"] == "skipped")
        n_fail = sum(1 for r in self.rows.values() if r["status"] == "failed")
        print("%s done: %d ok, %d skipped (eta cap), %d failed"
              % (self.subarray, n_ok, n_skip, n_fail))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("subarray", choices=sorted(SUBARRAYS))
    ap.add_argument("--limit", type=int, default=None,
                    help="run at most N new points")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    Sweep(args.subarray, limit=args.limit).run(dry_run=args.dry_run)

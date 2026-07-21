"""
Sweep the (robust, taper) lattice for one subarray: tclean each point
(niter=0 -> dirty image + PSF), measure beam / rms / skirt, append to the
results CSV, delete the image products.

How a sweep runs (v2 -- see config.py for the grid rationale):
  1. the two SEED points (natural and robust=-2, both untapered) run first;
     their beams anchor the subarray's taper grid, and the natural seed's
     rms is the eta = 1 reference;
  2. the lattice is walked row by row (a row = one weighting/robust value,
     tapers ascending) and EVERY cell is measured -- the full grid (bmason
     8 Jul 2026).  The only early-stop is the heterogeneous beam cap: after two
     consecutive points whose beam exceeds BEAM_CAP_ARCSEC the rest of the row
     is recorded 'skipped' (a composite tapered into its coarse component's
     regime is a false economy);
  3. everything is resumable: measured and skipped points are read back
     from results/<subarray>.csv and never re-run, so a killed run or an
     extended grid just picks up where it left off.  Failures are caught
     and recorded (status=failed) so one bad point never aborts a sweep.

PSF radial profiles: when config.CAPTURE_PROFILES is on, every successfully
imaged point also appends one JSON line ({"key": ..., "res_geo_arcsec": ...,
"r_arcsec": [...], "psf": [...], plus the fitted beam and major/minor-axis
cuts: "bmaj_arcsec", "bmin_arcsec", "bpa_deg", "cut_r_arcsec", "cut_maj",
"cut_min"}) to PROFILE_DIR/<subarray file stem>.jsonl before the image
products are deleted.  Appends are keyed by the lattice point: a re-measured
point may append a second line, so consumers must take the LAST line per
key.  A profile-capture failure never fails or skips the sweep point
(one-line warning only); a cuts-only failure degrades to an azimuthal-only
line (older lines, from before the cuts existed, are azimuthal-only too and
stay valid).

Run (from the curvegen/ directory, CASA's python3):
  .../python3 sweep.py core             # simulate if needed, then sweep
  .../python3 sweep.py core --limit 4   # at most 4 new points (pilot)
  .../python3 sweep.py core --dry-run   # list pending points and exit
"""

import argparse
import csv
import glob
import json
import os
import shutil
import sys
import time
import traceback

import numpy as np
import casatools
from casatasks import tclean, casalog

from config import (SUBARRAYS, IMSIZE, OVERSAMPLE, WORK_DIR, RESULTS_DIR,
                    SEEDS, BEAM_CAP_ARCSEC, MIN_UVRANGE_M, grid_rows,
                    CAPTURE_PROFILES, PROFILE_DIR)
from simulate import make_ms
from measure import (beam_arcsec, image_rms, psf_skirt, psf_radial_profile,
                    psf_axis_cuts_from_psf)

FIELDS = ["subarray", "weighting", "robust", "taper_mas", "imsize",
          "cell_arcsec", "bmaj_arcsec", "bmin_arcsec", "bpa_deg",
          "res_geo_arcsec", "sigma_dirty", "skirt", "status", "error",
          "elapsed_s"]

TCLEAN_EXTS = [".psf", ".image", ".residual", ".pb", ".sumwt", ".model",
               ".mask", ".weight"]


def point_key(weighting, robust, taper_mas):
    # "%.2f" % -0.0 -> "-0.00", which would spawn a DUPLICATE lattice row for
    # the same coordinate (this is the class of gotcha export_psf_data.
    # normalize_key patches after the fact).  Coerce any value that ROUNDS to
    # zero to +0.0 before formatting: byte-identical to the old spelling for
    # every non-zero value, and folds a -0.00 robust/taper into 0.00 here at
    # the source.  Keys are derived at load time, not stored, so existing data
    # is unaffected (and a grep found no -0.00 keys in the current results).
    robust, taper_mas = float(robust), float(taper_mas)
    if round(robust, 2) == 0.0:
        robust = 0.0
    if round(taper_mas, 3) == 0.0:
        taper_mas = 0.0
    return "%s_%.2f_%.3f" % (weighting, robust, taper_mas)


def _sig5(v):
    """Round a float to 5 significant digits (compact profile JSON)."""
    return float("%.5g" % float(v))


def result_shards(results_path):
    """Shard files belonging to a canonical results CSV."""
    return sorted(glob.glob(results_path + ".shard_*.csv"))


def _warn_bad_row(path, line_num, why):
    print("warning: skipping malformed result row in %s line %s: %s"
          % (path, line_num, why), file=sys.stderr)


def _validated_key(row, path, line_num, strict):
    if row.get(None) is not None:
        if strict:
            raise ValueError("extra CSV fields in %s line %s" % (path, line_num))
        _warn_bad_row(path, line_num, "wrong field count")
        return None
    missing = [f for f in FIELDS if row.get(f) is None]
    if missing:
        if strict:
            raise ValueError("missing CSV fields in %s line %s" % (path, line_num))
        _warn_bad_row(path, line_num, "wrong field count")
        return None
    try:
        return point_key(row["weighting"], row["robust"], row["taper_mas"])
    except Exception as e:
        if strict:
            raise
        _warn_bad_row(path, line_num, str(e))
        return None


def read_results(results_path, extra_paths=None, strict=True):
    """{key: row} for every point already recorded (ok, failed or skipped)."""
    rows = {}
    for i, path in enumerate([results_path] + list(extra_paths or [])):
        if os.path.isfile(path):
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = _validated_key(row, path, reader.line_num, strict)
                    if key is None:
                        continue
                    if (i == 0 or key not in rows
                            or (rows[key].get("status") == "skipped"
                                and row.get("status") != "skipped")):
                        rows[key] = row
    return rows


def append_row(results_path, row):
    new = not os.path.isfile(results_path)
    dirname = os.path.dirname(results_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(results_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def parse_row_spec(spec):
    """argparse converter for --only-row values like 'briggs:-1.2'."""
    try:
        weighting, robust = spec.split(":", 1)
        robust = float(robust)
    except ValueError:
        raise argparse.ArgumentTypeError("expected W:R, e.g. briggs:-1.2")
    if weighting not in ("natural", "briggs"):
        raise argparse.ArgumentTypeError("weighting must be natural or briggs")
    return weighting, robust


def load_points_file(path):
    """Load explicit lattice points for --points-file.

    JSON files may contain either [weighting, robust, taper_mas] triples or
    dictionaries with those field names.  CSV files use the same field names.
    """
    points = []
    if path.endswith(".csv"):
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                points.append((row["weighting"], row["robust"],
                               row["taper_mas"]))
    else:
        with open(path) as f:
            data = json.load(f)
        for item in data:
            if isinstance(item, dict):
                points.append((item["weighting"], item["robust"],
                               item["taper_mas"]))
            else:
                weighting, robust, taper = item
                points.append((weighting, robust, taper))

    out = []
    for weighting, robust, taper in points:
        if weighting not in ("natural", "briggs"):
            raise RuntimeError("bad points-file weighting: %s" % weighting)
        out.append((weighting, float(robust), float(taper)))
    return out


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


def tclean_kwargs(vis, imagename, weighting, robust, taper_mas, imsize,
                  cell_arcsec, min_uvrange_m):
    """The SINGLE, canonical tclean keyword set for a curve dirty image
    (niter=0 -> dirty image + PSF).  Both `Sweep.run_point` and
    `backfill_psf.py` build the call here so the two can never silently drift
    apart (backfill re-images a curve anchor to capture its PSF profile, and it
    must use exactly the convention the anchor was measured with).

    `cell_arcsec` is the already-decided cell -- run_point's adaptive `cell_pt`
    when sweeping, or a recorded results-CSV row's `cell_arcsec` when
    backfilling; it is NEVER recomputed here.  `min_uvrange_m` is the
    subarray's spurious-short-baseline cut: filtering LONG's ~3-antenna
    clusters (uvrange ">Nm") so beam/rms/skirt come from the real long-baseline
    uv coverage, applied uniformly (incl. the natural seed) so eta stays
    self-consistent.  taper_mas == 0 means no uv taper.
    """
    uvtaper = [] if taper_mas == 0 else \
        ["%gmarcsec" % taper_mas, "%gmarcsec" % taper_mas, "0deg"]
    uvrange = "" if min_uvrange_m is None else ">%gm" % min_uvrange_m
    return dict(vis=vis, imagename=imagename, cell=cell_string(cell_arcsec),
                imsize=imsize, datacolumn="data", weighting=weighting,
                robust=robust, uvtaper=uvtaper, uvrange=uvrange, niter=0,
                savemodel="none", pblimit=-0.02)


def run_tclean(**kwargs):
    """Execute one dirty-image tclean call built by `tclean_kwargs`.  Keeping
    the sole `tclean(...)` invocation here means the kwargs-parity between the
    sweep and the backfill can be tested by monkeypatching this module's
    `tclean`."""
    tclean(**kwargs)


class Sweep:
    def __init__(self, subarray, limit=None, record_path=None,
                 include_shards=False):
        self.subarray = subarray
        self.limit = limit
        self.n_run = 0
        self.results_path = os.path.join(
            RESULTS_DIR, subarray.replace("+", "_").replace("-", "_") + ".csv")
        self.record_path = record_path or self.results_path
        os.makedirs(RESULTS_DIR, exist_ok=True)
        extra = []
        if include_shards:
            extra = result_shards(self.results_path)
            if self.record_path != self.results_path and self.record_path not in extra:
                extra.append(self.record_path)
        self.rows = read_results(self.results_path, extra_paths=extra,
                                 strict=not include_shards)
        self.vis = None
        self.workdir = os.path.join(
            WORK_DIR, subarray.replace("+", "_").replace("-", "_"))
        self.imsize = IMSIZE[subarray]
        self.cell = None
        self.beam_cap = BEAM_CAP_ARCSEC.get(subarray)
        self.min_uvrange_m = MIN_UVRANGE_M.get(subarray)   # spurious-shorts cut

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
        append_row(self.record_path, row)
        self.rows[point_key(row["weighting"], row["robust"],
                            row["taper_mas"])] = row

    def measured(self, weighting, robust, taper):
        row = self.rows.get(point_key(weighting, robust, taper))
        return row if row and row["status"] == "ok" else None

    def row_complete(self, weighting, robust, tapers):
        return all(point_key(weighting, robust, t) in self.rows for t in tapers)

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
        t0 = time.time()
        try:
            # tclean_kwargs is the SINGLE place the dirty-image call is built
            # (see the module-level helper); backfill_psf.py re-images anchors
            # through the same helper with a byte-identical convention -- cell
            # here is the adaptive cell_pt, backfill passes the recorded cell.
            run_tclean(**tclean_kwargs(self.vis, name, weighting, robust,
                                       taper_mas, self.imsize, cell_pt,
                                       self.min_uvrange_m))
            bmaj, bmin, bpa = beam_arcsec(name + ".image")
            res_geo = float(np.sqrt(bmaj * bmin))
            sigma = image_rms(name + ".image")
            # degenerate-product guard (15 Jul 2026): a pathological tclean
            # run (e.g. snapshot LONG at extreme robust+taper) can "succeed"
            # with an empty image and a sentinel restoring beam (1e-6 arcsec,
            # sigma 0).  The MINOR axis is the binding sampling constraint
            # (snapshot/LONG beams are legitimately elongated): a fitted bmin
            # under ONE pixel, or a non-positive rms, is garbage and must be
            # recorded failed, never ok.  (Threshold is 1 cell, not 2: LONG's
            # far-coarse tapered rows legitimately fit bmin ~1.7 cells under
            # the adaptive-cell convention -- marginal but real; the sentinel
            # sits at ~0.001 cells.)
            geom = (bmaj, bmin, res_geo, sigma, cell_pt)
            if (any(not np.isfinite(v) or v <= 0 for v in geom)
                    or bmin < cell_pt):
                raise RuntimeError(
                    "degenerate tclean product: bmaj %.4g bmin %.4g res %.4g "
                    "arcsec, cell %.4g, rms %.4g"
                    % (bmaj, bmin, res_geo, cell_pt, sigma))
            if bmin < 3.0 * cell_pt:
                print("  warning: %s bmin %.4g arcsec only %.1f cells -- "
                      "marginally sampled minor axis"
                      % (key, bmin, bmin / cell_pt), file=sys.stderr)
            skirt, _ = psf_skirt(name + ".psf", res_geo)
            # beyond the beam cap the point is a measured diagnostic, not
            # usable curve data (collect.py exports only status="ok")
            status, err = "ok", ""
            if self.beam_cap is not None and res_geo > self.beam_cap:
                status = "capped"
                err = "beam %.4g > cap %.4g arcsec" % (res_geo, self.beam_cap)
            row = dict(subarray=self.subarray, weighting=weighting,
                       robust=robust, taper_mas=taper_mas, imsize=self.imsize,
                       cell_arcsec="%.6g" % cell_pt,
                       bmaj_arcsec="%.6g" % bmaj, bmin_arcsec="%.6g" % bmin,
                       bpa_deg="%.4g" % bpa, res_geo_arcsec="%.6g" % res_geo,
                       sigma_dirty="%.6g" % sigma, skirt="%.4g" % skirt,
                       status=status, error=err,
                       elapsed_s="%.1f" % (time.time() - t0))
            # compact radial profile, captured before the finally-block
            # cleanup deletes the PSF; a capture failure must never fail
            # or skip the point itself
            if CAPTURE_PROFILES:
                try:
                    self.capture_profile(key, name + ".psf", res_geo,
                                         beam=(bmaj, bmin, bpa))
                except Exception as pe:
                    print("warning: profile capture failed for %s: %s"
                          % (key, pe), file=sys.stderr)
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

    def capture_profile(self, key, psf_path, res_geo_arcsec, beam=None):
        """Append one profile JSON line for a measured point.

        Always writes the azimuthal radial profile.  When `beam` is given
        (bmaj_arcsec, bmin_arcsec, bpa_deg -- the already-fitted restoring
        beam, so this costs no extra tclean work) this also tries to add
        the beam and the major/minor-axis cuts; a cuts failure degrades to
        an azimuthal-only line rather than losing the whole point (the
        profile is a diagnostic capture, the sweep point is not).
        Consumers take the LAST line per key (re-measured points append).

        Returns True iff the major/minor-axis cut fields were written; False
        for an azimuthal-only line (no beam given, or the cut capture failed).
        run_point ignores this; backfill_psf REQUIRES cuts, so it uses the
        flag to tell a real cut-bearing capture from a swallowed fallback."""
        r, p = psf_radial_profile(psf_path, res_geo_arcsec)
        line_data = dict(key=key,
                         res_geo_arcsec=_sig5(res_geo_arcsec),
                         r_arcsec=[_sig5(v) for v in r],
                         psf=[_sig5(v) for v in p])
        cuts_ok = False
        if beam is not None:
            bmaj, bmin, bpa = beam
            try:
                cut_r, cut_maj, cut_min = psf_axis_cuts_from_psf(
                    psf_path, res_geo_arcsec, bpa)
                line_data.update(
                    bmaj_arcsec=_sig5(bmaj), bmin_arcsec=_sig5(bmin),
                    bpa_deg=_sig5(bpa),
                    cut_r_arcsec=[_sig5(v) for v in cut_r],
                    cut_maj=[None if v is None else _sig5(v)
                             for v in cut_maj],
                    cut_min=[None if v is None else _sig5(v)
                             for v in cut_min])
                cuts_ok = True
            except Exception as e:
                print("warning: axis-cut capture failed for %s: %s"
                      % (key, e), file=sys.stderr)
        os.makedirs(PROFILE_DIR, exist_ok=True)
        stem = self.subarray.replace("+", "_").replace("-", "_")
        line = json.dumps(line_data) + "\n"
        # one os.write on an O_APPEND descriptor: the best atomicity
        # available when parallel shard jobs (sweep_parallel.py /
        # fill_grid.py) append to the same file; interleaving is still
        # possible on a shared filesystem, so consumers should also skip
        # malformed lines (profiles are diagnostics, never curve data)
        fd = os.open(os.path.join(PROFILE_DIR, stem + ".jsonl"),
                     os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)
        return cuts_ok

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
    def ensure_seeds(self, dry_run=False, require_existing=False):
        # seeds first: they anchor the grid and the eta reference
        for weighting, robust, taper in SEEDS:
            if not self.measured(weighting, robust, taper):
                key = point_key(weighting, robust, taper)
                if require_existing:
                    raise RuntimeError("seed point missing or failed: %s" % key)
                if dry_run:
                    print("  seed pending:", key)
                    return None
                if self.run_point(weighting, robust, taper) is None:
                    return None                  # --limit exhausted
        nat = self.measured(*SEEDS[0])
        fine = self.measured(*SEEDS[1])
        if not (nat and fine):
            if require_existing:
                raise RuntimeError("seed point failed -- fix before sweeping")
            print("seed point failed -- fix before sweeping"); return None
        return nat, fine

    def prepare_lattice(self, dry_run=False, require_existing=False,
                        announce=True):
        seeds = self.ensure_seeds(dry_run=dry_run,
                                  require_existing=require_existing)
        if seeds is None:
            return None
        nat, fine = seeds
        sigma_nat = float(nat["sigma_dirty"])
        res_nat = float(nat["res_geo_arcsec"]) * 1e3     # mas
        res_fine = float(fine["res_geo_arcsec"]) * 1e3
        rows = grid_rows(res_fine, res_nat, self.subarray)
        n_total = sum(len(t) for _, _, t in rows)
        n_have = len(self.rows)
        if announce:
            print("%s: lattice %d points (res_fine %.4g mas, res_nat %.4g mas); "
                  "%d already recorded" % (self.subarray, n_total, res_fine,
                                           res_nat, n_have))
        return sigma_nat, res_fine, res_nat, rows

    def select_rows(self, rows, only_row):
        if only_row is None:
            return rows
        weighting, robust = only_row
        out = [r for r in rows
               if r[0] == weighting and abs(float(r[1]) - robust) < 1e-9]
        if not out:
            raise RuntimeError("row %s:%.2f is not in the lattice"
                               % (weighting, robust))
        return out

    def run(self, dry_run=False, only_row=None, require_seeds=None):
        if require_seeds is None:
            require_seeds = only_row is not None
        prepared = self.prepare_lattice(dry_run=dry_run,
                                        require_existing=require_seeds)
        if prepared is None:
            return False
        sigma_nat, _res_fine, _res_nat, rows = prepared
        rows = self.select_rows(rows, only_row)
        if dry_run:
            return True
        # FULL-GRID sweep (bmason 8 Jul 2026): every (robust, taper) cell is
        # measured -- the eta-cap and natural+taper-edge convergence prunes were
        # removed (they left holes that block bilinear-cell formation and
        # truncated the now-collected high-eta regime).  The ONLY early-stop is
        # the heterogeneous beam cap (a physics exclusion: a composite tapered
        # down into its coarse component's regime is a false economy), after two
        # consecutive capped points.
        for weighting, robust, tapers in rows:
            capped = None
            n_over_cap = 0    # consecutive beam-capped points in this row
            for taper in tapers:
                if capped:
                    self.skip_point(weighting, robust, taper, capped)
                    continue
                row = self.run_point(weighting, robust, taper)
                if row is None:
                    print("stopping: --limit reached"); return
                if row["status"] == "capped":
                    print("    beam %s\"  CAPPED (> %.3g\")  (%ss)"
                          % (row["res_geo_arcsec"], self.beam_cap,
                             row["elapsed_s"]))
                    n_over_cap += 1
                    if n_over_cap >= 2:
                        capped = ("beam cap %.3g arcsec exceeded earlier in row"
                                  % self.beam_cap)
                    continue
                if row["status"] == "ok":
                    n_over_cap = 0
                    eta = float(row["sigma_dirty"]) / sigma_nat
                    print("    beam %s\"  eta %.3f  skirt %s  (%ss)"
                          % (row["res_geo_arcsec"], eta, row["skirt"],
                             row["elapsed_s"]))
        n_ok = sum(1 for r in self.rows.values() if r["status"] == "ok")
        n_skip = sum(1 for r in self.rows.values() if r["status"] == "skipped")
        n_cap = sum(1 for r in self.rows.values() if r["status"] == "capped")
        n_fail = sum(1 for r in self.rows.values() if r["status"] == "failed")
        print("%s done: %d ok, %d skipped, %d beam-capped, %d failed"
              % (self.subarray, n_ok, n_skip, n_cap, n_fail))
        return True

    def run_points(self, points, allow_skipped=False):
        """Run an explicit point list with no row-walk pruning.

        This is for targeted fill-in jobs.  Normal resumability still holds:
        ok/failed/capped points are never re-run.  When allow_skipped=True,
        a selected skipped point is deliberately superseded by a new appended
        measurement row; unselected skipped points remain untouched.
        """
        prepared = self.prepare_lattice(require_existing=True, announce=False)
        if prepared is None:
            return False
        lattice = set()
        for weighting, robust, tapers in prepared[3]:
            for taper in tapers:
                lattice.add(point_key(weighting, robust, taper))

        ok = True
        for weighting, robust, taper in points:
            key = point_key(weighting, robust, taper)
            if key not in lattice:
                raise RuntimeError("points-file point is not in lattice: %s" % key)
            row = self.rows.get(key)
            if row is not None:
                if row["status"] == "skipped" and allow_skipped:
                    print("  %s superseding recorded skipped row" % key)
                    del self.rows[key]
                else:
                    print("  %s already status=%s; skipping"
                          % (key, row["status"]))
                    continue
            row = self.run_point(weighting, robust, taper)
            if row is None:
                ok = False
                break
            if row["status"] == "failed":
                ok = False
        return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("subarray", choices=sorted(SUBARRAYS))
    ap.add_argument("--limit", type=int, default=None,
                    help="run at most N new points")
    ap.add_argument("--seeds-only", action="store_true",
                    help="run ONLY the two seed points (natural + robust=-2, "
                         "untapered) and stop.  The seeds are cap- and "
                         "lattice-invariant, so this is the safe pre-cap pass: "
                         "it never writes a lattice point that a later "
                         "cap/N_TAPERS_HETERO change would strand or mis-cap.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only-row", type=parse_row_spec,
                    help="run only one lattice row, e.g. briggs:-1.2")
    ap.add_argument("--points-file",
                    help="run only explicit weighting/robust/taper points")
    ap.add_argument("--shard",
                    help="append newly recorded points to this CSV")
    args = ap.parse_args()
    if args.points_file and args.only_row:
        ap.error("--points-file cannot be combined with --only-row")
    if args.seeds_only and (args.only_row or args.points_file):
        ap.error("--seeds-only cannot be combined with --only-row/--points-file")
    include_shards = bool(args.only_row or args.shard or args.points_file)
    # --seeds-only ignores --limit (it runs exactly the seeds, no lattice)
    sweep = Sweep(args.subarray, limit=None if args.seeds_only else args.limit,
                  record_path=args.shard, include_shards=include_shards)
    try:
        if args.seeds_only:
            seeds = sweep.ensure_seeds(dry_run=args.dry_run)
            ok = seeds is not None
            if ok and not args.dry_run:
                print("%s: seeds ready (natural + robust=-2)" % args.subarray)
        elif args.points_file:
            if args.dry_run:
                ap.error("--dry-run is not supported with --points-file")
            ok = sweep.run_points(load_points_file(args.points_file),
                                  allow_skipped=True)
        else:
            ok = sweep.run(dry_run=args.dry_run, only_row=args.only_row)
    except RuntimeError as e:
        print("error:", e, file=sys.stderr)
        sys.exit(1)
    if (args.only_row or args.points_file or args.seeds_only) and not ok:
        sys.exit(1)

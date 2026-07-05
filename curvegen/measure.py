"""
Measurements on one tclean output: fitted beam, dirty-image rms, and the
PSF "skirt".

Skirt convention (memo 65 "metric 2b", adopted by memo 121 with a 10%
threshold): the azimuthally averaged radial profile of the PSF, interpolated
at a radius of ONE clean-beam FWHM.  We use the geometric-mean FWHM of the
fitted (restoring) beam as the radius, and a cubic spline through the annular
means, matching the memo-65 method (which used the iring task + spline).
For reference a pure Gaussian beam is ~6% at that radius.
"""

import numpy as np
import casatools
from scipy.interpolate import CubicSpline


def beam_arcsec(image_path):
    """(bmaj, bmin, bpa_deg) of the restoring beam, in arcsec."""
    ia = casatools.image()
    qa = casatools.quanta()
    ia.open(image_path)
    b = ia.restoringbeam()
    ia.close()
    return (qa.convert(b["major"], "arcsec")["value"],
            qa.convert(b["minor"], "arcsec")["value"],
            qa.convert(b["positionangle"], "deg")["value"])


def image_rms(image_path):
    """rms of the (noise-only) dirty image, via ia.statistics (memory-safe)."""
    ia = casatools.image()
    ia.open(image_path)
    st = ia.statistics()
    ia.close()
    return float(st["rms"][0])


def psf_skirt(psf_path, fwhm_arcsec, rmax_fwhm=2.5):
    """PSF level at radius = 1 x `fwhm_arcsec` (memo-65 metric 2b).

    Reads only a central cutout (+-rmax_fwhm x FWHM) so main-sized PSFs
    (15000^2 px) never load fully into memory.  Returns (skirt, profile)
    where profile is the (radius_arcsec, mean_psf) table for diagnostics.
    """
    ia = casatools.image()
    ia.open(psf_path)
    shape = ia.shape()
    cs = ia.coordsys()
    cell = abs(cs.increment()["numeric"][0]) * 206264.80624709636  # rad->arcsec
    cs.done()
    cx, cy = shape[0] // 2, shape[1] // 2
    half = int(np.ceil(rmax_fwhm * fwhm_arcsec / cell)) + 2
    half = min(half, cx, cy)
    blc = [cx - half, cy - half, 0, 0]
    trc = [cx + half, cy + half, 0, 0]
    cut = ia.getchunk(blc=blc, trc=trc)[:, :, 0, 0]
    ia.close()

    ny, nx = cut.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    r = np.hypot(xx - half, yy - half) * cell          # arcsec from PSF peak

    # annular means, one cell wide, out to rmax; then spline through them
    edges = np.arange(0.0, r.max(), cell)
    idx = np.digitize(r.ravel(), edges)
    flat = cut.ravel()
    radii, means = [], []
    for i in range(1, len(edges)):
        sel = idx == i
        if sel.any():
            radii.append(0.5 * (edges[i - 1] + edges[i]))
            means.append(flat[sel].mean())
    radii, means = np.array(radii), np.array(means)
    spline = CubicSpline(radii, means)
    skirt = float(spline(fwhm_arcsec))
    return skirt, np.column_stack([radii, means])

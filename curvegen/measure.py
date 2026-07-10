"""
Measurements on one tclean output: fitted beam, dirty-image rms, the
PSF "skirt", and a compact PSF radial profile.

Skirt convention (memo 65 "metric 2b", adopted by memo 121 with a 10%
threshold): the azimuthally averaged radial profile of the PSF, interpolated
at a radius of ONE clean-beam FWHM.  We use the geometric-mean FWHM of the
fitted (restoring) beam as the radius, and a cubic spline through the annular
means, matching the memo-65 method (which used the iring task + spline).
For reference a pure Gaussian beam is ~6% at that radius.

casatools is imported lazily inside the functions that need it, so the
pure-numpy pieces (radial_profile) stay importable without CASA
(tests/test_measure_profile.py runs CASA-free).
"""

import numpy as np
from scipy.interpolate import CubicSpline


def beam_arcsec(image_path):
    """(bmaj, bmin, bpa_deg) of the restoring beam, in arcsec."""
    import casatools
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
    import casatools
    ia = casatools.image()
    ia.open(image_path)
    st = ia.statistics()
    ia.close()
    return float(st["rms"][0])


def radial_profile(img, center_xy, cell_arcsec, r_max_arcsec, n_bins=40):
    """Azimuthally averaged radial profile of a 2-D array (pure numpy).

    `img` is any 2-D array, `center_xy` the (first-axis, second-axis) pixel
    coordinates of the profile center, `cell_arcsec` the pixel size.  The
    radius range [0, r_max_arcsec] is split into `n_bins` equal bins; empty
    bins (possible near the center when the bin width is below the pixel
    size) are dropped.  Returns (r_arcsec bin centers, mean values), both
    1-D float arrays of equal length.
    """
    img = np.asarray(img, dtype=float)
    c0, c1 = center_xy
    n0, n1 = img.shape
    yy, xx = np.mgrid[0:n0, 0:n1]
    r = np.hypot(yy - c0, xx - c1) * cell_arcsec
    edges = np.linspace(0.0, r_max_arcsec, n_bins + 1)
    idx = np.digitize(r.ravel(), edges)          # 1..n_bins in range
    idx[r.ravel() == edges[-1]] = n_bins         # right edge inclusive,
    flat = img.ravel()                           # like np.histogram
    radii, means = [], []
    for i in range(1, n_bins + 1):
        sel = idx == i
        if sel.any():
            radii.append(0.5 * (edges[i - 1] + edges[i]))
            means.append(flat[sel].mean())
    return np.array(radii), np.array(means)


def psf_radial_profile(imagename, res_geo_arcsec, n_bins=40):
    """Compact radial profile of a PSF, for capture at sweep time.

    Opens `imagename` the same way psf_skirt does (central cutout only, so
    main-sized PSFs never load fully into memory), profiles it out to
    r_max = 3 x `res_geo_arcsec`, and normalizes the profile to peak = 1.
    Returns (r_arcsec list, psf list).
    """
    import casatools
    ia = casatools.image()
    ia.open(imagename)
    try:                       # close even on error: run_point swallows
        shape = ia.shape()     # capture failures and then deletes the PSF,
        cs = ia.coordsys()     # so a leaked open handle would break cleanup
        cell = abs(cs.increment()["numeric"][0]) * 206264.80624709636  # arcsec
        cs.done()
        cx, cy = shape[0] // 2, shape[1] // 2
        r_max = 3.0 * res_geo_arcsec
        half = int(np.ceil(r_max / cell)) + 2
        half = min(half, cx, cy)
        blc = [cx - half, cy - half, 0, 0]
        trc = [cx + half, cy + half, 0, 0]
        cut = ia.getchunk(blc=blc, trc=trc)[:, :, 0, 0]
    finally:
        ia.close()

    # if the cutout was clipped at the image edge, only profile radii that
    # sample full annuli (partial corner annuli would bias the means)
    r_max = min(r_max, half * cell)
    radii, means = radial_profile(cut, (half, half), cell, r_max,
                                  n_bins=n_bins)
    peak = means.max() if len(means) else 1.0
    if peak > 0:
        means = means / peak
    return list(radii), list(means)


def psf_skirt(psf_path, fwhm_arcsec, rmax_fwhm=2.5):
    """PSF level at radius = 1 x `fwhm_arcsec` (memo-65 metric 2b).

    Reads only a central cutout (+-rmax_fwhm x FWHM) so main-sized PSFs
    (15000^2 px) never load fully into memory.  Returns (skirt, profile)
    where profile is the (radius_arcsec, mean_psf) table for diagnostics.
    """
    import casatools
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

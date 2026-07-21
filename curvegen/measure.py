"""
Measurements on one tclean output: fitted beam, dirty-image rms, the
PSF "skirt", a compact PSF radial profile, and major/minor-axis PSF cuts.

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


def _psf_cutout(imagename, r_max_arcsec):
    """Open a PSF image and read a central cutout (shared helper for
    psf_radial_profile and psf_axis_cuts_from_psf).

    Reads only a central blc:trc window (so main-sized PSFs, ~15000^2 px,
    never load fully into memory).  The cutout array is indexed [axis0,
    axis1] exactly as ia.getchunk returns it -- axis 0 is the image's first
    direction axis, axis 1 its second (for a standard CASA image these are
    R.A. and Dec. respectively); see psf_axis_cuts for why that ordering,
    AND the sign of each axis's coordinate increment, matter for the axis
    cuts.

    Returns (cutout, center_xy, cell_arcsec, r_max_arcsec, sign0, sign1).
    `sign0`/`sign1` are the signs of the coordsys increment on axis0/axis1:
    +1 if increasing pixel index increases the sky coordinate (R.A./Dec.),
    -1 if it decreases it.  `cell_arcsec` is the (unsigned) pixel size,
    taken from axis0 and assumed equal on axis1, as before.  The returned
    r_max_arcsec is clamped to half*cell if the requested radius would have
    run past the image edge, so callers only ever profile/cut radii the
    cutout actually covers (partial corner annuli would otherwise bias a
    radial mean, and an edge-clipped cut would silently go out of bounds).
    """
    import casatools
    ia = casatools.image()
    ia.open(imagename)
    try:                       # close even on error: run_point swallows
        shape = ia.shape()     # capture failures and then deletes the PSF,
        cs = ia.coordsys()     # so a leaked open handle would break cleanup
        inc = cs.increment()["numeric"]
        cell = abs(inc[0]) * 206264.80624709636                    # arcsec
        sign0 = -1.0 if inc[0] < 0 else 1.0
        sign1 = -1.0 if inc[1] < 0 else 1.0
        cs.done()
        cx, cy = shape[0] // 2, shape[1] // 2
        half = int(np.ceil(r_max_arcsec / cell)) + 2
        half = min(half, cx, cy)
        blc = [cx - half, cy - half, 0, 0]
        trc = [cx + half, cy + half, 0, 0]
        cut = ia.getchunk(blc=blc, trc=trc)[:, :, 0, 0]
    finally:
        ia.close()
    r_max_arcsec = min(r_max_arcsec, half * cell)
    return cut, (half, half), cell, r_max_arcsec, sign0, sign1


def psf_radial_profile(imagename, res_geo_arcsec, n_bins=40):
    """Compact radial profile of a PSF, for capture at sweep time.

    Opens `imagename` the same way psf_skirt does (central cutout only, so
    main-sized PSFs never load fully into memory), profiles it out to
    r_max = 3 x `res_geo_arcsec`, and normalizes the profile to peak = 1.
    Returns (r_arcsec list, psf list).
    """
    # axis signs don't matter for an isotropic radial average
    cut, center, cell, r_max, _sign0, _sign1 = \
        _psf_cutout(imagename, 3.0 * res_geo_arcsec)
    radii, means = radial_profile(cut, center, cell, r_max, n_bins=n_bins)
    peak = means.max() if len(means) else 1.0
    if peak > 0:
        means = means / peak
    return list(radii), list(means)


def _bilinear_sample(img, p0, p1):
    """Bilinear-interpolate 2-D array `img` at fractional pixel coordinates
    (`p0`, `p1`) -- equal-length 1-D arrays of axis0/axis1 positions.

    Returns a plain list, the same length, with None (not NaN -- JSON has
    no NaN) wherever the surrounding 2x2 square falls outside `img`.
    """
    n0, n1 = img.shape
    out = []
    for x0, x1 in zip(p0, p1):
        i0, i1 = int(np.floor(x0)), int(np.floor(x1))
        if i0 < 0 or i1 < 0 or i0 + 1 >= n0 or i1 + 1 >= n1:
            out.append(None)
            continue
        f0, f1 = x0 - i0, x1 - i1
        out.append(float(
            img[i0, i1] * (1 - f0) * (1 - f1) +
            img[i0 + 1, i1] * f0 * (1 - f1) +
            img[i0, i1 + 1] * (1 - f0) * f1 +
            img[i0 + 1, i1 + 1] * f0 * f1))
    return out


def psf_axis_cuts(cutout, center, cell_arcsec, bpa_deg, r_max_arcsec, n=81,
                  sign0=1.0, sign1=1.0):
    """Bilinear PSF cuts through the peak along the beam's major & minor axes.

    `cutout` must be indexed [axis0, axis1] exactly as _psf_cutout /
    ia.getchunk return it.  For a standard CASA image axis0 is R.A., axis1
    is Dec. (the convention already used by psf_radial_profile's
    `cx, cy = shape[0], shape[1]` split, and by `_psf_cutout` above); the
    CASA beam position angle `bpa_deg` is defined from north (+Dec) toward
    east (+R.A.), i.e. in SKY coordinates a unit step along the major axis
    has components (east=sin(bpa), north=cos(bpa)), minor +90 deg from that:
    (east=cos(bpa), north=-sin(bpa)).

    Sky coordinates and pixel indices are not the same thing: whether
    increasing pixel index on a given axis increases or decreases the sky
    coordinate depends on that axis's coordsys increment sign, and the TWO
    axes are independent -- a standard CASA/FITS image has a NEGATIVE R.A.
    increment (pixel axis0 increasing -> R.A. decreasing, i.e. +axis0 is
    WEST) but a POSITIVE Dec. increment (+axis1 is north).  `sign0`/`sign1`
    (from `_psf_cutout`) carry those per-axis signs into pixel space, so the
    major-axis pixel-space unit step is (sign0*sin(bpa), sign1*cos(bpa)) on
    (axis0, axis1), and minor is (sign0*cos(bpa), -sign1*sin(bpa)).  Default
    (+1, +1) keeps this function directly testable without a real image's
    coordsys.  (Flipping BOTH signs together would only mirror the --
    symmetric -- PSF, harmless; but getting one axis's sign wrong, or
    swapping which trig function multiplies which axis, samples neither the
    true major nor minor axis -- the unit tests below check both.)

    Samples run over `n` signed radii evenly spaced across
    [-r_max_arcsec, +r_max_arcsec] (r=0 is included and lands exactly on the
    peak pixel, no interpolation needed there).  A sample whose bilinear
    square falls outside `cutout` is None rather than clipped: clipping
    would silently flatten the cut's wings, which is exactly the asymmetry
    this capture exists to expose.

    Returns (cut_r_arcsec, cut_maj, cut_min): r ascending, and the two cuts
    each a length-`n` list on the same scale as `cutout` (None where a
    sample is out of bounds).
    """
    cutout = np.asarray(cutout, dtype=float)
    c0, c1 = center
    pa = np.deg2rad(bpa_deg)
    major = (sign0 * np.sin(pa), sign1 * np.cos(pa))
    minor = (sign0 * np.cos(pa), -sign1 * np.sin(pa))   # +90 deg from major

    r = np.linspace(-r_max_arcsec, r_max_arcsec, n)
    cut_maj = _bilinear_sample(cutout, c0 + r * major[0] / cell_arcsec,
                                       c1 + r * major[1] / cell_arcsec)
    cut_min = _bilinear_sample(cutout, c0 + r * minor[0] / cell_arcsec,
                                       c1 + r * minor[1] / cell_arcsec)
    return list(r), cut_maj, cut_min


def psf_axis_cuts_from_psf(psf_path, res_geo_arcsec, bpa_deg, n=81):
    """Major/minor-axis PSF cuts for capture at sweep time.

    Opens `psf_path` via the same central-cutout path as psf_radial_profile
    (r_max = 3 x `res_geo_arcsec`), reading the image's real per-axis
    coordinate-increment signs (see _psf_cutout / psf_axis_cuts), and
    samples it with psf_axis_cuts.  The cutout is normalized by its own raw
    peak pixel (not the radial profile's binned peak): r=0 always lands
    exactly on the peak pixel, so for a well-formed PSF the two peaks agree
    to well under a percent.  Returns (cut_r_arcsec, cut_maj, cut_min).
    """
    cut, center, cell, r_max, sign0, sign1 = \
        _psf_cutout(psf_path, 3.0 * res_geo_arcsec)
    peak = float(cut.max())
    if peak > 0:
        cut = cut / peak
    return psf_axis_cuts(cut, center, cell, bpa_deg, r_max, n=n,
                         sign0=sign0, sign1=sign1)


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

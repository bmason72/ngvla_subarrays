"""
Configuration for Rev F taperability/sculptability curve generation (PLAN.md
Track 2).  Everything tunable lives here: subarray composition, image sizes,
and the (robust, taper) parameter grids.

Grid design (v2, after bmason's 5 Jul 2026 review of the v1 curves):
  * The grid is a full 2-D (robust x taper) lattice: rows are natural
    weighting plus Briggs robust -2..+2 in steps of 0.4, columns are taper 0
    plus ~14 log-spaced tapers.  Natural+taper is then genuinely one edge of
    the searched space, so the sculpted (imaging) curve can never sit above
    an admissible natural point at the same resolution -- the v1 failure.
  * Tapers are anchored to the subarray's OWN measured resolutions: from
    0.3 x the robust=-2 beam (so every row samples smoothly down to its
    untapered resolution) up to 20 x the natural beam.  Anchors are read
    from the two seed points, which the sweep runs first; grids are
    therefore per-subarray and self-calibrating.
  * eta is computed on the fly and rows are pruned once eta > ETA_CAP
    (points beyond are recorded as skipped): we don't need the eta > ~5
    regime, and this keeps the lattice tractable.

Only the relatively homogeneous subarrays are swept for now (RUN_SET);
core+mid and main need a smarter treatment of their two-component beams
and are deferred (see PLAN.md).
"""

import os
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REVF_DIR = os.path.join(REPO, "ngvla-configurations", "Rev F", "CASA Files")

COMPONENT_CFGS = {
    "core": "RevF_Core_2025_01_27_xyz.cfg",
    "spiral": "RevF_Spiral_2025_01_16_xyz.cfg",
    "mid": "RevF_MidSitesPreferred_2025_01_16_xyz.cfg",
}

# 'core-inner' is memo 121's CoreInner: the innermost 57 of the core's 114
# antennas (selected by radius from the core centroid in build_configs.py).
SUBARRAYS = {
    "core-inner": ["core-inner"],
    "core": ["core"],
    "spiral": ["spiral"],
    "mid": ["mid"],
    "core+spiral": ["core", "spiral"],
    "core+mid": ["core", "mid"],
    "spiral+mid": ["spiral", "mid"],
    "main": ["core", "spiral", "mid"],
}

# the relatively homogeneous set we are getting right first
RUN_SET = ["core-inner", "core", "spiral", "mid", "core+spiral", "spiral+mid"]

IMSIZE = {
    "core-inner": 4096,
    "core": 4096,
    "spiral": 4096,
    "mid": 4096,
    "core+spiral": 8192,
    "spiral+mid": 8192,
    "core+mid": 15000,
    "main": 15000,
}

ROBUST_LIST = [round(r, 2) for r in np.arange(-2.0, 2.01, 0.4)]
N_TAPERS = 14        # log-spaced taper count per row
TAPER_LO_X = 0.3     # taper range: TAPER_LO_X * res(robust=-2) ...
TAPER_HI_X = 20.0    # ... TAPER_HI_X * res(natural)
ETA_CAP = 5.0        # stop extending a row once eta exceeds this

# simulation parameters (identical to Viviana's pipeline for comparability)
SIM = dict(
    frequency="30GHz",
    integration_time="60s",
    timerange=("-2h", "2h"),
    source_dec="+24",
    noise="1Jy",
)

OVERSAMPLE = 5           # pixels per synthesized-beam FWHM (via im.advise)

CFG_DIR = os.path.join(REPO, "curvegen", "configs")
MS_DIR = os.path.join(REPO, "curvegen", "ms")
WORK_DIR = os.path.join(REPO, "curvegen", "work")
RESULTS_DIR = os.path.join(REPO, "curvegen", "results")

# the two seed points every sweep runs first; their measured beams anchor
# the taper grid (res_nat from the first, res_fine from the second)
SEEDS = [("natural", 2.0, 0.0), ("briggs", -2.0, 0.0)]


def taper_list_mas(res_fine_mas, res_nat_mas):
    """Log-spaced tapers anchored to the subarray's measured resolutions."""
    lo = TAPER_LO_X * res_fine_mas
    hi = TAPER_HI_X * res_nat_mas
    return [round(float(t), 3) for t in
            np.logspace(np.log10(lo), np.log10(hi), N_TAPERS)]


def grid_rows(res_fine_mas, res_nat_mas):
    """The full sweep lattice: [(weighting, robust, [tapers ascending]), ...].

    Every row starts at taper 0; the sweep walks tapers in order and prunes
    the row once eta > ETA_CAP.
    """
    tapers = [0.0] + taper_list_mas(res_fine_mas, res_nat_mas)
    rows = [("natural", 2.0, tapers)]
    for r in ROBUST_LIST:
        rows.append(("briggs", r, tapers))
    return rows

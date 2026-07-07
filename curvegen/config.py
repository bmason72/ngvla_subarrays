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
    "long": "RevF_Long_2025_01_16_xyz.cfg",
}

# 'core-inner' is memo 121's CoreInner: the innermost 57 of the core's 114
# antennas by radius from the core centroid; 'core-outer' is the other 57
# (memo 121's 'outer50core').  Both membership rules verified against
# Stroh's delivered configs.  The memo-121 campaign set (7 Jul 2026) adds
# 'long' and its combinations; note Long includes small ~3-antenna clusters
# with ~100 m internal baselines -- physical, kept in the sims, but they
# must be FILTERED when computing b_min/LAS (see saUtil.filter_spurious_shorts).
SUBARRAYS = {
    "core-inner": ["core-inner"],
    "core": ["core"],
    "spiral": ["spiral"],
    "mid": ["mid"],
    "core+spiral": ["core", "spiral"],
    "core+mid": ["core", "mid"],
    "spiral+mid": ["spiral", "mid"],
    "main": ["core", "spiral", "mid"],
    # memo-121 campaign additions
    "core-outer": ["core-outer"],             # seeds only (cap anchor)
    "long": ["long"],
    "mid+long": ["mid", "long"],
    "spiral+mid+long": ["spiral", "mid", "long"],
    "main+long": ["core", "spiral", "mid", "long"],
    "spiral+core-outer": ["spiral", "core-outer"],
    "mid+spiral+core-outer": ["mid", "spiral", "core-outer"],
    "long+mid+spiral+core-outer": ["long", "mid", "spiral", "core-outer"],
}

# the relatively homogeneous set we got right first (v2)
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
    # campaign: long-baseline combos need the spike sampled at fine cell
    # while the plateau/taper branch reaches the beam cap (adaptive cell
    # handles the coarse end); outerCore combos mirror their non-outer kin
    "core-outer": 4096,
    "long": 8192,
    "mid+long": 15000,
    "spiral+mid+long": 15000,
    "main+long": 15000,
    "spiral+core-outer": 8192,
    "mid+spiral+core-outer": 15000,
    "long+mid+spiral+core-outer": 15000,
}

ROBUST_LIST = [round(r, 2) for r in np.arange(-2.0, 2.01, 0.4)]
N_TAPERS = 14        # log-spaced taper count per row
TAPER_LO_X = 0.3     # taper range: TAPER_LO_X * res(robust=-2) ...
TAPER_HI_X = 20.0    # ... TAPER_HI_X * res(natural)
ETA_CAP = 5.0        # stop extending a row once eta exceeds this

# Heterogeneous subarrays (v2 rework of the v1 "bonkers" failure): beams
# coarser than the coarsest component's own native beam are always better
# made with that component subarray -- reaching them from the composite
# means tapering away the long spacings (low eta but a false economy, the
# v1 sculpt-curve false minima).  Points whose measured beam exceeds the
# cap are recorded status="capped" (measurements kept for diagnostics but
# never collected into the curve data), and a row is pruned after two
# consecutive capped points (two, not one, to ride out clean-beam-fit
# discontinuities at the spike-to-plateau transition).  The cap is the
# coarsest component's natural beam: Rev F core at 30 GHz = 0.710"
# (measured, results/core.csv; hardcoded so config never depends on
# generated results at import time).
BEAM_CAP_ARCSEC = {
    "core+mid": 0.710,
    "main": 0.710,
    # memo-121 campaign combos: cap = the coarsest component's (or largest
    # contained offered subarray's) measured native beam at 30 GHz
    "mid+long": 0.00296,                 # mid native (measured)
    "spiral+mid+long": 0.0111,           # spiral+mid native (measured)
    "main+long": 0.0212,                 # main native (measured)
    # outerCore combos: cap = core-outer native 0.4908" (measured 7 Jul 2026)
    "spiral+core-outer": 0.491,
    "mid+spiral+core-outer": 0.491,
    "long+mid+spiral+core-outer": 0.491,
}
# Their fine-to-coarse dynamic range is ~2.5 dex (vs ~1.3 homogeneous) and
# the beam(taper) mapping crosses a sharp spike-to-plateau transition, so
# sample tapers more densely.
N_TAPERS_HETERO = 18

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


def taper_list_mas(res_fine_mas, res_nat_mas, n_tapers=N_TAPERS):
    """Log-spaced tapers anchored to the subarray's measured resolutions."""
    lo = TAPER_LO_X * res_fine_mas
    hi = TAPER_HI_X * res_nat_mas
    return [round(float(t), 3) for t in
            np.logspace(np.log10(lo), np.log10(hi), n_tapers)]


def grid_rows(res_fine_mas, res_nat_mas, subarray=None):
    """The full sweep lattice: [(weighting, robust, [tapers ascending]), ...].

    Every row starts at taper 0; the sweep walks tapers in order and prunes
    the row once eta > ETA_CAP (and, for heterogeneous subarrays, once the
    beam exceeds BEAM_CAP_ARCSEC).
    """
    n_tapers = N_TAPERS_HETERO if subarray in BEAM_CAP_ARCSEC else N_TAPERS
    tapers = [0.0] + taper_list_mas(res_fine_mas, res_nat_mas, n_tapers)
    rows = [("natural", 2.0, tapers)]
    for r in ROBUST_LIST:
        rows.append(("briggs", r, tapers))
    return rows

"""
Configuration for Rev F taperability/sculptability curve generation (PLAN.md
Track 2).  Everything tunable lives here: subarray composition, image sizes,
and the (robust, taper) parameter grids.

Grid design (kept deliberately small -- PLAN.md section 9):
  * natural branch : natural weighting, taper 0 + ~12 log-spaced tapers.
    Traces the classic taperability curve rightward from native resolution
    (memos 55/72).  Taper ranges adapted per subarray from the presets in
    ngvla-taperability-pipeline/run_all.py.
  * robust branch  : Briggs robust -2..+2 step 0.4, no taper (memo 65 grid).
    Traces finer-than-native resolutions and beam sculpting.
  * sculpt branch  : a coarse robust x taper grid (memo 121's sculptability
    move: reach a *tapered* resolution with a sculpted skirt).

The sweep is resumable, so grids can be extended later -- new points are
appended, finished ones are skipped.
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

# v1 subarray set: all non-empty subsets of {core, spiral, mid} (PLAN.md sec 5)
SUBARRAYS = {
    "core": ["core"],
    "spiral": ["spiral"],
    "mid": ["mid"],
    "core+spiral": ["core", "spiral"],
    "core+mid": ["core", "mid"],
    "spiral+mid": ["spiral", "mid"],
    "main": ["core", "spiral", "mid"],
}

# image size in pixels; larger arrays need more pixels so the uv plane is
# gridded finely enough for Briggs weighting (cf. run_all.py comments:
# 4096 "most arrays", 15000 main)
IMSIZE = {
    "core": 4096,
    "spiral": 4096,
    "mid": 4096,
    "core+spiral": 8192,
    "spiral+mid": 8192,
    "core+mid": 15000,
    "main": 15000,
}

# natural-branch uv tapers in mas (on-sky FWHM), log-spaced from roughly the
# native resolution up to ~the LAS scale of the shortest baselines present
TAPERS_MAS = {
    "core": np.logspace(3.0, 4.0, 12),      # 1" - 10"
    "spiral": np.logspace(1.5, 3.0, 12),    # 30 mas - 1"
    "mid": np.logspace(0.0, 1.5, 12),       # 1 - 30 mas
    "core+spiral": np.logspace(1.8, 4.0, 12),
    "spiral+mid": np.logspace(0.0, 3.0, 12),
    "core+mid": np.logspace(0.0, 4.0, 12),
    "main": np.logspace(0.0, 4.0, 12),
}

ROBUST_LIST = np.arange(-2.0, 2.01, 0.4)     # memo 65 grid

# sculpt branch: negative-robust x a subsample of the taper grid
SCULPT_ROBUSTS = [-2.0, -1.5, -1.0, -0.5]
SCULPT_TAPER_STRIDE = 3                       # every 3rd natural taper

# simulation parameters (identical to Viviana's pipeline for comparability)
SIM = dict(
    frequency="30GHz",
    integration_time="60s",
    timerange=("-2h", "2h"),
    source_dec="+24",
    noise="1Jy",
)

OVERSAMPLE = 5           # pixels per synthesized-beam FWHM (via im.advise)

# working directories (ms/ and work/ are regenerable -> gitignored)
CFG_DIR = os.path.join(REPO, "curvegen", "configs")
MS_DIR = os.path.join(REPO, "curvegen", "ms")
WORK_DIR = os.path.join(REPO, "curvegen", "work")
RESULTS_DIR = os.path.join(REPO, "curvegen", "results")


def grid_points(subarray):
    """The (weighting, robust, taper_mas) grid for one subarray.

    Returns a list of tuples; taper 0 means no taper.  The natural untapered
    point is first -- it is the eta = 1 reference and must exist before any
    eta can be computed.
    """
    pts = [("natural", 2.0, 0.0)]
    for t in TAPERS_MAS[subarray]:
        pts.append(("natural", 2.0, round(float(t), 3)))
    for r in ROBUST_LIST:
        pts.append(("briggs", round(float(r), 2), 0.0))
    sculpt_tapers = TAPERS_MAS[subarray][::SCULPT_TAPER_STRIDE]
    for r in SCULPT_ROBUSTS:
        for t in sculpt_tapers:
            pts.append(("briggs", round(float(r), 2), round(float(t), 3)))
    return pts

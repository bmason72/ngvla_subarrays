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
  * the FULL grid is measured (bmason 8 Jul 2026): the eta-cap and
    natural+taper-edge convergence prunes were removed so every (robust, taper)
    cell exists -- pruning left holes that block bilinear-cell formation and
    truncated the (now-collected) high-eta regime.  ETA_CAP survives only as a
    plotting/back-of-envelope bound (make_report display, this file's docs).
    The one early-stop kept is the heterogeneous beam cap (BEAM_CAP_ARCSEC).
"""

import csv
import os
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# (rev, sim_mode) axis (tranche component D).  Everything below selects the
# active configuration revision and simulation mode from the environment; the
# DEFAULT (revF, track) reproduces the original hardcoded Rev F / 4-h-track
# behaviour byte-for-byte (same dicts, same paths).  A campaign for another
# combination just exports NGVLA_REV / NGVLA_SIM_MODE (see the sbatch scripts).
# ---------------------------------------------------------------------------
REV = os.environ.get("NGVLA_REV", "revF")
SIM_MODE = os.environ.get("NGVLA_SIM_MODE", "track")

# per-rev component .cfg directories and filename maps.  Rev D's "long" is the
# lba (long-baseline array) config; core/spiral/mid map name-for-name.  Rev D
# lba has the SAME spurious-short pathology as Rev F Long (baselines 36-174 m
# then a jump to 131 km) -- handled by MIN_UVRANGE_M below, exactly as Rev F.
_COMPONENT_DIRS = {
    "revF": os.path.join(REPO, "ngvla-configurations", "Rev F", "CASA Files"),
    "revD": os.path.join(REPO, "ngvla-configurations", "Rev D", "CASA Files"),
}
_COMPONENT_CFGS = {
    "revF": {
        "core": "RevF_Core_2025_01_27_xyz.cfg",
        "spiral": "RevF_Spiral_2025_01_16_xyz.cfg",
        "mid": "RevF_MidSitesPreferred_2025_01_16_xyz.cfg",
        "long": "RevF_Long_2025_01_16_xyz.cfg",
    },
    "revD": {
        "core": "ngvla-revD.core.cfg",
        "spiral": "ngvla-revD.spiral.cfg",
        "mid": "ngvla-revD.mid.cfg",
        "long": "ngvla-revD.lba.cfg",
    },
}
if REV not in _COMPONENT_CFGS:
    raise ValueError("unknown NGVLA_REV=%r; known revisions: %s"
                     % (REV, sorted(_COMPONENT_CFGS)))

# component .cfg directory + filename map for the ACTIVE revision
COMPONENT_DIR = _COMPONENT_DIRS[REV]
COMPONENT_CFGS = _COMPONENT_CFGS[REV]
# backward-compatible alias (some callers still import REVF_DIR)
REVF_DIR = _COMPONENT_DIRS["revF"]

# 'core-inner' is memo 121's CoreInner: the innermost 57 of the core's 114
# antennas by radius from the core centroid; 'core-outer' is the other 57
# (memo 121's 'outer50core').  Both membership rules verified against
# Stroh's delivered configs.  The memo-121 campaign set (7 Jul 2026) adds
# 'long' and its combinations; note Long includes small ~3-antenna clusters
# with ~100 m internal baselines -- physical, kept in the sims, but they
# must be FILTERED when computing b_min/LAS (see saUtil.filter_spurious_shorts).
_SUBARRAYS = {
    "revF": {
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
    },
    # Rev D offered set (bmason, campaign_proposal_revd_snapshot.md): mirror the
    # Rev F structure where components exist.  Rev D has no core-inner/core-outer
    # split, so those and the spiral+mid+long / core-outer combos are omitted.
    "revD": {
        "core": ["core"],
        "spiral": ["spiral"],
        "mid": ["mid"],
        "core+spiral": ["core", "spiral"],
        "spiral+mid": ["spiral", "mid"],
        "main": ["core", "spiral", "mid"],
        "long": ["long"],
        "mid+long": ["mid", "long"],
        "main+long": ["core", "spiral", "mid", "long"],
    },
}
SUBARRAYS = _SUBARRAYS[REV]

# the relatively homogeneous set we got right first (v2)
RUN_SET = ["core-inner", "core", "spiral", "mid", "core+spiral", "spiral+mid"]

_IMSIZE = {
    "revF": {
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
    },
    # Rev D mirrors the Rev F imsize choices for the shared subarray shapes.
    "revD": {
        "core": 4096,
        "spiral": 4096,
        "mid": 4096,
        "core+spiral": 8192,
        "spiral+mid": 8192,
        "main": 15000,
        "long": 8192,
        "mid+long": 15000,
        "main+long": 15000,
    },
}
IMSIZE = _IMSIZE[REV]

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
# DEFAULT (revF, track) caps -- the measured values, hardcoded so the default
# config never depends on generated results at import time (byte-stable).
_BEAM_CAP_DEFAULT = {
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

# CAP_REFERENCE[rev] = {heterogeneous subarray: the offered subarray whose
# NATURAL beam is that subarray's cap}.  It generalizes _BEAM_CAP_DEFAULT: for
# any NON-default (rev, sim_mode) combination the caps are not known a priori
# (snapshot beams are elliptical/sparse; Rev D geometry differs), so they are
# MEASURED from that combination's own natural seeds and written into its
# subarrays metadata CSV by curvegen/fill_beam_caps.py -- the two-step the
# campaign proposal describes (seeds first, then caps into the metadata, then
# the full grids).  Keyed by rev (geometry), independent of sim_mode.
CAP_REFERENCE = {
    "revF": {
        "core+mid": "core",
        "main": "core",
        "mid+long": "mid",
        "spiral+mid+long": "spiral+mid",
        "main+long": "main",
        "spiral+core-outer": "core-outer",
        "mid+spiral+core-outer": "core-outer",
        "long+mid+spiral+core-outer": "core-outer",
    },
    "revD": {
        "main": "core",
        "mid+long": "mid",
        "main+long": "main",
    },
}.get(REV, {})


def _load_caps_from_metadata():
    """Read caps for the active non-default combo from its subarrays CSV.

    The CSV is resolved through sa_select/data/config_registry.csv (the same
    source of truth CurveLibrary/collect use).  Returns {} if the combo is not
    yet registered or the file/column is absent or empty -- which is the
    correct state during the seed+pilot phase, BEFORE fill_beam_caps.py has
    measured and written the caps.  Later full-grid runs re-import config and
    pick up the freshly-written caps.
    """
    reg = os.path.join(REPO, "sa_select", "data", "config_registry.csv")
    try:
        with open(reg, newline="") as f:
            subs_csv = next(
                (r["subarrays_csv"].strip() for r in csv.DictReader(f)
                 if r["rev"].strip() == REV
                 and r["sim_mode"].strip() == SIM_MODE), None)
        if not subs_csv:
            return {}
        path = os.path.join(REPO, "sa_select", "data", subs_csv)
        caps = {}
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                v = (r.get("beam_cap_arcsec_30ghz") or "").strip()
                if v:
                    caps[r["name"].strip()] = float(v)
        return caps
    except (FileNotFoundError, StopIteration, KeyError):
        return {}


# active caps: the hardcoded measured dict for the default combo (byte-stable),
# else the caps measured for this combo and written into its metadata CSV
BEAM_CAP_ARCSEC = (_BEAM_CAP_DEFAULT if (REV, SIM_MODE) == ("revF", "track")
                   else _load_caps_from_metadata())
# Their fine-to-coarse dynamic range is ~2.5 dex (vs ~1.3 homogeneous) and
# the beam(taper) mapping crosses a sharp spike-to-plateau transition, so
# sample tapers more densely.
N_TAPERS_HETERO = 18

# Spurious-short-baseline filter (bmason 8 Jul 2026): the LONG config has small
# ~3-antenna clusters whose internal baselines run 37-176 m, leaving a bimodal
# uv distribution (a real ~2900x gap up to the 515 km long baselines) that
# fragments the LONG-only curve.  Image with uvrange>178 m to filter them.
# 178 m sits in the 176.2 -> 179.0 m gap: it removes ALL of LONG's 30 spurious
# baselines while KEEPING core-outer's legitimate baselines (b_min 179.0 m) in
# long+mid+spiral+core-outer -- a wider cut (e.g. 500 m) would wrongly delete
# ~65 real core-outer baselines.  NOT applied to main+long: the core's
# legitimate 42 m baselines live below the cut.  The cut is applied uniformly
# incl. the natural seed, so eta = rms/natural_rms stays self-consistent, and
# it reuses the existing MS (only re-imaging is needed).  Filtered b_min (and
# hence LAS) per subarray: long 515 km, mid+long 10.1 km, spiral+mid+long
# 811 m, long+mid+spiral+core-outer 179 m -- reflected in subarrays.csv.
_MIN_UVRANGE = {
    "revF": {
        "long": 178.0,
        "mid+long": 178.0,
        "spiral+mid+long": 178.0,
        "long+mid+spiral+core-outer": 178.0,
    },
    # Rev D lba is pathologically identical to Rev F Long: spurious internal
    # baselines 36-174 m then a jump to 131 km, so the SAME 178 m cut removes
    # all 30 spurious and keeps every real baseline.  main+long is NOT filtered
    # (its core has legitimate ~39 m baselines below the cut), as in Rev F.
    "revD": {
        "long": 178.0,
        "mid+long": 178.0,
    },
}
MIN_UVRANGE_M = _MIN_UVRANGE.get(REV, {})

# simulation parameters (track = identical to Viviana's pipeline, for
# comparability).  sim_mode "snapshot" (feature 6): a single 60 s integration
# centered on transit (HA=0) -- the ("-30s","30s") window makes the one dump's
# midpoint sit at HA=0.  simulate.py asserts exactly one integration lands.
_SIM_TRACK = dict(
    frequency="30GHz",
    integration_time="60s",
    timerange=("-2h", "2h"),
    source_dec="+24",
    noise="1Jy",
)
SIM_MODES = {
    "track": _SIM_TRACK,
    "snapshot": dict(_SIM_TRACK, timerange=("-30s", "30s")),
}
if SIM_MODE not in SIM_MODES:
    raise ValueError("unknown NGVLA_SIM_MODE=%r; known modes: %s"
                     % (SIM_MODE, sorted(SIM_MODES)))
# the active simulation preset (simulate.py imports SIM)
SIM = SIM_MODES[SIM_MODE]

OVERSAMPLE = 5           # pixels per synthesized-beam FWHM (via im.advise)


def config_suffix():
    """Path suffix for the active combo: "" for the default (revF, track),
    else "-<rev>_<sim_mode>" so each combination writes to FRESH directories
    (results-revD_track/, ms-revD_track/, ...) and never collides with the
    Rev F / track data.  Used by all four path constants below."""
    return "" if (REV, SIM_MODE) == ("revF", "track") \
        else "-%s_%s" % (REV, SIM_MODE)


_SUFFIX = config_suffix()

# configs and results are small (cfg files + CSVs) and live in the repo;
# per-combo they get the suffix (default -> unchanged repo dirs).
CFG_DIR = os.path.join(REPO, "curvegen", "configs" + _SUFFIX)
RESULTS_DIR = os.path.join(REPO, "curvegen", "results" + _SUFFIX)


def _scratch_dir(kind):
    """Resolve a large out-of-repo directory (ms / work).  The DEFAULT combo
    keeps the original repo path (curvegen/ms, curvegen/work -- symlinks on
    TACC) byte-for-byte; any other combo appends the suffix under a base dir
    taken from the environment.

    The two kinds get DIFFERENT bases (15 Jul 2026, bmason: $SCRATCH is
    periodically purged and losing the MSes costs a re-simulation campaign):
    - ms   -> NGVLA_MS_BASE   (e.g. $WORK/ngvla_curvegen -- persistent)
    - work -> NGVLA_SCRATCH   (e.g. $SCRATCH/ngvla_curvegen -- tclean cwd /
      TempLattice churn; disposable, regenerated per run)
    NGVLA_MS_BASE falls back to NGVLA_SCRATCH (the pre-15-Jul layout), then
    to a suffixed repo dir (fine for a laptop, wrong for a big campaign)."""
    if not _SUFFIX:
        return os.path.join(REPO, "curvegen", kind)
    base = None
    if kind == "ms":
        base = os.environ.get("NGVLA_MS_BASE")
    if base is None:
        base = os.environ.get("NGVLA_SCRATCH")
    if base:
        return os.path.join(base, kind + _SUFFIX)
    return os.path.join(REPO, "curvegen", kind + _SUFFIX)


MS_DIR = _scratch_dir("ms")
WORK_DIR = _scratch_dir("work")

# PSF radial-profile capture (groundwork for memo-style beam-shape work):
# every successfully imaged sweep point appends one JSON line of azimuthal
# profile to PROFILE_DIR/<subarray file stem>.jsonl (see sweep.py)
CAPTURE_PROFILES = True
PROFILE_DIR = os.path.join(RESULTS_DIR, "profiles")

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

    Every row starts at taper 0; the sweep measures every cell (full grid).
    For heterogeneous subarrays the row still stops once the beam exceeds
    BEAM_CAP_ARCSEC (two consecutive capped points).
    """
    n_tapers = N_TAPERS_HETERO if subarray in BEAM_CAP_ARCSEC else N_TAPERS
    tapers = [0.0] + taper_list_mas(res_fine_mas, res_nat_mas, n_tapers)
    rows = [("natural", 2.0, tapers)]
    for r in ROBUST_LIST:
        rows.append(("briggs", r, tapers))
    return rows

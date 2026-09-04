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
import re
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# (rev, sim_mode, band) axis.  An empty band is the legacy monochromatic
# 30-GHz campaign; band4 is the first broadband MFS campaign.
# The active axes come from the environment. The default (revF, track, mono)
# retains the original 30-GHz setup and paths.
# ---------------------------------------------------------------------------
REV = os.environ.get("NGVLA_REV", "revF")
SIM_MODE = os.environ.get("NGVLA_SIM_MODE", "track")
BAND = os.environ.get("NGVLA_BAND", "").strip().lower()
CAMPAIGN_VARIANT = os.environ.get("NGVLA_CAMPAIGN_VARIANT", "").strip().lower()

# MFS-2a intentionally exposes only the bmason-approved first MFS window.
# Frequencies are GHz; channels uniformly tile [lo, hi], and CASA receives
# the first channel centre rather than the band centre.
BANDS = {
    "band4": dict(ref_freq_ghz=27.0, freq_lo_ghz=20.25,
                  freq_hi_ghz=33.75),
}
if BAND and BAND not in BANDS:
    raise ValueError("unknown NGVLA_BAND=%r; MFS scope currently supports: %s"
                     % (BAND, sorted(BANDS)))
if BAND and REV != "revF":
    raise ValueError("NGVLA_BAND=%r is currently supported only for revF"
                     % BAND)
MFS = bool(BAND)
if CAMPAIGN_VARIANT and not MFS:
    raise ValueError("NGVLA_CAMPAIGN_VARIANT is only valid for MFS campaigns")
if CAMPAIGN_VARIANT and not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,47}",
                                         CAMPAIGN_VARIANT):
    raise ValueError("NGVLA_CAMPAIGN_VARIANT must be a 1-48 character safe "
                     "slug (lowercase letters, digits, '.', '_' or '-')")


def _active_registry_row():
    """Registry row for the exact (rev, sim_mode, band), or None.

    Older registries have no band column; those rows remain mono entries.
    """
    path = os.path.join(REPO, "sa_select", "data", "config_registry.csv")
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                if (row["rev"].strip() == REV
                        and row["sim_mode"].strip() == SIM_MODE
                        and (row.get("band") or "").strip().lower() == BAND):
                    return row
    except FileNotFoundError:
        return None
    return None


REGISTRY_ROW = _active_registry_row()
if MFS and REGISTRY_ROW is None:
    raise ValueError("no config_registry.csv row for (rev=%r, sim_mode=%r, "
                     "band=%r)" % (REV, SIM_MODE, BAND))


def _positive_int(value, source):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a positive integer, got %r"
                         % (source, value))
    if parsed <= 0 or str(parsed) != str(value).strip():
        raise ValueError("%s must be a positive integer, got %r"
                         % (source, value))
    return parsed


if MFS:
    _env_nchan = os.environ.get("NGVLA_NCHAN", "").strip()
    _reg_nchan = (REGISTRY_ROW.get("nchan") or "").strip()
    if not _env_nchan and not _reg_nchan:
        raise ValueError("MFS campaign %s/%s/%s requires nchan: set "
                         "NGVLA_NCHAN or populate config_registry.csv nchan"
                         % (REV, SIM_MODE, BAND))
    NCHAN = _positive_int(_env_nchan or _reg_nchan,
                          "NGVLA_NCHAN" if _env_nchan else "registry nchan")
    if _env_nchan and _reg_nchan:
        registered = _positive_int(_reg_nchan, "registry nchan")
        if NCHAN != registered:
            raise ValueError("NGVLA_NCHAN=%d disagrees with registry nchan=%d "
                             "for %s/%s/%s"
                             % (NCHAN, registered, REV, SIM_MODE, BAND))
    _band = BANDS[BAND]
    REF_FREQ_GHZ = _band["ref_freq_ghz"]
    FREQ_LO_GHZ = _band["freq_lo_ghz"]
    FREQ_HI_GHZ = _band["freq_hi_ghz"]
    for _field, _expected in (("ref_freq_ghz", REF_FREQ_GHZ),
                              ("freq_lo_ghz", FREQ_LO_GHZ),
                              ("freq_hi_ghz", FREQ_HI_GHZ)):
        try:
            _registered = float((REGISTRY_ROW.get(_field) or "").strip())
        except ValueError:
            raise ValueError("registry %s is required and numeric for %s/%s/%s"
                             % (_field, REV, SIM_MODE, BAND))
        if abs(_registered - _expected) > 1e-12:
            raise ValueError("registry %s=%g disagrees with band definition %g"
                             % (_field, _registered, _expected))
    CHANNEL_WIDTH_GHZ = (FREQ_HI_GHZ - FREQ_LO_GHZ) / NCHAN
    FIRST_CHANNEL_CENTER_GHZ = FREQ_LO_GHZ + CHANNEL_WIDTH_GHZ / 2.0
    CURVE_TYPES = (REGISTRY_ROW.get("curve_types") or "ptsrc").strip()
    NOISE_POLICY = (os.environ.get("NGVLA_NOISE_POLICY")
                    or REGISTRY_ROW.get("noise_policy") or "equal").strip()
    if CURVE_TYPES != "ptsrc":
        raise ValueError("first MFS campaign requires curve_types=ptsrc, got %r"
                         % CURVE_TYPES)
    if NOISE_POLICY != "equal":
        raise ValueError("MFS noise_policy=%r is not implemented; use 'equal'"
                         % NOISE_POLICY)
else:
    NCHAN = 1
    REF_FREQ_GHZ = 30.0
    FREQ_LO_GHZ = FREQ_HI_GHZ = 30.0
    CHANNEL_WIDTH_GHZ = 0.001
    FIRST_CHANNEL_CENTER_GHZ = 30.0
    CURVE_TYPES = "both"
    NOISE_POLICY = "equal"

# per-rev component .cfg directories and filename maps.  Rev D's "long" is the
# lba (long-baseline array) config; core/spiral/mid map name-for-name.  Rev D
# lba has the SAME spurious-short pathology as Rev F Long (baselines 36-174 m
# then a jump to 131 km) -- handled by MIN_UVRANGE_M below, exactly as Rev F.
_COMPONENT_DIRS = {
    "revF": os.path.join(REPO, "ngvla-configurations", "Rev F", "CASA Files"),
    "revD": os.path.join(REPO, "ngvla-configurations", "Rev D", "CASA Files"),
    "revC": os.path.join(REPO, "ngvla-configurations", "Rev C.01", "CASA Files"),
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
    # Rev C.01 (WRAPUP.md release scope, 17 Aug 2026): components mirror Rev D
    # (core 94 / spiral 74 / mid 46 / lba 30 antennas; the provided monolithic
    # main.cfg equals core+spiral+mid antenna-for-antenna, 214).  Its lba
    # short-baseline pathology DIFFERS from D/F: ~10 VLBA-style sites of 2-4
    # antennas whose internal baselines run 47-1115 m, then a gap to the first
    # inter-site baseline at 53.4 km -- see _MIN_UVRANGE below.
    "revC": {
        "core": "ngvla-revC.01.core.cfg",
        "spiral": "ngvla-revC.01.spiral.cfg",
        "mid": "ngvla-revC.01.mid.cfg",
        "long": "ngvla-revC.01.lba.cfg",
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
    # Rev C offered set mirrors Rev D (bmason, WRAPUP.md release scope): same
    # component structure, no core-inner/core-outer split.
    "revC": {
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

MFS_SUBARRAYS = ["core-inner", "core", "spiral", "mid",
                 "core+spiral", "spiral+mid", "main"]
if MFS:
    SUBARRAYS = {name: SUBARRAYS[name] for name in MFS_SUBARRAYS}

# the relatively homogeneous set we got right first (v2)
RUN_SET = list(MFS_SUBARRAYS) if MFS else \
    ["core-inner", "core", "spiral", "mid", "core+spiral", "spiral+mid"]

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
    # Rev C mirrors Rev D (same subarray shapes).
    "revC": {
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
if MFS:
    IMSIZE = {name: IMSIZE[name] for name in MFS_SUBARRAYS}

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
    # Rev C: same heterogeneous shapes as Rev D, same references.
    "revC": {
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
                 and r["sim_mode"].strip() == SIM_MODE
                 and (r.get("band") or "").strip().lower() == BAND), None)
        if not subs_csv:
            return {}
        path = os.path.join(REPO, "sa_select", "data", subs_csv)
        caps = {}
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                field = "beam_cap_arcsec_native" if MFS \
                    else "beam_cap_arcsec_30ghz"
                v = (r.get(field) or "").strip()
                if v:
                    caps[r["name"].strip()] = float(v)
        return caps
    except (FileNotFoundError, StopIteration, KeyError):
        return {}


# active caps: the hardcoded measured dict for the default combo (byte-stable),
# else the caps measured for this combo and written into its metadata CSV
BEAM_CAP_ARCSEC = (_BEAM_CAP_DEFAULT if not MFS
                   and (REV, SIM_MODE) == ("revF", "track")
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
    # Rev C lba's spurious shorts are its VLBA-style SITE-INTERNAL baselines:
    # ~10 sites of 2-4 antennas, internal baselines 47.4-1115.0 m, then a gap
    # to the first inter-site baseline at 53354 m.  A 2000 m cut removes all
    # 32 site-internal baselines with huge margin on both sides.  mid is safe
    # under the same cut (its b_min is 7858 m); main+long is NOT filtered
    # (core's legitimate 38 m baselines live below any cut), as in D and F.
    "revC": {
        "long": 2000.0,
        "mid+long": 2000.0,
    },
}
MIN_UVRANGE_M = _MIN_UVRANGE.get(REV, {})

# simulation parameters (track = identical to Viviana's pipeline, for
# comparability).  sim_mode "snapshot" (feature 6): a single 60 s integration
# centered on transit (HA=0) -- the ("-30s","30s") window makes the one dump's
# midpoint sit at HA=0.  simulate.py asserts exactly one integration lands.
_SIM_TRACK = dict(
    frequency=(("%.12gGHz" % FIRST_CHANNEL_CENTER_GHZ) if MFS else "30GHz"),
    ref_frequency="%.12gGHz" % REF_FREQ_GHZ,
    channel_width=(("%.12gGHz" % CHANNEL_WIDTH_GHZ) if MFS else "1MHz"),
    nchannels=NCHAN,
    correlations="RR LL" if MFS else "RR RL LR LL",
    integration_time="60s",
    timerange=("-2h", "2h"),
    expected_integrations=240,
    source_dec="+24",
    noise="1Jy",
)
SIM_MODES = {
    "track": _SIM_TRACK,
    "snapshot": dict(_SIM_TRACK, timerange=("-30s", "30s"),
                     expected_integrations=1),
}
if SIM_MODE not in SIM_MODES:
    raise ValueError("unknown NGVLA_SIM_MODE=%r; known modes: %s"
                     % (SIM_MODE, sorted(SIM_MODES)))
# the active simulation preset (simulate.py imports SIM)
SIM = SIM_MODES[SIM_MODE]

OVERSAMPLE = 5           # pixels per synthesized-beam FWHM (via im.advise)


def config_suffix():
    """Path suffix for the active combo: "" for the default mono campaign,
    else "-<rev>_<sim_mode>[_<band>]" so each combination writes to FRESH directories
    (results-revD_track/, ms-revD_track/, ...) and never collides with the
    Rev F / track data.  Used by all four path constants below."""
    if not MFS and (REV, SIM_MODE) == ("revF", "track"):
        return ""
    parts = [REV, SIM_MODE]
    if BAND:
        parts.append(BAND)
    return "-" + "_".join(parts)


def artifact_suffix():
    """Combo suffix plus an optional isolated MFS pilot/run variant.

    Variants deliberately do not affect ``CFG_DIR`` because antenna geometry
    is independent of channelization.  They do isolate every mutable or large
    artifact (manifest, result table, profile, MS, and tclean work directory),
    allowing nchan pilots to coexist without weakening manifest validation.
    """
    suffix = config_suffix()
    if CAMPAIGN_VARIANT:
        suffix += "_" + CAMPAIGN_VARIANT
    return suffix


_CONFIG_SUFFIX = config_suffix()
_SUFFIX = artifact_suffix()

# configs and results are small (cfg files + CSVs) and live in the repo;
# per-combo they get the suffix (default -> unchanged repo dirs).
CFG_DIR = os.path.join(REPO, "curvegen", "configs" + _CONFIG_SUFFIX)
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

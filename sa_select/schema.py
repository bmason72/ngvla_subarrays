"""
Data model for the NGVLA subarray-selection tool.

Everything the tool passes around is one of the three dataclasses below, plus the
two CSV tables under ``sa_select/data/`` whose columns are documented here.

Units convention (used everywhere in this package):
  * angles / resolutions / LAS / tapers : arcsec
  * frequency                           : GHz
  * flux density                        : Jy/beam
  * brightness temperature              : K
  * time                                : hours
  * correlator dump time                : seconds
  * raw data volume                     : number of visibilities
  * baseline lengths                    : meters

Reference frequency: selector-facing mono curve tables are tabulated at 30 GHz.
Resolutions scale as lambda, i.e. res(f) = res_30GHz * (30 / f_GHz), and so
does the LAS. Broadband MFS campaign rows are fixed-window native products;
they are registered separately and deliberately excluded from that scaling API.

-------------------------------------------------------------------------------
CSV table: data/config_registry.csv   (one row per campaign combination)
  rev, sim_mode  configuration and time-sampling axes
  band           empty for mono; band4 for the first Ka MFS campaign
  ref_freq_ghz, freq_lo_ghz, freq_hi_ghz
                 fixed-window MFS spectral definition (empty for mono)
  nchan          required MFS channel count; may remain empty before bmason's
                 pilot decision, in which case NGVLA_NCHAN is mandatory
  curve_types    both or ptsrc
  noise_policy   channel noise-weighting convention (currently equal)
  subarrays_csv, samples_csv
                 package-relative metadata and collected-curve filenames

-------------------------------------------------------------------------------
CSV table: data/subarrays.csv   (one row per subarray)
  name         canonical subarray name: core, spiral, mid, core+spiral,
               core+mid, spiral+mid, main
  components   '+'-separated Rev F component configs the subarray is built from
  n_ant        number of antennas
  b_min_m      shortest baseline (m), from the Rev F .cfg positions
  b_max_m      longest baseline (m)
  las_coeff    LAS = las_coeff * lambda / b_min  (memo 67; provisional for
               subarrays memo 67 did not measure -- see las_coeff_note)
  calc_name    subarray key understood by the ngVLA sensitivity calculator,
               or '' if the calculator has no entry (e.g. core+mid)
  las_coeff_note  provenance / caveat for las_coeff
  beam_cap_arcsec_30ghz  heterogeneous beam cap (arcsec at 30 GHz), empty for
               uncapped subarrays.  Beams coarser than the coarsest component's
               own native beam are always better made with that component
               (curvegen/config.BEAM_CAP_ARCSEC), so offered curves / selector
               answers are clipped here; samples measured beyond the cap serve
               as interpolation anchors only (9 Jul 2026, see PLAN.md)
  beam_cap_arcsec_native  MFS-only equivalent measured in that fixed window's
               native reference frame; never stored in the 30-GHz field

CSV tables: data/revf_curves.csv, data/bootstrap_curves.csv
  (one row per measured curve *sample*)
  Raw (resolution, eta, skirt) samples; the point-source and imaging "curves"
  are derived from these at query time by curves.py (imaging = only samples
  with skirt <= threshold). Bootstrap samples come from the memo-121 CSVs and
  were the stand-in until the Rev F curves (revf_curves.csv, from
  curvegen/collect.py) were generated (PLAN.md Track 2).
  subarray               canonical name (see above)
  resolution_arcsec_30ghz  beam FWHM scaled to 30 GHz (geometric mean if elliptical)
  eta                    sensitivity-loss factor vs natural weighting (>= 1)
  skirt                  PSF level at radius = 1 FWHM (0..1), empty if unknown
  weighting              'natural' or 'briggs'
  robust                 Briggs robust value (empty for natural)
  taper_arcsec_30ghz     uv-taper FWHM on the sky, scaled to 30 GHz (empty if none)
  freq_orig_ghz          frequency the sample was originally measured at
  source                 provenance, e.g. 'memo121:MainCln.csv:PF3(KSG1).1'
  note                   free-form caveat
  sample_status          'ok' (default when the column is absent, e.g. the
                         bootstrap table) or 'capped_anchor': measured beyond
                         the subarray's beam cap, usable as an interpolation
                         anchor but never offered as an answer itself

CSV tables: data/*_band*_curves.csv
  Fixed-window MFS samples use a deliberately incompatible native schema:
  subarray, band, ref_freq_ghz, resolution_arcsec_native, eta, skirt,
  weighting, robust, taper_arcsec_native, source, note, sample_status.
  Native angles belong to the complete registered spectral window and must
  never be interpreted as monochromatic 30-GHz quantities or scaled as 30/f.
-------------------------------------------------------------------------------
"""

from dataclasses import dataclass, field
import math
from typing import Dict, Optional, List


@dataclass
class ObservingRequest:
    """What the astronomer asks for."""

    resolution: float                 # target beam FWHM (arcsec)
    frequency: float                  # GHz
    sensitivity: Optional[float] = None   # goal, in `sensitivity_unit`
    sensitivity_unit: str = "Jy/beam"     # 'Jy/beam' or 'K'
    las: Optional[float] = None       # largest angular scale needed (arcsec)
    imaging: bool = True              # True: apply PSF-skirt constraint
    beam_margin: float = 0.05         # fractional tolerance on achieved beam
    skirt_threshold: float = 0.10     # max PSF level at r = 1 FWHM (imaging only)
    skirt_relax: bool = True          # if the threshold is unachievable at the
                                      # requested resolution, fall back to the
                                      # best achievable skirt (flagged) rather
                                      # than excluding the subarray -- angular
                                      # resolution is the primary requirement
    optimize: str = "antenna_hours"   # built-in heuristic name, see heuristics.py
    strict_first: bool = True          # imaging: rank skirt-met candidates before
                                      # relaxed candidates; False lets a custom
                                      # heuristic compare the mixed pool
    delta_v: Optional[float] = None   # channel width for line sensitivity (m/s);
                                      # None -> calculator's continuum default
    normalization_warnings: List[str] = field(default_factory=list, init=False,
                                               repr=False)

    def __post_init__(self):
        if self.sensitivity_unit not in ("Jy/beam", "K"):
            raise ValueError("sensitivity_unit must be 'Jy/beam' or 'K'")
        if (not math.isfinite(self.resolution)
                or not math.isfinite(self.frequency)
                or self.resolution <= 0 or self.frequency <= 0):
            raise ValueError("resolution and frequency must be positive")
        if self.sensitivity is not None and (
                not math.isfinite(self.sensitivity) or self.sensitivity <= 0):
            raise ValueError("sensitivity must be positive when supplied")
        if self.las is not None and (not math.isfinite(self.las) or self.las <= 0):
            raise ValueError("las must be positive when supplied")
        if not math.isfinite(self.skirt_threshold) or not 0 <= self.skirt_threshold <= 1:
            raise ValueError("skirt_threshold must be between 0 and 1")
        if not math.isfinite(self.beam_margin):
            raise ValueError("beam_margin must be finite")
        if self.beam_margin < 0:
            self.normalization_warnings.append(
                "negative beam_margin treated as exact (0)")
            self.beam_margin = 0.0
        if self.beam_margin >= 1:
            raise ValueError("beam_margin must be less than 1")
        if self.delta_v is not None and (
                not math.isfinite(self.delta_v) or self.delta_v <= 0):
            raise ValueError("delta_v must be positive when supplied")


@dataclass
class SubarrayInfo:
    """Static facts about one subarray (a row of data/subarrays.csv)."""

    name: str
    components: str
    n_ant: int
    b_min_m: float
    b_max_m: float
    las_coeff: float
    calc_name: str = ""
    las_coeff_note: str = ""
    beam_cap_arcsec: Optional[float] = None   # at 30 GHz; None = uncapped

    def las_arcsec(self, freq_ghz: float) -> float:
        """Largest angular scale (arcsec) at freq_ghz: las_coeff * lambda / b_min."""
        lambda_m = 0.299792458 / freq_ghz          # c/f with f in GHz -> meters
        return self.las_coeff * lambda_m / self.b_min_m * 206264.8


@dataclass
class CurveSample:
    """One measured (resolution, eta, skirt) point for a subarray at 30 GHz."""

    subarray: str
    resolution: float                 # arcsec at 30 GHz
    eta: float
    weighting: str                    # 'natural' or 'briggs'
    skirt: Optional[float] = None     # None = not measured
    robust: Optional[float] = None
    taper: Optional[float] = None     # arcsec at 30 GHz
    freq_orig: Optional[float] = None
    source: str = ""
    note: str = ""
    sample_status: str = "ok"         # 'ok' | 'capped_anchor' (see docstring)


@dataclass
class Candidate:
    """One subarray evaluated against a request -- a row of the tool's output.

    ``feasible`` is False when the subarray cannot satisfy the request;
    ``reasons`` then says why (there may be several).  Feasible candidates
    carry the imaging parameters that achieve the requested beam and the
    required time for either a user goal or the one-minute-MAIN fiducial.
    """

    subarray: SubarrayInfo
    feasible: bool = False
    reasons: List[str] = field(default_factory=list)    # fatal exclusions
    warnings: List[str] = field(default_factory=list)   # non-fatal caveats
                                                        # (e.g. relaxed skirt)

    # structured imaging-policy state (None for point-source/no curve answer)
    skirt_required: Optional[float] = None
    skirt_met: Optional[bool] = None
    skirt_relaxed: bool = False

    # imaging solution (None until filled in)
    resolution: Optional[float] = None    # achieved beam FWHM (arcsec) at request freq
    eta: Optional[float] = None
    weighting: Optional[str] = None
    robust: Optional[float] = None
    taper: Optional[float] = None         # arcsec at the request frequency
    skirt: Optional[float] = None
    las: Optional[float] = None           # subarray LAS (arcsec) at request freq

    # cost (user goal or one-minute-MAIN fiducial; None only if cost failed)
    sensitivity_jy: Optional[float] = None   # goal converted to Jy/beam
    integration_time_hr: Optional[float] = None
    antenna_hours: Optional[float] = None
    n_visibilities: Optional[float] = None  # one channel; fixed release dump time
    cost_status: str = "pending"             # pending | available | unavailable | failed
    cost_error: str = ""
    goal_origin: Optional[str] = None         # user | main_natural_1min_fiducial

    source: str = ""                      # provenance of the curve sample used

    def tclean_pars(self) -> dict:
        """The tclean weighting parameters as keyword-ready values."""
        pars = {"weighting": self.weighting}
        if self.weighting == "briggs":
            pars["robust"] = self.robust
        if self.taper:
            pars["uvtaper"] = ["%.4garcsec" % self.taper]
        return pars


@dataclass(frozen=True)
class SelectionWarning:
    """Structured result-level diagnostic safe for API/batch consumers."""

    code: str
    message: str
    details: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(code=self.code, message=self.message, details=dict(self.details))

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
  * baseline lengths                    : meters

Reference frequency: curve tables are tabulated at 30 GHz. Resolutions scale as
lambda, i.e.  res(f) = res_30GHz * (30 / f_GHz),  and so does the LAS.

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

CSV table: data/bootstrap_curves.csv   (one row per measured curve *sample*)
  Raw (resolution, eta, skirt) samples; the point-source and imaging "curves"
  are derived from these at query time by curves.py (imaging = only samples
  with skirt <= threshold). Bootstrap samples come from the memo-121 CSVs and
  are a stand-in until Rev F curves are generated (PLAN.md Track 2).
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
-------------------------------------------------------------------------------
"""

from dataclasses import dataclass, field
from typing import Optional, List


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
    optimize: str = "antenna_hours"   # built-in heuristic name, see heuristics.py
    delta_v: Optional[float] = None   # channel width for line sensitivity (m/s);
                                      # None -> calculator's continuum default

    def __post_init__(self):
        if self.sensitivity_unit not in ("Jy/beam", "K"):
            raise ValueError("sensitivity_unit must be 'Jy/beam' or 'K'")
        if self.resolution <= 0 or self.frequency <= 0:
            raise ValueError("resolution and frequency must be positive")


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


@dataclass
class Candidate:
    """One subarray evaluated against a request -- a row of the tool's output.

    ``feasible`` is False when the subarray cannot satisfy the request;
    ``reasons`` then says why (there may be several).  Feasible candidates
    carry the imaging parameters that achieve the requested beam and, when a
    sensitivity goal was given, the required time.
    """

    subarray: SubarrayInfo
    feasible: bool = False
    reasons: List[str] = field(default_factory=list)

    # imaging solution (None until filled in)
    resolution: Optional[float] = None    # achieved beam FWHM (arcsec) at request freq
    eta: Optional[float] = None
    weighting: Optional[str] = None
    robust: Optional[float] = None
    taper: Optional[float] = None         # arcsec at the request frequency
    skirt: Optional[float] = None
    las: Optional[float] = None           # subarray LAS (arcsec) at request freq

    # cost (None when no sensitivity goal was given)
    sensitivity_jy: Optional[float] = None   # goal converted to Jy/beam
    integration_time_hr: Optional[float] = None
    antenna_hours: Optional[float] = None

    source: str = ""                      # provenance of the curve sample used

    def tclean_pars(self) -> dict:
        """The tclean weighting parameters as keyword-ready values."""
        pars = {"weighting": self.weighting}
        if self.weighting == "briggs":
            pars["robust"] = self.robust
        if self.taper:
            pars["uvtaper"] = ["%.4garcsec" % self.taper]
        return pars

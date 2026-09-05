"""
Adapters for Michael Stroh's delivery formats (docs/plans/RELEASE_PLAN.md T5).

Two input formats are supported (see docs/architecture/mstroh_comparison.md for the full
review of the delivery):

1. **Per-subarray CASA ``.cfg`` files** (``ngvla-revF.<subarray>.cfg``: one
   monolithic file per complete subarray, CASA XYZ format).
   ``subarray_info_from_cfg`` turns one into a ``SubarrayInfo`` (n_ant and
   physical b_min/b_max computed from the antenna positions, with an
   optional spurious-short-baseline cut).

2. **``subarray_data.json``** (the format his sensitivity curves shipped
   in): per subarray ``b_min``/``b_max``/``N_ant``/``theta_nat_30_GHz`` plus
   an eta(resolution) cubic spline in scipy PPoly form.
   ``curve_library`` builds a ready-to-query ``CurveLibrary`` from it, so
   ``select_subarrays`` can rank subarrays against his curves directly.

Convention conversions applied on load (both verified against his package,
docs/architecture/mstroh_comparison.md):

* **sqrt(2) beam convention**: his resolution scalar is
  ``1000*sqrt(bmaj^2 + bmin^2)`` mas -- a quadrature sum, ~sqrt(2) larger
  than a real FWHM for a near-circular beam.  Everything this module
  returns is divided by sqrt(2) (geometric-mean FWHM, our convention).
* **spline evaluation**: ``spline_params = [coefficients, breakpoints]``
  for ``scipy.interpolate.PPoly``; x = log10(theta_mas in HIS convention),
  y = eta.

Caveats carried as sample notes / metadata (do not silence them):

* His curves are point-source (taperability) only -- no skirt/sculpting --
  so imaging queries against a Stroh library find no sculpted samples.
* His delivery does not record which (robust, taper) achieves each point,
  so the tclean parameters this library reports are PLACEHOLDERS (the
  taper is set to the sample's own resolution -- roughly right in the
  taper-dominated regime, wrong near native).  Every sample carries a note
  saying so, which ``select_subarrays`` surfaces as a candidate warning.
* His eta is normalized to the minimum rms over his grid rather than a
  true natural point, and his b_min/b_max are projected uv distances at
  mid-track rather than physical baselines (used for LAS unless you build
  the metadata from his .cfg files instead).
"""

import json
import math
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

from .schema import SubarrayInfo, CurveSample
from .curves import CurveLibrary

SQRT2 = math.sqrt(2.0)

_PLACEHOLDER_NOTE = ("Stroh spline curve: the delivery does not record "
                     "robust/taper per point; the reported taper is a "
                     "placeholder (= the resolution), NOT a validated "
                     "tclean parameter")

_LAS_NOTE = ("b_min/b_max are Stroh's projected mid-track uv distances, not "
             "physical baselines; LAS = 0.80*lambda/b_min on that convention "
             "(rebuild from his .cfg files via subarray_info_from_cfg for "
             "physical baselines).")


# ---------------------------------------------------------------------------
# 1. per-subarray .cfg files
# ---------------------------------------------------------------------------

def read_cfg(path: str) -> Tuple[List[str], np.ndarray]:
    """Antenna (names, XYZ positions [m]) from one CASA-format .cfg file."""
    names, xyz = [], []
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = ln.split()
            xyz.append([float(v) for v in parts[:3]])
            names.append(parts[4] if len(parts) > 4 else "ant%d" % len(names))
    if not xyz:
        raise ValueError("no antenna rows in %s" % path)
    return names, np.array(xyz)


def _baseline_stats(xyz: np.ndarray, min_uvrange_m: Optional[float] = None
                    ) -> Tuple[int, float, float]:
    """(n_ant, b_min_m, b_max_m); b_min honors an optional spurious-short cut
    (the shortest baseline STRICTLY longer than the cut)."""
    n = len(xyz)
    d = xyz[:, None, :] - xyz[None, :, :]
    lengths = np.sqrt((d ** 2).sum(-1))[np.triu_indices(n, 1)]
    b_max = float(lengths.max())
    if min_uvrange_m is not None:
        kept = lengths[lengths > min_uvrange_m]
        if kept.size == 0:
            raise ValueError("uvrange cut %g m removed ALL baselines"
                             % min_uvrange_m)
        b_min = float(kept.min())
    else:
        b_min = float(lengths.min())
    return n, b_min, b_max


def subarray_info_from_cfg(name: str, path: str, las_coeff: float = 0.8,
                           min_uvrange_m: Optional[float] = None,
                           calc_name: str = "") -> SubarrayInfo:
    """SubarrayInfo for one MStroh-style monolithic subarray .cfg file."""
    _, xyz = read_cfg(path)
    n, b_min, b_max = _baseline_stats(xyz, min_uvrange_m)
    note = ("geometry from %s (physical baselines%s); LAS = "
            "%.2f*lambda/b_min (memo 67, applied uniformly)"
            % (os.path.basename(path),
               "" if min_uvrange_m is None
               else ", uvrange>%gm cut" % min_uvrange_m,
               las_coeff))
    return SubarrayInfo(name=name, components=name, n_ant=n, b_min_m=b_min,
                        b_max_m=b_max, las_coeff=las_coeff,
                        calc_name=calc_name, las_coeff_note=note)


# ---------------------------------------------------------------------------
# 2. subarray_data.json (curves)
# ---------------------------------------------------------------------------

def load_subarray_data(path: str) -> Dict[str, dict]:
    """Parse subarray_data.json: {name: entry}.  Each entry keeps Stroh's raw
    fields plus ``ppoly`` (the scipy PPoly, x = log10(theta_mas, HIS sqrt2
    convention)) and ``theta_nat_arcsec`` (converted to geometric-mean FWHM,
    arcsec)."""
    from scipy.interpolate import PPoly       # scipy needed only here

    with open(path) as f:
        raw = json.load(f)
    out = {}
    for name, e in raw.items():
        entry = dict(e)
        if e.get("spline_type") != "cubic" or "spline_params" not in e:
            entry["ppoly"] = None             # e.g. sba: no taper support
        else:
            coef, breaks = e["spline_params"]
            entry["ppoly"] = PPoly(np.asarray(coef), np.asarray(breaks))
        entry["theta_nat_arcsec"] = e["theta_nat_30_GHz"] / SQRT2 / 1000.0
        out[name] = entry
    return out


def curve_samples(name: str, entry: dict, n_points: int = 80
                  ) -> List[CurveSample]:
    """His eta(resolution) spline as CurveSamples at 30 GHz (geometric-mean
    FWHM convention), presented as ONE natural+taper row so the shared
    envelope engine can interpolate it.  Point-source only (skirt=None)."""
    pp = entry.get("ppoly")
    if pp is None:
        return []
    x = np.linspace(pp.x[0], pp.x[-1], n_points)
    samples = []
    for xi in x:
        res_arcsec = 10.0 ** float(xi) / SQRT2 / 1000.0
        eta = float(pp(float(xi)))
        if not np.isfinite(eta) or eta <= 0:
            continue
        samples.append(CurveSample(
            subarray=name, resolution=res_arcsec, eta=eta,
            weighting="natural", robust=None,
            taper=res_arcsec,               # placeholder, see module docstring
            skirt=None, source="stroh", note=_PLACEHOLDER_NOTE))
    return samples


def subarray_info_from_entry(name: str, entry: dict,
                             las_coeff: float = 0.8) -> SubarrayInfo:
    """SubarrayInfo from a subarray_data.json entry (his uv-projected
    b_min/b_max -- see _LAS_NOTE)."""
    return SubarrayInfo(name=name, components=name,
                        n_ant=int(entry["N_ant"]),
                        b_min_m=float(entry["b_min"]),
                        b_max_m=float(entry["b_max"]),
                        las_coeff=las_coeff, calc_name="",
                        las_coeff_note=_LAS_NOTE)


def curve_library(json_path: str, n_points: int = 80,
                  las_coeff: float = 0.8) -> CurveLibrary:
    """A ready-to-query CurveLibrary built entirely from subarray_data.json.

    Subarrays without a spline (e.g. sba) get metadata but no curve, so they
    always come back infeasible with a clear reason.  Imaging queries find no
    sculpted samples anywhere (his curves are point-source only).
    """
    data = load_subarray_data(json_path)
    return CurveLibrary.from_tables(
        {name: subarray_info_from_entry(name, e, las_coeff)
         for name, e in data.items()},
        {name: curve_samples(name, e, n_points)
         for name, e in data.items()})

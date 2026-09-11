"""Exact physical baseline distributions used by the optional rank metrics.

The packaged data are deliberately independent of the curve-generation
environment.  They contain EVERY unordered antenna pair for each supported
configuration revision -- no uv-range cut is applied.  In particular,
``config.MIN_UVRANGE_M`` (the spurious ~3-antenna-cluster short-baseline
cut used for curve generation / imaging, where those cluster baselines
really do distort the PSF and eta) is deliberately NOT ported into this
geometry: for the ``efficient``/``performance`` ranking metrics below, Bmin
and Bmax alone decide which pairs count in a requested science-baseline
interval, so ``n_pairs`` always equals ``n_ant*(n_ant-1)/2`` here, even for
LONG-containing subarrays.

This was tried the other way (the cut applied here) on 11 Sep 2026 and
reversed the same day (bmason): dropping those pairs from ``lengths_m``
while still charging them in the ``n_ant*(n_ant-1)/2`` denominator
permanently penalized those subarrays with no way to ever earn credit for
the pairs, even for a request whose Bmin is small enough that they should
naturally fall in range. See ``curvegen/build_baseline_data.py``'s module
docstring, ``docs/plans/baseline-window-plan.md`` (decision 5 / W3), and
``docs/worklog/baseline-ranking.md`` (11 Sep 2026 entries). Do not
reintroduce the cut here a third time. Projection is still NOT applied:
lengths are exact unprojected 3-D physical distances.
"""

from __future__ import annotations

import bisect
import gzip
import json
import math
from importlib import resources
from functools import lru_cache
from typing import Any, Dict, Mapping, Optional


_ARCSEC_PER_RADIAN = 206264.8
_DATA_FILE = "data/baseline_geometry.json.gz"

# When the PI supplies no LAS, Bmin defaults to DEFAULT_LAS_RATIO times the
# requested resolution instead of 0.  An implicit Bmin = 0 invents its own
# science requirement (everything shorter than Bmax "counts"), which badly
# inflated large subarrays: at 30 GHz / 0.01" with no LAS, `main` scored 0.824
# vs `mid` 0.372 under `efficient` -- backwards (docs/plans/baseline-window-plan.md).
#
# Verified acceptance (docs/plans/baseline-window-plan.md): at this ratio,
# `core`, `spiral` and `mid` each rank #1 under `efficient` at their own
# natural resolution, with efficiencies 0.911 / 0.948 / 0.845 respectively.
#
# COUPLING CAVEAT (decision 1): this ratio is tuned jointly with Bmax's 1.02
# Airy factor below, which stays fixed (bmason, 11 Sep 2026 -- it is
# physical, independent of array configuration).  At that Bmax factor, only
# LAS ratios 5 and 10 satisfy the acceptance criterion above: ratio 30 drops
# `core` to rank 2, and ratio 100 fails two of the three cases.  Do NOT raise
# this ratio in isolation -- raising it requires raising the Bmax factor too.
DEFAULT_LAS_RATIO = 10.0


def load_baseline_geometry(rev: str) -> Dict[str, Dict[str, Any]]:
    """Return exact pair-length geometry for configuration revision *rev*.

    ``rev`` is the registered revision spelling (for example ``"revF"``).
    A newly allocated mapping is returned so callers cannot mutate the cached
    package payload.  Missing revisions are an error: assigning a familiar
    subarray name to geometry from another revision would be scientifically
    misleading.
    """
    if not isinstance(rev, str) or not rev.strip():
        raise ValueError("baseline geometry revision must be a non-empty string")
    try:
        payload = _load_payload()
        entries = payload["revisions"][rev]
    except (KeyError, TypeError) as exc:
        raise ValueError("no baseline geometry is packaged for revision %r" % rev) from exc
    return {
        name: {
            "n_ant": int(entry["n_ant"]),
            "n_pairs": int(entry["n_pairs"]),
            "lengths_m": list(entry["lengths_m"]),
            "provenance": dict(entry["provenance"]),
        }
        for name, entry in entries.items()
    }


@lru_cache(maxsize=1)
def _load_payload() -> Mapping[str, Any]:
    """Read package data lazily, keeping import of the selector inexpensive."""
    path = resources.files("sa_select").joinpath(_DATA_FILE)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping) or payload.get("format_version") != 2:
        raise ValueError("unsupported packaged baseline geometry format")
    return payload


def baseline_metrics(geometry: Mapping[str, Any], frequency_ghz: float,
                     resolution_arcsec: float, las_arcsec: Optional[float],
                     las_coeff: float) -> Dict[str, Any]:
    """Count physical antenna pairs in a requested science-baseline interval.

    ``las_arcsec=None`` means the PI supplied no LAS: Bmin then uses a default
    LAS of ``DEFAULT_LAS_RATIO * resolution_arcsec`` (see that constant's
    comment for the derivation and its coupling to Bmax's Airy factor) --
    this is purely a Bmin convenience default and is reported back as
    ``baseline_las_defaulted`` so callers never mistake it for a PI-supplied
    LAS; it must never be used for LAS *feasibility* (that stays keyed on the
    PI-supplied value only, in the selector).  Bounds are inclusive, and
    counts use the full physical distribution (including Long's short
    intra-site pairs).  The requested resolution supplies the upper bound;
    this routine does not make a geometric feasibility decision.
    """
    n_ant, lengths, provenance = _validate_geometry(geometry)
    frequency_ghz = _positive_finite(frequency_ghz, "frequency_ghz")
    resolution_arcsec = _positive_finite(resolution_arcsec, "resolution_arcsec")
    las_coeff = _positive_finite(las_coeff, "las_coeff")
    wavelength_m = 0.299792458 / frequency_ghz
    b_max = 1.02 * wavelength_m * _ARCSEC_PER_RADIAN / resolution_arcsec
    las_defaulted = las_arcsec is None
    if las_defaulted:
        las_effective = DEFAULT_LAS_RATIO * resolution_arcsec
    else:
        las_effective = _positive_finite(las_arcsec, "las_arcsec")
    b_min = las_coeff * wavelength_m * _ARCSEC_PER_RADIAN / las_effective
    if not math.isfinite(b_min) or not math.isfinite(b_max) or b_min > b_max:
        raise ValueError("requested baseline bounds are invalid or inverted")
    in_range = bisect.bisect_right(lengths, b_max) - bisect.bisect_left(lengths, b_min)
    total = n_ant * (n_ant - 1) // 2
    return {
        "baseline_min_m": b_min,
        "baseline_max_m": b_max,
        "baselines_in_range": in_range,
        "baselines_total": total,
        "baseline_efficiency": in_range / total,
        "baseline_provenance": provenance,
        "baseline_las_arcsec": las_effective,
        "baseline_las_defaulted": las_defaulted,
    }


def _positive_finite(value: Any, name: str) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("%s must be a finite positive number" % name) from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("%s must be a finite positive number" % name)
    return value


def _validate_geometry(geometry: Mapping[str, Any]):
    if not isinstance(geometry, Mapping):
        raise ValueError("baseline geometry must be a mapping")
    try:
        raw_n_ant = geometry["n_ant"]
        n_ant = int(raw_n_ant)
        lengths = geometry["lengths_m"]
        provenance = geometry["provenance"]
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("baseline geometry is missing required fields") from exc
    if (isinstance(raw_n_ant, bool) or n_ant != raw_n_ant or n_ant < 2
            or not isinstance(lengths, (list, tuple))
            or not isinstance(provenance, Mapping)):
        raise ValueError("baseline geometry has invalid fields")
    total = n_ant * (n_ant - 1) // 2
    # No uv-range cut is applied when this geometry is packaged (see
    # curvegen/build_baseline_data.py and this module's docstring), so every
    # packaged entry has exactly n_ant*(n_ant-1)/2 pairs. The <= check (rather
    # than strict equality) is kept as a generic robustness bound for any
    # geometry a caller supplies directly, not because a cut is expected.
    if len(lengths) > total:
        raise ValueError("baseline geometry length count exceeds antenna-pair count")
    if "n_pairs" in geometry:
        try:
            n_pairs = int(geometry["n_pairs"])
        except (TypeError, ValueError) as exc:
            raise ValueError("baseline geometry n_pairs is invalid") from exc
        if n_pairs != len(lengths):
            raise ValueError("baseline geometry n_pairs does not match lengths_m count")
    if any(isinstance(item, bool) for item in lengths):
        raise ValueError("baseline geometry contains an invalid length")
    try:
        lengths = [float(item) for item in lengths]
    except (TypeError, ValueError) as exc:
        raise ValueError("baseline geometry contains a non-numeric length") from exc
    if any(not math.isfinite(item) or item < 0 for item in lengths):
        raise ValueError("baseline geometry contains an invalid length")
    if any(left > right for left, right in zip(lengths, lengths[1:])):
        raise ValueError("baseline geometry lengths are not sorted")
    return n_ant, lengths, dict(provenance)

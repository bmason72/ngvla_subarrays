"""
Curve library: loads the tabulated per-subarray data and answers the question
"what does it cost (eta) for subarray X to make beam theta at frequency f,
and which tclean parameters get me there?"

The on-disk tables (see schema.py docstring for columns) hold raw curve
*samples* at the 30 GHz reference frequency.  The point-source and imaging
"curves" of the memos are derived here at query time:

  * point-source curve : minimum-eta sample near a target resolution,
                         PSF skirt ignored;
  * imaging curve      : same, but only samples whose skirt <= threshold
                         qualify (memo 65/121 beam sculpting).

Frequency scaling: resolutions and tapers scale as lambda, so a sample at
30 GHz maps to frequency f by multiplying by (30/f).  eta is assumed
invariant under this scaling (PLAN.md open question 2).
"""

import csv
import os
from typing import Dict, List, Optional, Tuple

from .schema import SubarrayInfo, CurveSample

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
REF_FREQ_GHZ = 30.0


def _float_or_none(s: str) -> Optional[float]:
    s = s.strip()
    return float(s) if s else None


def load_subarrays(path: Optional[str] = None) -> Dict[str, SubarrayInfo]:
    """Read data/subarrays.csv into {name: SubarrayInfo}."""
    path = path or os.path.join(DATA_DIR, "subarrays.csv")
    out = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            info = SubarrayInfo(
                name=row["name"].strip(),
                components=row["components"].strip(),
                n_ant=int(row["n_ant"]),
                b_min_m=float(row["b_min_m"]),
                b_max_m=float(row["b_max_m"]),
                las_coeff=float(row["las_coeff"]),
                calc_name=row.get("calc_name", "").strip(),
                las_coeff_note=row.get("las_coeff_note", "").strip(),
            )
            out[info.name] = info
    return out


def load_samples(path: Optional[str] = None) -> Dict[str, List[CurveSample]]:
    """Read a curve-sample table into {subarray: [CurveSample, ...]}."""
    path = path or os.path.join(DATA_DIR, "bootstrap_curves.csv")
    out: Dict[str, List[CurveSample]] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            s = CurveSample(
                subarray=row["subarray"].strip(),
                resolution=float(row["resolution_arcsec_30ghz"]),
                eta=float(row["eta"]),
                weighting=row["weighting"].strip(),
                skirt=_float_or_none(row.get("skirt", "")),
                robust=_float_or_none(row.get("robust", "")),
                taper=_float_or_none(row.get("taper_arcsec_30ghz", "")),
                freq_orig=_float_or_none(row.get("freq_orig_ghz", "")),
                source=row.get("source", "").strip(),
                note=row.get("note", "").strip(),
            )
            out.setdefault(s.subarray, []).append(s)
    for samples in out.values():
        samples.sort(key=lambda s: s.resolution)
    return out


class CurveLibrary:
    """Tabulated subarray curves + metadata, with the query logic."""

    def __init__(self, subarrays: Optional[str] = None, samples: Optional[str] = None):
        self.subarrays = load_subarrays(subarrays)
        self.samples = load_samples(samples)

    def names(self) -> List[str]:
        return list(self.subarrays)

    # ------------------------------------------------------------------ #

    def qualifying_samples(self, name: str, skirt_threshold: Optional[float]
                           ) -> List[CurveSample]:
        """Samples usable for a query: all of them (point-source,
        skirt_threshold=None) or only sculpted ones (imaging).

        A sample with no skirt measurement cannot be shown to satisfy the
        imaging constraint, so it is excluded when a threshold is given.
        """
        samples = self.samples.get(name, [])
        if skirt_threshold is None:
            return samples
        return [s for s in samples
                if s.skirt is not None and s.skirt <= skirt_threshold]

    def resolution_range(self, name: str, freq_ghz: float,
                         skirt_threshold: Optional[float]) -> Optional[Tuple[float, float]]:
        """(finest, coarsest) tabulated resolution (arcsec) at freq_ghz."""
        q = self.qualifying_samples(name, skirt_threshold)
        if not q:
            return None
        scale = REF_FREQ_GHZ / freq_ghz
        return (q[0].resolution * scale, q[-1].resolution * scale)

    def solve(self, name: str, resolution: float, freq_ghz: float,
              beam_margin: float = 0.05,
              skirt_threshold: Optional[float] = None
              ) -> Tuple[Optional[CurveSample], str]:
        """Find the minimum-eta way for subarray `name` to reach `resolution`
        (arcsec) at `freq_ghz`, within a fractional beam tolerance.

        Returns (sample, message).  The sample is returned in REFERENCE
        (30 GHz) units -- use scale_sample() for request-frequency values.
        On failure the sample is None and the message says why.

        v1 note: with sparse bootstrap data we pick the best *tabulated*
        sample inside the tolerance window rather than interpolating; the
        dense Track-2 grids will make this exact (PLAN.md section 5).
        """
        q = self.qualifying_samples(name, skirt_threshold)
        if not q:
            if name not in self.samples or not self.samples[name]:
                return None, "no curve data tabulated for this subarray"
            return None, ("no tabulated (robust, taper) combination meets the "
                          "PSF-skirt threshold of %.2g" % skirt_threshold)

        # work at the reference frequency: the window scales the same way
        res_ref = resolution * freq_ghz / REF_FREQ_GHZ
        lo, hi = res_ref * (1 - beam_margin), res_ref * (1 + beam_margin)
        in_window = [s for s in q if lo <= s.resolution <= hi]
        if not in_window:
            scale = REF_FREQ_GHZ / freq_ghz
            return None, ("no tabulated solution within +/-%.0f%% of %.4g arcsec; "
                          "nearest qualifying samples span %.4g - %.4g arcsec "
                          "at this frequency"
                          % (100 * beam_margin, resolution,
                             q[0].resolution * scale, q[-1].resolution * scale))

        best = min(in_window, key=lambda s: s.eta)
        return best, "ok"

    def scale_sample(self, sample: CurveSample, freq_ghz: float) -> CurveSample:
        """Copy of `sample` with resolution and taper scaled 30 GHz -> freq_ghz."""
        scale = REF_FREQ_GHZ / freq_ghz
        return CurveSample(
            subarray=sample.subarray,
            resolution=sample.resolution * scale,
            eta=sample.eta,
            weighting=sample.weighting,
            skirt=sample.skirt,
            robust=sample.robust,
            taper=None if sample.taper is None else sample.taper * scale,
            freq_orig=sample.freq_orig,
            source=sample.source,
            note=sample.note,
        )

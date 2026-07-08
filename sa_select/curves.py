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

from .envelope import Envelope, TRADE_SPAN
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
        self._envelopes: Dict[str, Envelope] = {}

    def envelope(self, name: str) -> Envelope:
        """The interpolated curve families for one subarray (cached)."""
        env = self._envelopes.get(name)
        if env is None:
            env = Envelope([dict(res=s.resolution, eta=s.eta, skirt=s.skirt,
                                 weighting=s.weighting, robust=s.robust,
                                 taper=s.taper, ref=s)
                            for s in self.samples.get(name, [])])
            self._envelopes[name] = env
        return env

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
        """(finest, coarsest) RAW tabulated sample resolution (arcsec) at
        freq_ghz.  Diagnostic only: solve() interpolates within lattice rows,
        so for imaging queries it can succeed slightly outside the span of
        the discrete skirt-qualifying samples (at an interpolated
        threshold crossing).  Do not use this as a feasibility gate."""
        q = self.qualifying_samples(name, skirt_threshold)
        if not q:
            return None
        scale = REF_FREQ_GHZ / freq_ghz
        return (q[0].resolution * scale, q[-1].resolution * scale)

    def solve(self, name: str, resolution: float, freq_ghz: float,
              beam_margin: float = 0.05,
              skirt_threshold: Optional[float] = None,
              relax: bool = True
              ) -> Tuple[Optional[CurveSample], str]:
        """Find the minimum-eta way for subarray `name` to reach `resolution`
        (arcsec) at `freq_ghz`, within a fractional beam tolerance.

        Returns (sample, message); message is "ok", a "relaxed: ..." warning,
        or -- with sample None -- the reason there is no solution.  The sample
        is in REFERENCE (30 GHz) units; use scale_sample() for request-
        frequency values.

        Angular resolution is the primary requirement.  When an imaging query
        (skirt_threshold given) finds no beam under the threshold at this
        resolution, and `relax` is True, the skirt criterion is relaxed to the
        best achievable value there (memo 121's 'partial' cases: some beams
        bottom out at ~16%) rather than distorting the resolution or failing.
        The returned message flags the relaxation.
        """
        if name not in self.samples or not self.samples[name]:
            return None, "no curve data tabulated for this subarray"

        # work at the reference frequency: the window scales the same way
        res_ref = resolution * freq_ghz / REF_FREQ_GHZ

        # the envelope engine interpolates within measured lattice rows, so
        # the answer varies continuously with the request (see envelope.py
        # and curve_anomaly_postmortem.md for why the old per-window sample
        # min produced discontinuities)
        choice = self.envelope(name).solve(res_ref, margin=beam_margin,
                                           skirt_max=skirt_threshold,
                                           relax=relax)
        if choice is not None:
            sample = self._choice_to_sample(name, choice)
            if choice.relaxed:
                best = choice.best_skirt if choice.best_skirt is not None \
                    else choice.skirt
                return sample, ("relaxed: no beam here reaches skirt <= %.2g "
                                "(nor the %.2g trade cap); best achievable "
                                "is %.2g (chosen beam: %.2g)"
                                % (skirt_threshold,
                                   skirt_threshold + TRADE_SPAN, best,
                                   choice.skirt))
            if choice.traded:
                return sample, ("traded: skirt %.2g > %.2g accepted under "
                                "the 1-for-1 eta-skirt trade"
                                % (choice.skirt, skirt_threshold))
            return sample, "ok"

        q = self.qualifying_samples(name, skirt_threshold)
        if skirt_threshold is not None and not q:
            return None, ("no tabulated (robust, taper) combination meets the "
                          "PSF-skirt threshold of %.2g" % skirt_threshold)
        scale = REF_FREQ_GHZ / freq_ghz
        if not q:
            return None, "no usable curve data for this subarray"
        return None, ("no tabulated solution within +/-%.0f%% of %.4g arcsec; "
                      "nearest qualifying samples span %.4g - %.4g arcsec "
                      "at this frequency"
                      % (100 * beam_margin, resolution,
                         q[0].resolution * scale, q[-1].resolution * scale))

    def _choice_to_sample(self, name: str, choice) -> CurveSample:
        """Engine Choice -> CurveSample (reference-frequency units).
        Interpolated choices say so in `note` and cite their anchors."""
        note, source = "", ""
        anchors = [a.ref for a in choice.anchors]
        if choice.interpolated:
            beams = sorted(a.res for a in choice.anchors)
            kind = ("within a bilinear (robust, taper) lattice cell"
                    if len(beams) >= 4 else "between measured beams")
            note = ("interpolated %s spanning %.4g-%.4g arcsec (30 GHz)"
                    % (kind, beams[0], beams[-1]))
            source = " <-> ".join(getattr(a, "source", "") or "?"
                                  for a in anchors)
        elif anchors and anchors[0] is not None:
            source = getattr(anchors[0], "source", "")
            note = getattr(anchors[0], "note", "")
        return CurveSample(
            subarray=name,
            resolution=choice.res,
            eta=choice.eta,
            weighting=choice.weighting,
            skirt=choice.skirt,
            robust=choice.robust,
            taper=choice.taper if choice.taper else None,
            freq_orig=REF_FREQ_GHZ,
            source=source,
            note=note,
        )

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

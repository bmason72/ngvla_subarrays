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
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .envelope import Envelope, TRADE_SPAN
from .schema import SubarrayInfo, CurveSample

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
REF_FREQ_GHZ = 30.0


@dataclass(frozen=True)
class CurveSolveResult:
    """Structured query outcome; ``solve()`` keeps the legacy tuple API."""

    sample: Optional[CurveSample]
    message: str
    relaxed: bool = False
    skirt_met: Optional[bool] = None
    best_skirt: Optional[float] = None


def _float_or_none(s: str) -> Optional[float]:
    s = s.strip()
    return float(s) if s else None


def load_registry(path: Optional[str] = None
                  ) -> Dict[Tuple[str, str], Tuple[str, str]]:
    """Read data/config_registry.csv into {(rev, sim_mode): (subs_csv, samp_csv)}.

    The registry maps a configuration revision + simulation mode to the pair of
    data files (both relative to data/) that describe it: the subarray-metadata
    CSV and the curve-sample CSV.  It is the single source of truth for which
    files back a given (rev, sim_mode) -- see CurveLibrary.for_config and
    curvegen/collect.py (which routes its output through the same registry).
    """
    path = path or os.path.join(DATA_DIR, "config_registry.csv")
    out: Dict[Tuple[str, str], Tuple[str, str]] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            # Public selector v1 is intentionally mono-only.  Broadband MFS
            # rows share this registry for campaign routing but are fixed-
            # window native curves and must not enter the 30/f scaling API.
            if (row.get("band") or "").strip():
                continue
            out[(row["rev"].strip(), row["sim_mode"].strip())] = (
                row["subarrays_csv"].strip(), row["samples_csv"].strip())
    return out


def load_campaign_registry(path: Optional[str] = None) -> Dict[Tuple[str, str, str], dict]:
    """Read all mono and MFS campaign rows, keyed by ``(rev, mode, band)``.

    The empty string is the mono band.  Values retain the complete CSV row so
    curve-generation code can validate spectral-window and manifest fields.
    ``load_registry`` remains the backward-compatible selector-facing mono
    projection until the fixed-window MFS selector API is designed.
    """
    path = path or os.path.join(DATA_DIR, "config_registry.csv")
    out = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            key = (row["rev"].strip(), row["sim_mode"].strip(),
                   (row.get("band") or "").strip().lower())
            if key in out:
                raise ValueError("duplicate config_registry.csv entry for %r"
                                 % (key,))
            out[key] = dict(row)
    return out


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
                beam_cap_arcsec=_float_or_none(
                    row.get("beam_cap_arcsec_30ghz", "") or ""),
            )
            out[info.name] = info
    return out


def load_samples(path: Optional[str] = None) -> Dict[str, List[CurveSample]]:
    """Read a curve-sample table into {subarray: [CurveSample, ...]}.

    Defaults to the authoritative Rev F curves (revf_curves.csv, produced by
    curvegen/collect.py).  The older memo-121 bootstrap table
    (bootstrap_curves.csv) is kept for reference; pass it explicitly to use it.
    """
    path = path or os.path.join(DATA_DIR, "revf_curves.csv")
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
                sample_status=(row.get("sample_status") or "ok").strip(),
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

    @classmethod
    def from_tables(cls, subarrays: Dict[str, SubarrayInfo],
                    samples: Dict[str, List[CurveSample]]) -> "CurveLibrary":
        """Build a library directly from in-memory tables (no CSV files) --
        e.g. from an external curve delivery (see sa_select/stroh.py)."""
        lib = cls.__new__(cls)
        lib.subarrays = dict(subarrays)
        lib.samples = {k: sorted(v, key=lambda s: s.resolution)
                       for k, v in samples.items()}
        lib._envelopes = {}
        return lib

    @classmethod
    def for_config(cls, rev: str = "revF", sim_mode: str = "track",
                   registry_path: Optional[str] = None) -> "CurveLibrary":
        """Build a library for a registered (rev, sim_mode) combination.

        Resolves the metadata + curve CSVs through data/config_registry.csv.
        ``for_config("revF", "track")`` is equivalent to ``CurveLibrary()``
        (the default files).  An unregistered combination raises ValueError
        listing the registered ones.
        """
        registry = load_registry(registry_path)
        key = (rev, sim_mode)
        if key not in registry:
            raise ValueError(
                "no config_registry.csv entry for (rev=%r, sim_mode=%r); "
                "registered combinations: %s"
                % (rev, sim_mode, sorted(registry)))
        subs_csv, samp_csv = registry[key]
        return cls(subarrays=os.path.join(DATA_DIR, subs_csv),
                   samples=os.path.join(DATA_DIR, samp_csv))

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
        Capped anchors (measured beyond the beam cap) are interpolation
        support, not offerable answers, so they never qualify.
        """
        samples = [s for s in self.samples.get(name, [])
                   if s.sample_status == "ok"]
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
        """Compatibility wrapper returning the historical ``(sample, msg)``."""
        result = self.solve_detailed(
            name, resolution, freq_ghz, beam_margin=beam_margin,
            skirt_threshold=skirt_threshold, relax=relax)
        return result.sample, result.message

    def solve_detailed(self, name: str, resolution: float, freq_ghz: float,
              beam_margin: float = 0.05,
              skirt_threshold: Optional[float] = None,
              relax: bool = True
              ) -> CurveSolveResult:
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
            return CurveSolveResult(None, "no curve data tabulated for this subarray")

        # work at the reference frequency: the window scales the same way
        res_ref = resolution * freq_ghz / REF_FREQ_GHZ

        # heterogeneous beam cap: never offer a beam coarser than the
        # coarsest component's own native beam (that regime belongs to the
        # component subarray); capped-anchor samples only support
        # interpolation up to the cap
        info = self.subarrays.get(name)
        cap = info.beam_cap_arcsec if info else None
        if cap is not None and res_ref * (1 - beam_margin) > cap:
            return CurveSolveResult(
                None, "requested beam is coarser than this subarray's "
                "beam cap (%.4g arcsec at the request frequency): "
                "beams this coarse are better made with its "
                "coarsest component subarray"
                % (cap * REF_FREQ_GHZ / freq_ghz))

        # the envelope engine interpolates within measured lattice rows, so
        # the answer varies continuously with the request (see envelope.py
        # and curve_anomaly_postmortem.md for why the old per-window sample
        # min produced discontinuities)
        choice = self.envelope(name).solve(res_ref, margin=beam_margin,
                                           skirt_max=skirt_threshold,
                                           relax=relax, max_res=cap)
        if choice is not None:
            sample = self._choice_to_sample(name, choice)
            if choice.relaxed:
                best = choice.best_skirt if choice.best_skirt is not None \
                    else choice.skirt
                return CurveSolveResult(
                    sample,
                    "relaxed: no beam within the tolerance meets "
                    "skirt <= %.2g; best achievable skirt is %.2g "
                    "(reported beam skirt %.2g, eta %.2f) -- does "
                    "NOT meet the criterion"
                    % (skirt_threshold, best, choice.skirt, choice.eta),
                    relaxed=True, skirt_met=False, best_skirt=best)
            if choice.traded:               # only in mode='legacy_trade'
                return CurveSolveResult(
                    sample,
                    "traded: skirt %.2g > %.2g accepted under "
                    "the 1-for-1 eta-skirt trade (legacy mode)"
                    % (choice.skirt, skirt_threshold),
                    skirt_met=False)
            return CurveSolveResult(
                sample, "ok",
                skirt_met=True if skirt_threshold is not None else None)

        q = self.qualifying_samples(name, skirt_threshold)
        if skirt_threshold is not None and not q:
            return CurveSolveResult(
                None, "no tabulated (robust, taper) combination meets the "
                "PSF-skirt threshold of %.2g" % skirt_threshold,
                skirt_met=False)
        scale = REF_FREQ_GHZ / freq_ghz
        if not q:
            return CurveSolveResult(None, "no usable curve data for this subarray")
        return CurveSolveResult(
            None, "no tabulated solution within +/-%.0f%% of %.4g arcsec; "
            "nearest qualifying samples span %.4g - %.4g arcsec "
            "at this frequency"
            % (100 * beam_margin, resolution,
               q[0].resolution * scale, q[-1].resolution * scale),
            skirt_met=False if skirt_threshold is not None else None)

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
            # anchors' own caveats must survive interpolation (measured
            # lattice samples carry none; external curves, e.g. stroh.py's
            # placeholder-taper warning, do)
            anchor_notes = []
            for a in anchors:
                n = getattr(a, "note", "")
                if n and n not in anchor_notes:
                    anchor_notes.append(n)
            if anchor_notes:
                note += "; " + "; ".join(anchor_notes)
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

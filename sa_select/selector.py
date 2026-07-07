"""
The selection engine (Phase B of PLAN.md): given an ObservingRequest, evaluate
every tabulated subarray against it and return a ranked list of Candidates.

For each subarray the steps are (PLAN.md section 8):
  1. scale its 30 GHz reference curve to the requested frequency;
  2. feasibility: can it make the requested beam (within beam_margin), and is
     its LAS large enough?  Imaging projects additionally require a PSF-skirt
     <= request.skirt_threshold (beam sculpting, memos 65/121);
  3. read off eta and the (weighting, robust, taper) that achieve the beam;
  4. if a sensitivity goal was given, get the integration time from the
     sensitivity calculator (natural rms x our eta) and antenna-hours;
  5. rank the feasible candidates with the requested heuristic.

Infeasible subarrays are kept, with human-readable reasons, so the caller can
see *why* something was excluded.
"""

from typing import List, Optional, Union

from .schema import ObservingRequest, Candidate
from .curves import CurveLibrary
from . import heuristics


class SelectionResult:
    """Ranked candidates, feasible first.  Iterable; also offers .table()."""

    def __init__(self, request: ObservingRequest, candidates: List[Candidate]):
        self.request = request
        self.candidates = candidates

    @property
    def feasible(self) -> List[Candidate]:
        return [c for c in self.candidates if c.feasible]

    @property
    def infeasible(self) -> List[Candidate]:
        return [c for c in self.candidates if not c.feasible]

    @property
    def best(self) -> Optional[Candidate]:
        f = self.feasible
        return f[0] if f else None

    def __iter__(self):
        return iter(self.candidates)

    def __len__(self):
        return len(self.candidates)

    def __getitem__(self, i):
        return self.candidates[i]

    def to_rows(self) -> List[dict]:
        """Plain dicts, one per candidate (drop straight into a DataFrame)."""
        rows = []
        for c in self.candidates:
            rows.append(dict(
                subarray=c.subarray.name, n_ant=c.subarray.n_ant,
                feasible=c.feasible, reasons="; ".join(c.reasons),
                warnings="; ".join(c.warnings),
                resolution_arcsec=c.resolution, eta=c.eta,
                weighting=c.weighting, robust=c.robust,
                taper_arcsec=c.taper, skirt=c.skirt, las_arcsec=c.las,
                sensitivity_jy=c.sensitivity_jy,
                integration_time_hr=c.integration_time_hr,
                antenna_hours=c.antenna_hours, source=c.source,
            ))
        return rows

    def table(self) -> str:
        """A readable summary table (feasible part) plus exclusion notes."""
        def fmt(x, spec="%.3g"):
            return "-" if x is None else spec % x

        hdr = ("%-12s %5s %9s %5s %8s %6s %8s %6s %9s %8s %8s"
               % ("subarray", "N_ant", "beam(\")", "eta", "weight",
                  "robust", "taper(\")", "skirt", "LAS(\")", "t_int(h)", "antHrs"))
        lines = [hdr, "-" * len(hdr)]
        for c in self.feasible:
            lines.append("%-12s %5d %9s %5s %8s %6s %8s %6s %9s %8s %8s"
                         % (c.subarray.name, c.subarray.n_ant,
                            fmt(c.resolution, "%.4g"), fmt(c.eta),
                            c.weighting or "-", fmt(c.robust, "%.2f"),
                            fmt(c.taper, "%.3g"), fmt(c.skirt, "%.2f"),
                            fmt(c.las, "%.4g"),
                            fmt(c.integration_time_hr),
                            fmt(c.antenna_hours)))
        if not self.feasible:
            lines.append("(no feasible subarray)")
        for c in self.feasible:
            for w in c.warnings:
                lines.append("note      %-12s : %s" % (c.subarray.name, w))
        for c in self.infeasible:
            lines.append("excluded  %-12s : %s"
                         % (c.subarray.name, "; ".join(c.reasons)))
        return "\n".join(lines)


def select_subarrays(request: ObservingRequest,
                     library: Optional[CurveLibrary] = None,
                     heuristic: Union[str, heuristics.Heuristic, None] = None,
                     ) -> SelectionResult:
    """Evaluate all subarrays against `request`; see module docstring.

    `heuristic` overrides request.optimize; it may be a built-in name
    (heuristics.HEURISTICS) or any callable (candidates, request) -> ranked
    candidates.
    """
    library = library or CurveLibrary()
    rank = heuristics.resolve(heuristic, default=request.optimize)
    skirt_thr = request.skirt_threshold if request.imaging else None

    # the sensitivity calculator is only needed when a goal was given
    sens = None
    sens_err = None
    if request.sensitivity is not None:
        try:
            from . import sensitivity as sens
        except Exception as e:            # keep selection usable without it
            sens_err = "sensitivity module unavailable (%s)" % e

    candidates = []
    for info in library.subarrays.values():
        c = Candidate(subarray=info)
        c.las = info.las_arcsec(request.frequency)

        # -- LAS feasibility -------------------------------------------- #
        if request.las is not None and c.las < request.las:
            c.reasons.append("LAS %.4g\" < requested %.4g\""
                             % (c.las, request.las))

        # -- beam feasibility + imaging parameters ----------------------- #
        sample, msg = library.solve(info.name, request.resolution,
                                    request.frequency,
                                    beam_margin=request.beam_margin,
                                    skirt_threshold=skirt_thr,
                                    relax=request.skirt_relax)
        if sample is None:
            c.reasons.append(msg)
        else:
            if msg != "ok":
                c.warnings.append(msg)          # e.g. relaxed skirt criterion
            if sample.note:
                c.warnings.append(sample.note)  # e.g. interpolated parameters
            s = library.scale_sample(sample, request.frequency)
            c.resolution, c.eta, c.skirt = s.resolution, s.eta, s.skirt
            c.weighting, c.robust, c.taper = s.weighting, s.robust, s.taper
            c.source = s.source

        c.feasible = not c.reasons

        # -- cost: integration time & antenna-hours ---------------------- #
        if c.feasible and request.sensitivity is not None:
            if sens_err:
                c.reasons.append(sens_err)
            else:
                try:
                    goal_jy = request.sensitivity
                    if request.sensitivity_unit == "K":
                        goal_jy = sens.tb_to_jy(request.sensitivity,
                                                c.resolution,
                                                request.frequency)
                    c.sensitivity_jy = goal_jy
                    key = info.calc_name or info.name
                    c.integration_time_hr = sens.integration_time(
                        key, request.frequency, c.eta, goal_jy,
                        delta_v=request.delta_v)
                    c.antenna_hours = c.integration_time_hr * info.n_ant
                except Exception as e:
                    c.reasons.append("sensitivity calculation failed: %s" % e)

        candidates.append(c)

    ranked = rank([c for c in candidates if c.feasible], request)
    ranked += [c for c in candidates if not c.feasible]
    return SelectionResult(request, ranked)

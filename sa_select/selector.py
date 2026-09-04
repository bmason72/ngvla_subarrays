"""
The selection engine (Phase B of PLAN.md): given an ObservingRequest, evaluate
every tabulated subarray against it and return a ranked list of Candidates.

For each subarray the steps are (PLAN.md section 8):
  1. scale its 30 GHz reference curve to the requested frequency;
  2. feasibility: can it make the requested beam (within beam_margin), and is
     its LAS large enough?  Imaging projects additionally require a PSF-skirt
     <= request.skirt_threshold (beam sculpting, memos 65/121);
  3. read off eta and the (weighting, robust, taper) that achieve the beam;
  4. resolve either the supplied sensitivity goal or the natural MAIN
     one-minute fiducial, then calculate time and antenna-hours;
  5. for imaging, rank skirt-met candidates ahead of relaxed candidates, and
     rank within each group with the requested cost heuristic.

Infeasible subarrays are kept, with human-readable reasons, so the caller can
see *why* something was excluded.
"""

from typing import List, Optional, Union

from .schema import ObservingRequest, Candidate, SelectionWarning
from .curves import CurveLibrary
from .visibility import (CORRELATOR_DUMP_TIME_S, VISIBILITY_CHANNELS,
                         estimate_visibility_count, format_visibility_count)
from . import heuristics


class SelectionResult:
    """Ranked candidates, feasible first.  Iterable; also offers .table()."""

    def __init__(self, request: ObservingRequest, candidates: List[Candidate],
                 warnings: Optional[List[SelectionWarning]] = None,
                 ranking_available: bool = True):
        self.request = request
        self.candidates = candidates
        self.warnings = list(warnings or [])
        self.ranking_available = bool(ranking_available)

    @property
    def feasible(self) -> List[Candidate]:
        return [c for c in self.candidates if c.feasible]

    @property
    def infeasible(self) -> List[Candidate]:
        return [c for c in self.candidates if not c.feasible]

    @property
    def best(self) -> Optional[Candidate]:
        if not self.ranking_available:
            return None
        f = self.feasible
        return f[0] if f else None

    @property
    def any_subarray_meets_skirt(self) -> Optional[bool]:
        if not self.request.imaging:
            return None
        return any(c.feasible and c.skirt_met is True for c in self.candidates)

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
                skirt_required=c.skirt_required, skirt_met=c.skirt_met,
                skirt_relaxed=c.skirt_relaxed,
                resolution_arcsec=c.resolution, eta=c.eta,
                weighting=c.weighting, robust=c.robust,
                taper_arcsec=c.taper, skirt=c.skirt, las_arcsec=c.las,
                sensitivity_jy=c.sensitivity_jy,
                integration_time_hr=c.integration_time_hr,
                antenna_hours=c.antenna_hours,
                n_visibilities=c.n_visibilities,
                correlator_dump_time_s=CORRELATOR_DUMP_TIME_S,
                visibility_channels=VISIBILITY_CHANNELS,
                cost_status=c.cost_status,
                cost_error=c.cost_error, goal_origin=c.goal_origin,
                ranking_available=self.ranking_available,
                result_warning_codes=";".join(w.code for w in self.warnings),
                source=c.source,
            ))
        return rows

    def to_summary(self) -> dict:
        """Structured request-level status for API and batch consumers."""
        costed = [c for c in self.feasible if c.cost_status == "available"]
        origins = sorted({c.goal_origin for c in costed if c.goal_origin})
        fiducial_values = {
            c.sensitivity_jy for c in costed
            if c.goal_origin == "main_natural_1min_fiducial"
        }
        return dict(
            ranking_available=self.ranking_available,
            any_subarray_meets_skirt=self.any_subarray_meets_skirt,
            warnings=[w.to_dict() for w in self.warnings],
            best_subarray=None if self.best is None else self.best.subarray.name,
            goal_origins=origins,
            fiducial_goal_jy=(next(iter(fiducial_values))
                              if len(fiducial_values) == 1 else None),
            frequency_ghz=self.request.frequency,
            delta_v_m_per_s=self.request.delta_v,
            correlator_dump_time_s=CORRELATOR_DUMP_TIME_S,
            visibility_channels=VISIBILITY_CHANNELS,
        )

    def table(self) -> str:
        """A readable summary table (feasible part) plus exclusion notes."""
        def fmt(x, spec="%.3g"):
            return "-" if x is None else spec % x

        hdr = ("%-12s %5s %9s %5s %8s %6s %8s %6s %9s %8s %8s %12s"
               % ("subarray", "N_ant", "beam(\")", "eta", "weight",
                  "robust", "taper(\")", "skirt", "LAS(\")", "t_int(h)",
                  "antHrs", "visibilities"))
        lines = [hdr, "-" * len(hdr)]
        if not self.ranking_available and self.feasible:
            lines.append("(cost ranking unavailable; feasible rows are not recommendations)")
        for c in self.feasible:
            lines.append("%-12s %5d %9s %5s %8s %6s %8s %6s %9s %8s %8s %12s"
                         % (c.subarray.name, c.subarray.n_ant,
                            fmt(c.resolution, "%.4g"), fmt(c.eta),
                            c.weighting or "-", fmt(c.robust, "%.2f"),
                            fmt(c.taper, "%.3g"), fmt(c.skirt, "%.2f"),
                            fmt(c.las, "%.4g"),
                            fmt(c.integration_time_hr),
                            fmt(c.antenna_hours),
                            format_visibility_count(c.n_visibilities)))
        if not self.feasible:
            lines.append("(no feasible subarray)")
        for c in self.feasible:
            for w in c.warnings:
                lines.append("note      %-12s : %s" % (c.subarray.name, w))
        for w in self.warnings:
            lines.append("warning   %-12s : %s" % (w.code, w.message))
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

    result_warnings = [
        SelectionWarning("REQUEST_NORMALIZED", text)
        for text in request.normalization_warnings
    ]
    candidates = []
    for info in library.subarrays.values():
        c = Candidate(subarray=info)
        c.skirt_required = skirt_thr
        c.las = info.las_arcsec(request.frequency)

        # -- LAS feasibility -------------------------------------------- #
        if request.las is not None and c.las < request.las:
            c.reasons.append("LAS %.4g\" < requested %.4g\""
                             % (c.las, request.las))

        # -- beam feasibility + imaging parameters ----------------------- #
        solved = library.solve_detailed(
            info.name, request.resolution, request.frequency,
            beam_margin=request.beam_margin, skirt_threshold=skirt_thr,
            relax=request.skirt_relax)
        sample, msg = solved.sample, solved.message
        if sample is None:
            c.reasons.append(msg)
        else:
            c.skirt_met = solved.skirt_met
            c.skirt_relaxed = solved.relaxed
            if msg != "ok":
                c.warnings.append(msg)          # e.g. relaxed skirt criterion
            if sample.note:
                c.warnings.append(sample.note)  # e.g. interpolated parameters
            s = library.scale_sample(sample, request.frequency)
            c.resolution, c.eta, c.skirt = s.resolution, s.eta, s.skirt
            c.weighting, c.robust, c.taper = s.weighting, s.robust, s.taper
            c.source = s.source

        c.feasible = not c.reasons
        if not c.feasible:
            c.cost_status = "unavailable"
        candidates.append(c)

    # -- cost: explicit science goal or the one-minute MAIN fiducial ------- #
    curve_feasible = [c for c in candidates if c.feasible]
    ranking_available = True
    sens = None
    sens_err = None
    if curve_feasible:
        try:
            from . import sensitivity as sens
        except Exception as e:            # keep beam/LAS-only selection usable
            sens_err = "sensitivity module unavailable (%s)" % e

    fiducial_goal_jy = None
    if curve_feasible and request.sensitivity is None and sens_err is None:
        try:
            fiducial_goal_jy = sens.natural_rms(
                "main", request.frequency, t_obs_hr=1.0 / 60.0,
                delta_v=request.delta_v)
        except Exception as e:
            sens_err = "cannot calculate one-minute MAIN fiducial (%s)" % e

    if curve_feasible and sens_err is not None:
        if request.sensitivity is not None:
            for c in curve_feasible:
                c.cost_status = "failed"
                c.cost_error = sens_err
                c.reasons.append(sens_err)
                c.feasible = False
        else:
            ranking_available = False
            for c in curve_feasible:
                c.cost_status = "unavailable"
                c.cost_error = sens_err
            result_warnings.append(SelectionWarning(
                "COST_UNAVAILABLE",
                "%s; beam/LAS feasibility is retained but no recommendation "
                "is ranked" % sens_err))
    elif curve_feasible:
        implicit_failures = []
        for c in curve_feasible:
            try:
                goal_jy = request.sensitivity
                goal_origin = "user"
                if goal_jy is None:
                    goal_jy = fiducial_goal_jy
                    goal_origin = "main_natural_1min_fiducial"
                elif request.sensitivity_unit == "K":
                    goal_jy = sens.tb_to_jy(request.sensitivity,
                                            c.resolution,
                                            request.frequency)
                c.sensitivity_jy = goal_jy
                c.goal_origin = goal_origin
                key = c.subarray.calc_name or c.subarray.name
                # The backing rms already contains N(N-1).  n_ant_actual only
                # replaces a stale revision count (e.g. Rev C) or completes a
                # donor-to-actual rescale for names missing from the backing
                # calculator.  It is unity for matching Rev F/Rev D entries.
                c.integration_time_hr = sens.integration_time(
                    key, request.frequency, c.eta, goal_jy,
                    delta_v=request.delta_v,
                    n_ant_actual=c.subarray.n_ant)
                c.antenna_hours = c.integration_time_hr * c.subarray.n_ant
                c.n_visibilities = estimate_visibility_count(
                    c.subarray.n_ant, c.integration_time_hr)
                c.cost_status = "available"
            except Exception as e:
                message = "sensitivity calculation failed: %s" % e
                c.cost_status = "failed"
                c.cost_error = message
                if request.sensitivity is not None:
                    c.reasons.append(message)
                    c.feasible = False
                else:
                    implicit_failures.append(c)

        if implicit_failures:
            ranking_available = False
            names = ", ".join(c.subarray.name for c in implicit_failures)
            for c in candidates:
                if c.feasible:
                    c.integration_time_hr = None
                    c.antenna_hours = None
                    c.n_visibilities = None
                    if c.cost_status == "available":
                        c.cost_status = "unavailable"
                        c.cost_error = "implicit cost ranking disabled because another candidate failed"
            result_warnings.append(SelectionWarning(
                "COST_UNAVAILABLE",
                "implicit fiducial cost failed for %s; beam/LAS feasibility is "
                "retained but no recommendation is ranked" % names,
                {"subarrays": [c.subarray.name for c in implicit_failures]}))

    feasible = [c for c in candidates if c.feasible]
    if request.imaging and not any(c.skirt_met is True for c in feasible):
        result_warnings.append(SelectionWarning(
            "NO_SUBARRAY_MEETS_SKIRT",
            "no feasible subarray meets skirt <= %.3g; relaxed results are "
            "shown where available" % request.skirt_threshold,
            {"skirt_threshold": request.skirt_threshold}))

    # Strict-first is an engine policy.  A heuristic ranks within each group;
    # strict_first=False is the deliberate mixed-pool escape hatch.
    if request.imaging and request.strict_first:
        strict = [c for c in feasible if c.skirt_met is True]
        relaxed = [c for c in feasible if c.skirt_met is not True]
        if ranking_available:
            ranked = rank(strict, request) + rank(relaxed, request)
        else:
            ranked = strict + relaxed       # presentation order only; best=None
    elif ranking_available:
        ranked = rank(feasible, request)
    else:
        ranked = feasible                   # metadata presentation order only
    ranked += [c for c in candidates if not c.feasible]
    return SelectionResult(request, ranked, warnings=result_warnings,
                           ranking_available=ranking_available)

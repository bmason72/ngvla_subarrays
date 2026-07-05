"""
Pluggable ranking heuristics.

A heuristic is any callable  (feasible_candidates, request) -> ranked list
of the same candidates, best first.  The engine looks built-in names up in
HEURISTICS; passing your own callable to select_subarrays() works the same
way, so trying a different selection strategy never requires touching the
engine.

When no sensitivity goal was given, integration_time_hr / antenna_hours are
None, so the built-ins fall back to *relative* costs, which follow from the
radiometer equation (rms ∝ eta / sqrt(N(N-1) t)) at fixed target sensitivity:

    time to reach a fixed rms       :  t     ∝  eta^2 / (N (N-1))
    antenna-hours to reach that rms :  N t   ∝  eta^2 / (N-1)

(cf. the (214/N * eta)^2 convention in CLAUDE.md, which approximates
N(N-1) by N^2).
"""

from typing import Callable, Dict, List, Union

from .schema import Candidate, ObservingRequest

Heuristic = Callable[[List[Candidate], ObservingRequest], List[Candidate]]


def relative_time(c: Candidate) -> float:
    """Relative integration time to a fixed point-source rms (arbitrary units)."""
    n = c.subarray.n_ant
    return c.eta ** 2 / (n * (n - 1))


def relative_antenna_hours(c: Candidate) -> float:
    """Relative antenna-hours to a fixed point-source rms (arbitrary units)."""
    return c.subarray.n_ant * relative_time(c)


def by_integration_time(cands: List[Candidate], request: ObservingRequest
                        ) -> List[Candidate]:
    """Least telescope wall-clock time first."""
    def key(c):
        t = c.integration_time_hr if c.integration_time_hr is not None \
            else relative_time(c)
        return (t, c.subarray.n_ant)          # tie-break: fewer antennas
    return sorted(cands, key=key)


def by_antenna_hours(cands: List[Candidate], request: ObservingRequest
                     ) -> List[Candidate]:
    """Least total antenna-hours (the EOP resource-cost view) first."""
    def key(c):
        ah = c.antenna_hours if c.antenna_hours is not None \
            else relative_antenna_hours(c)
        return (ah, c.subarray.n_ant)
    return sorted(cands, key=key)


HEURISTICS: Dict[str, Heuristic] = {
    "integration_time": by_integration_time,
    "antenna_hours": by_antenna_hours,
}


def resolve(h: Union[str, Heuristic, None], default: str = "antenna_hours"
            ) -> Heuristic:
    """Turn a heuristic name / callable / None into a callable."""
    if h is None:
        h = default
    if callable(h):
        return h
    try:
        return HEURISTICS[h]
    except KeyError:
        raise ValueError("unknown heuristic %r; built-ins: %s"
                         % (h, ", ".join(sorted(HEURISTICS))))

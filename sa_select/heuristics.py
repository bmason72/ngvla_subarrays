"""
Pluggable ranking heuristics.

A heuristic is any callable  (feasible_candidates, request) -> ranked list
of the same candidates, best first.  The engine looks built-in names up in
HEURISTICS; passing your own callable to select_subarrays() works the same
way, so trying a different selection strategy never requires touching the
engine.  For imaging requests the engine normally calls the heuristic once
for skirt-met candidates and once for relaxed candidates, then concatenates
those groups.  ``ObservingRequest.strict_first=False`` opts into one mixed
pool.

The selector always resolves an absolute goal before invoking a built-in: a
user goal, or the natural untapered MAIN sensitivity in one minute.  Built-ins
therefore refuse candidates without absolute costs.  The relative helper
functions below remain only for transition/audit comparisons.
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
        if c.integration_time_hr is None:
            raise ValueError("integration-time ranking requested without available costs")
        return (c.integration_time_hr, c.subarray.n_ant)  # tie-break: fewer antennas
    return sorted(cands, key=key)


def by_antenna_hours(cands: List[Candidate], request: ObservingRequest
                     ) -> List[Candidate]:
    """Least total antenna-hours (the EOP resource-cost view) first."""
    def key(c):
        if c.antenna_hours is None:
            raise ValueError("antenna-hour ranking requested without available costs")
        return (c.antenna_hours, c.subarray.n_ant)
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

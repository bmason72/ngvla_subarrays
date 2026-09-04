"""
sa_select -- NGVLA subarray selection.

Given a desired resolution, frequency, sensitivity, and largest angular scale,
return a ranked list of Rev F subarrays (with tclean weighting parameters)
that achieve the requested beam, minimizing integration time or antenna-hours.

Typical use:

    from sa_select import ObservingRequest, select_subarrays

    req = ObservingRequest(resolution=0.01, frequency=30.0,   # 10 mas at 30 GHz
                           sensitivity=1e-6,                  # 1 uJy/beam
                           las=0.1, imaging=True)
    result = select_subarrays(req)
    print(result.table())
    best = result.best          # a Candidate; best.tclean_pars() -> dict

See PLAN.md and the memos (55/65/67/72/76/121) for the method.  Curve data in
sa_select/data/ is currently BOOTSTRAP data derived from memo 121 (pre-Rev-F
simulations) -- a stand-in until the Rev F curves are generated.
"""

from .schema import (ObservingRequest, SubarrayInfo, CurveSample, Candidate,
                     SelectionWarning)
from .curves import CurveLibrary
from .selector import select_subarrays, SelectionResult
from .heuristics import HEURISTICS
from .visibility import (CORRELATOR_DUMP_TIME_S, VISIBILITY_CHANNELS,
                         estimate_visibility_count)

__all__ = ["ObservingRequest", "SubarrayInfo", "CurveSample", "Candidate",
           "SelectionWarning", "CurveLibrary", "select_subarrays",
           "SelectionResult", "HEURISTICS", "CORRELATOR_DUMP_TIME_S",
           "VISIBILITY_CHANNELS", "estimate_visibility_count"]

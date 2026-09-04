"""Raw visibility-count estimates for selected subarrays.

The current release assumes one channel, excludes autocorrelations, and uses
a fixed 5 s correlator dump time. Keep the observing-rule assumptions here so
that a future frequency/FOV/baseline-dependent dump time has one replacement
point.
"""

import math
from numbers import Integral


CORRELATOR_DUMP_TIME_S = 5.0
VISIBILITY_CHANNELS = 1


def estimate_visibility_count(n_ant: int, integration_time_hr: float,
                              dump_time_s: float = CORRELATOR_DUMP_TIME_S,
                              n_channels: int = VISIBILITY_CHANNELS) -> float:
    """Return the number of baseline-time-channel visibility samples.

    This implements ``N_ant * (N_ant - 1) / 2 * t_obs / t_dump`` for each
    channel. The result is a float because the sensitivity-derived observing
    time is continuous rather than rounded to a whole correlator dump.
    """
    if not isinstance(n_ant, Integral) or isinstance(n_ant, bool) or n_ant < 2:
        raise ValueError("n_ant must be an integer >= 2")
    if not math.isfinite(integration_time_hr) or integration_time_hr <= 0:
        raise ValueError("integration_time_hr must be finite and positive")
    if not math.isfinite(dump_time_s) or dump_time_s <= 0:
        raise ValueError("dump_time_s must be finite and positive")
    if (not isinstance(n_channels, Integral) or isinstance(n_channels, bool)
            or n_channels < 1):
        raise ValueError("n_channels must be a positive integer")
    n_baselines = n_ant * (n_ant - 1) / 2
    n_dumps = integration_time_hr * 3600.0 / dump_time_s
    return n_baselines * n_dumps * n_channels


def format_visibility_count(n_visibilities: float) -> str:
    """Format a visibility count with an SI visibility unit."""
    if n_visibilities is None:
        return "-"
    for scale, unit in ((1e12, "TVis"), (1e9, "GVis"),
                        (1e6, "MVis"), (1e3, "kVis")):
        if n_visibilities >= scale:
            return "%.3g %s" % (n_visibilities / scale, unit)
    return "%.3g Vis" % n_visibilities

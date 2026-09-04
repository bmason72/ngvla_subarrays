"""CASA-free helpers shared by the sweep, refiner, and adaptive sampler."""

import math
from collections import deque


SKIRT_MAX = 0.10
GAP_RATIO = 1.35
RIM_DEX = 0.01


def point_key(weighting, robust, taper_mas):
    """Canonical key at the precision stored by the sweep CSV."""
    robust, taper_mas = float(robust), float(taper_mas)
    if round(robust, 2) == 0.0:
        robust = 0.0
    if round(taper_mas, 3) == 0.0:
        taper_mas = 0.0
    return "%s_%.2f_%.3f" % (weighting, robust, taper_mas)


def progressive_log_midpoints(lo, hi, k, exclude=()):
    """Return deterministic breadth-first log-midpoints inside ``(lo, hi)``."""
    if not (lo > 0 and hi > lo):
        return []
    xlo, xhi = math.log10(lo), math.log10(hi)
    seen = {round(float(t), 3) for t in exclude}
    out, queue, guard = [], deque([(xlo, xhi)]), 0
    while queue and len(out) < k and guard < 4000:
        guard += 1
        alo, ahi = queue.popleft()
        mid = 0.5 * (alo + ahi)
        taper = round(10 ** mid, 3)
        if taper not in seen and lo < taper < hi:
            seen.add(taper)
            out.append(taper)
        if ahi - alo > 1e-6:
            queue.append((alo, mid))
            queue.append((mid, ahi))
    return out

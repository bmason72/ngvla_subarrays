#!/usr/bin/env python3
"""Build packaged exact physical baseline distributions for Rev C/D/F.

Run from the repository root with the normal Python/CASA environment:
    python curvegen/build_baseline_data.py

Membership is obtained in a fresh subprocess per revision from the campaign's
``config`` and ``build_configs`` helpers.  Thus CoreInner/CoreOuter use the
same authoritative membership implementation as generated simulation configs.
The output is deliberately runtime-independent of curvegen and the config
checkout.

NO uv-range cut is applied here, by design.  ``config.MIN_UVRANGE_M`` (the
spurious ~3-antenna-cluster short-baseline cut used for curve generation /
imaging, where those cluster baselines really do distort the PSF and eta)
is NOT ported into this packaged pair-length geometry.  For the
``efficient``/``performance`` ranking metrics (`sa_select/baselines.py`),
every distinct antenna pair is packaged for every subarray: Bmin/Bmax alone
decide which pairs count in a requested science-baseline interval, and a
pair outside that interval is simply not credited -- it is not "wasted."
This was tried the other way (``MIN_UVRANGE_M`` applied here) on 11 Sep 2026
and reversed the same day: dropping those pairs from ``lengths_m`` while
still charging them in the ``n_ant*(n_ant-1)/2`` denominator permanently
penalized LONG-containing subarrays with no way to ever earn credit for
those pairs, even for a request with a small enough Bmin that should
naturally include them. See ``docs/plans/baseline-window-plan.md`` (decision
5 / W3) and ``docs/worklog/baseline-ranking.md`` (11 Sep 2026 entries) for
the full history. Do not reintroduce the cut here a third time.
"""

import csv
import gzip
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sa_select" / "data" / "baseline_geometry.json.gz"
REVISIONS = ("revC", "revD", "revF")

_EXTRACT = r'''
import json
from build_configs import (read_antenna_lines, inner_core_lines,
                           outer_core_lines, spiral_plus_core_lines)
from config import SUBARRAYS
def lines(component):
    if component == "core-inner": return inner_core_lines()
    if component == "core-outer": return outer_core_lines()
    if component.startswith("core-spiral+"): return spiral_plus_core_lines(component)
    return read_antenna_lines(component)
print(json.dumps({
    "subarrays": {name: [line.rstrip() for part in parts for line in lines(part)]
                 for name, parts in SUBARRAYS.items()},
}, sort_keys=True))
'''


def _subarray_lines(rev):
    """Return ``{subarray: antenna lines}`` for *rev*."""
    env = dict(os.environ, NGVLA_REV=rev, NGVLA_SIM_MODE="track", NGVLA_BAND="")
    result = subprocess.run([sys.executable, "-c", _EXTRACT], cwd=ROOT / "curvegen",
                            env=env, text=True, stdout=subprocess.PIPE, check=True)
    return json.loads(result.stdout)["subarrays"]


def _metadata_counts(rev):
    registry = ROOT / "sa_select" / "data" / "config_registry.csv"
    with registry.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    filename = next(row["subarrays_csv"] for row in rows
                    if row["rev"] == rev and row["sim_mode"] == "track"
                    and not row.get("band", ""))
    with (ROOT / "sa_select" / "data" / filename).open(newline="") as handle:
        return {row["name"]: int(row["n_ant"]) for row in csv.DictReader(handle)}


def _entry(rev, name, lines, expected_n):
    stations = [line.split()[-1] for line in lines]
    if len(stations) != len(set(stations)):
        raise ValueError("%s/%s contains duplicate station names" % (rev, name))
    if len(lines) != expected_n:
        raise ValueError("%s/%s has %d antennas, metadata says %d" %
                         (rev, name, len(lines), expected_n))
    xyz = [tuple(float(value) for value in line.split()[:3]) for line in lines]
    lengths = sorted(math.sqrt(sum((left[i] - right[i]) ** 2 for i in range(3)))
                     for index, left in enumerate(xyz) for right in xyz[index + 1:])
    expected_pairs = len(xyz) * (len(xyz) - 1) // 2
    if len(lengths) != expected_pairs:
        raise ValueError("%s/%s pair count is invalid" % (rev, name))
    source_digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    return {"n_ant": len(xyz), "n_pairs": len(lengths), "lengths_m": lengths,
            "provenance": {"version": 2, "convention": "physical-3d-unprojected-pairs",
                           "membership_source": "curvegen.build_configs",
                           "membership_sha256": source_digest,
                           "revision": rev, "subarray": name,
                           "uvrange_cut": None,
                           "uvrange_cut_note": ("no uv-range cut applied by design; "
                               "see curvegen/build_baseline_data.py module docstring "
                               "(bmason, 11 Sep 2026)")}}


def main():
    revisions = {}
    for rev in REVISIONS:
        lines = _subarray_lines(rev)
        counts = _metadata_counts(rev)
        absent = set(counts) - set(lines)
        if absent:
            raise ValueError("%s metadata names missing from config: %s" % (rev, sorted(absent)))
        revisions[rev] = {name: _entry(rev, name, sub_lines, counts[name])
                          for name, sub_lines in sorted(lines.items()) if name in counts}
    payload = {"format_version": 2, "revisions": revisions}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    # An explicit mtime and no embedded filename make repeated builds byte-stable.
    with OUT.open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as handle:
        handle.write(encoded)
    print("wrote %s (%d bytes)" % (OUT, OUT.stat().st_size))


if __name__ == "__main__":
    main()

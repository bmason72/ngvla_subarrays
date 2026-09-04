"""Compare the retired relative-cost order with the absolute fiducial order.

Run from a checkout with::

    python -m sa_select.audit_ranking RANKING_TRANSITION_AUDIT.json

The output is review evidence, not runtime input.  Differences are not
automatically failures: exact natural-rms anchors include effects that the old
equal-SEFD relative formula omitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from .curves import CurveLibrary, DATA_DIR, load_registry
from .heuristics import relative_antenna_hours, relative_time
from .schema import ObservingRequest
from .selector import select_subarrays


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_audit(grid_size=80):
    campaigns = []
    for (rev, sim_mode), (subarrays_csv, samples_csv) in sorted(load_registry().items()):
        sample_path = Path(DATA_DIR) / samples_csv
        if not sample_path.exists() or sample_path.stat().st_size == 0:
            campaigns.append({"rev": rev, "sim_mode": sim_mode, "status": "no data"})
            continue
        library = CurveLibrary.for_config(rev, sim_mode)
        resolutions = [sample.resolution for samples in library.samples.values()
                       for sample in samples]
        if not resolutions:
            campaigns.append({"rev": rev, "sim_mode": sim_mode, "status": "no samples"})
            continue
        grid = np.geomspace(min(resolutions), max(resolutions), grid_size)
        differences = []
        cases = 0
        for optimize, relative_key in [
                ("antenna_hours", relative_antenna_hours),
                ("integration_time", relative_time)]:
            for resolution in grid:
                request = ObservingRequest(
                    resolution=float(resolution), frequency=30.0,
                    imaging=False, optimize=optimize)
                result = select_subarrays(request, library=library)
                if not result.ranking_available or not result.feasible:
                    continue
                cases += 1
                new_order = [c.subarray.name for c in result.feasible]
                old_order = [c.subarray.name for c in sorted(
                    result.feasible,
                    key=lambda c: (relative_key(c), c.subarray.n_ant))]
                if new_order != old_order:
                    differences.append({
                        "resolution_arcsec_30ghz": float(resolution),
                        "optimize": optimize,
                        "old_order": old_order,
                        "fiducial_order": new_order,
                    })
        campaigns.append({
            "rev": rev,
            "sim_mode": sim_mode,
            "status": "compared",
            "subarrays_sha256": _sha256(Path(DATA_DIR) / subarrays_csv),
            "samples_sha256": _sha256(sample_path),
            "cases_compared": cases,
            "ordering_differences": differences,
        })
    return {
        "schema": "ngvla.sa-select.ranking-transition-audit",
        "schema_version": 1,
        "frequency_ghz": 30.0,
        "beam_margin": 0.05,
        "imaging": False,
        "grid_size_per_metric": grid_size,
        "note": (
            "Old order uses eta^2/[N(N-1)] or eta^2/(N-1); fiducial order "
            "uses packaged exact natural-rms anchors and one-minute MAIN goal."
        ),
        "campaigns": campaigns,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--grid-size", type=int, default=80)
    args = parser.parse_args(argv)
    if args.grid_size < 2:
        parser.error("--grid-size must be >= 2")
    args.output.write_text(json.dumps(build_audit(args.grid_size), indent=2) + "\n")


if __name__ == "__main__":
    main()

"""Export Rev F ngECT sensitivity curves as scipy PPoly JSON.

The output is intentionally close to Michael Stroh's ``subarray_data.json``:
each subarray has legacy top-level ``b_min``, ``b_max``, ``N_ant`` and
``theta_nat_30_GHz`` fields, plus serialized cubic PPoly splines.  Two
conventions differ deliberately from Stroh's table and are recorded in
``_meta``:

* angular coordinates here are geometric-mean FWHM in mas.  Stroh's delivered
  table used the quadrature sum of beam axes, inflating near-circular beams by
  about sqrt(2);
* ``b_min`` and ``b_max`` here are physical 3-D Rev F baseline lengths from
  ``subarrays.csv``.  Stroh's values are projected uv baselines at mid-track.

The curve values come from the shared ``Envelope`` engine, not raw samples.
Point-source curves minimize eta.  Imaging curves use the strict skirt <= 0.10
engine choices where such a domain exists; for capped heterogeneous arrays
whose capped domain has no strict points, the exported imaging curve falls back
to the engine's relaxed best-achievable-skirt choices and marks that in the
curve's ``selection_policy`` field.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from scipy.interpolate import PchipInterpolator, PPoly

from .curves import CurveLibrary, DATA_DIR

GENERATOR = "sa_select/export_ngect.py"
DEFAULT_OUTPUT = os.path.join(DATA_DIR, "ngect_subarray_data.json")
GRID_DEX = 0.01
CONTIGUOUS_RATIO = 10 ** (2 * GRID_DEX)
IMAGING_SKIRT_MAX = 0.10
MAX_RELATIVE_SPLINE_ERROR = 0.009

CURVE_POINT_SOURCE = "point_source"
CURVE_IMAGING = "imaging_s0_0.10"

POLICY_POINT_SOURCE = "point_source_min_eta"
POLICY_STRICT = "strict_only"
POLICY_RELAXED_FALLBACK = "relaxed_best_achievable_no_strict_domain"


@dataclass
class ExportCurve:
    """Dense engine curve after export filtering and largest-run selection."""

    key: str
    raw_points: Sequence
    kept_points: Sequence
    dropped_spans_log10_theta_mas: List[List[float]]
    selection_policy: str
    log10_theta_mas: np.ndarray
    eta: np.ndarray


@dataclass
class SplineStats:
    """Export diagnostics useful for tests and final reporting."""

    max_relative_error: float
    curve_errors: Dict[Tuple[str, str], float]


def _meta() -> Dict[str, object]:
    return {
        "generator": GENERATOR,
        "data_provenance": "sa_select/data/revf_curves.csv (curvegen collect.py)",
        "rev": "revF",
        "sim_mode": "4h_track",
        "reference_freq_GHz": 30.0,
        "eta_definition": (
            "dirty-image rms at the operating point divided by the "
            "natural-untapered dirty rms, at the 30 GHz reference. "
            "Convention warning: theta here is geometric-mean FWHM in mas; "
            "mstroh/subarray_data.json thetas are quadrature-sum values, "
            "about sqrt(2) larger for near-circular beams (see "
            "docs/architecture/mstroh_comparison.md finding 1). Convention warning: b_min/b_max "
            "here are physical 3-D baseline lengths from the Rev F .cfg files; "
            "Stroh's are projected-uv baselines at mid-track."
        ),
        "beam_cap_units": "arcsec at 30 GHz",
        "spline_convention": "x = log10(theta_mas), y = eta, scipy PPoly [c, x]",
        "curve_selection_policy": (
            "point_source is the engine min-eta curve. imaging_s0_0.10 is "
            "strict skirt <= 0.10 where a strict capped-domain run exists; "
            "otherwise it is the engine relaxed best-achievable-skirt curve, "
            "marked selection_policy='relaxed_best_achievable_no_strict_domain'."
        ),
        "knot_policy": (
            "seed knots are every 5th kept point plus endpoints; additional "
            "knots are inserted adaptively until dense-grid relative error is "
            "below %.3g" % MAX_RELATIVE_SPLINE_ERROR
        ),
    }


def _log10_theta_mas(point) -> float:
    if point.res <= 0:
        raise ValueError("curve point resolution must be positive")
    return math.log10(point.res * 1e3)


def _sort_points(points: Iterable) -> List:
    return sorted(points, key=lambda p: p.res)


def _strict_imaging_point(point) -> bool:
    return not bool(getattr(point, "relaxed", False)) and not bool(
        getattr(point, "traded", False)
    )


def _contiguous_runs(points: Sequence) -> List[Tuple[int, int]]:
    """Return half-open runs whose adjacent resolution ratio is contiguous."""

    if not points:
        return []
    runs: List[Tuple[int, int]] = []
    start = 0
    for idx, (left, right) in enumerate(zip(points, points[1:]), 1):
        if right.res / left.res > CONTIGUOUS_RATIO:
            runs.append((start, idx))
            start = idx
    runs.append((start, len(points)))
    return runs


def _largest_run(points: Sequence) -> Tuple[List, List]:
    """Keep the largest contiguous run, tie-breaking by wider log-domain."""

    runs = _contiguous_runs(points)
    if not runs:
        return [], []

    def rank(run: Tuple[int, int]) -> Tuple[int, float]:
        start, stop = run
        width = _log10_theta_mas(points[stop - 1]) - _log10_theta_mas(points[start])
        return stop - start, width

    best = max(runs, key=rank)
    kept = list(points[best[0] : best[1]])
    dropped: List = []
    for run in runs:
        if run != best:
            dropped.extend(points[run[0] : run[1]])
    return kept, dropped


def _dropped_spans(raw_points: Sequence, dropped_points: Sequence) -> List[List[float]]:
    dropped_ids = {id(point) for point in dropped_points}
    spans: List[List[float]] = []
    start = None
    last = None
    previous_dropped = None

    for point in raw_points:
        if id(point) not in dropped_ids:
            if start is not None and last is not None:
                spans.append([_log10_theta_mas(start), _log10_theta_mas(last)])
            start = last = previous_dropped = None
            continue

        if (
            start is not None
            and previous_dropped is not None
            and point.res / previous_dropped.res > CONTIGUOUS_RATIO
        ):
            spans.append([_log10_theta_mas(start), _log10_theta_mas(last)])
            start = point
        elif start is None:
            start = point
        last = point
        previous_dropped = point

    if start is not None and last is not None:
        spans.append([_log10_theta_mas(start), _log10_theta_mas(last)])
    return spans


def build_export_curve(lib: CurveLibrary, name: str, curve_key: str) -> ExportCurve:
    """Build the dense kept curve points used for one serialized spline."""

    cap = lib.subarrays[name].beam_cap_arcsec
    env = lib.envelope(name)
    if curve_key == CURVE_POINT_SOURCE:
        raw_points = _sort_points(env.curve(skirt_max=None, grid_dex=GRID_DEX, max_res=cap))
        candidate_points = raw_points
        initially_dropped: List = []
        policy = POLICY_POINT_SOURCE
    elif curve_key == CURVE_IMAGING:
        raw_points = _sort_points(
            env.curve(skirt_max=IMAGING_SKIRT_MAX, grid_dex=GRID_DEX, max_res=cap)
        )
        strict_points = [point for point in raw_points if _strict_imaging_point(point)]
        if strict_points:
            candidate_points = strict_points
            initially_dropped = [
                point for point in raw_points if not _strict_imaging_point(point)
            ]
            policy = POLICY_STRICT
        elif raw_points:
            candidate_points = raw_points
            initially_dropped = []
            policy = POLICY_RELAXED_FALLBACK
        else:
            raise ValueError("%s has no imaging engine curve points" % name)
    else:
        raise ValueError("unknown curve key %r" % (curve_key,))

    kept_points, out_of_run = _largest_run(candidate_points)
    if len(kept_points) < 2:
        raise ValueError("%s %s has fewer than two kept points" % (name, curve_key))

    dropped_points = list(initially_dropped) + out_of_run
    spans = _dropped_spans(raw_points, dropped_points)
    x = np.asarray([_log10_theta_mas(point) for point in kept_points], dtype=float)
    y = np.asarray([point.eta for point in kept_points], dtype=float)
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("%s %s has non-finite curve values" % (name, curve_key))
    if not np.all(np.diff(x) > 0):
        raise ValueError("%s %s log-resolution values are not increasing" % (name, curve_key))

    return ExportCurve(
        key=curve_key,
        raw_points=raw_points,
        kept_points=kept_points,
        dropped_spans_log10_theta_mas=spans,
        selection_policy=policy,
        log10_theta_mas=x,
        eta=y,
    )


def _initial_knot_indices(n_points: int) -> List[int]:
    return sorted(set([0, n_points - 1] + list(range(0, n_points, 5))))


def _fit_pchip_for_curve(curve: ExportCurve) -> Tuple[PchipInterpolator, float]:
    """Fit a PCHIP, refining the spec's 5-point seed until it is accurate."""

    x = curve.log10_theta_mas
    y = curve.eta
    knot_indices = _initial_knot_indices(len(x))

    while True:
        interp = PchipInterpolator(x[knot_indices], y[knot_indices])
        spline_y = interp(x)
        rel = np.abs(spline_y - y) / y
        max_rel = float(np.max(rel))
        if max_rel < MAX_RELATIVE_SPLINE_ERROR:
            return interp, max_rel

        worst_idx = int(np.argmax(rel))
        if worst_idx in knot_indices:
            missing = [idx for idx in range(len(x)) if idx not in knot_indices]
            if not missing:
                return interp, max_rel
            worst_idx = max(missing, key=lambda idx: rel[idx])
        knot_indices.append(worst_idx)
        knot_indices = sorted(set(knot_indices))


def serialize_curve(curve: ExportCurve) -> Tuple[Dict[str, object], float]:
    interp, max_rel = _fit_pchip_for_curve(curve)
    x = interp.x.tolist()
    c = interp.c.tolist()
    out = {
        "spline_type": "cubic",
        "spline_method": "pchip",
        "spline_params": [c, x],
        "domain_log10_theta_mas": [float(x[0]), float(x[-1])],
        "eta_min": float(np.min(curve.eta)),
        "eta_max": float(np.max(curve.eta)),
        "n_knots": int(len(x)),
        "dropped_spans_log10_theta_mas": curve.dropped_spans_log10_theta_mas,
        "selection_policy": curve.selection_policy,
    }
    return out, max_rel


def theta_nat_30_ghz_mas(lib: CurveLibrary, name: str) -> float:
    matches = [
        sample
        for sample in lib.samples.get(name, [])
        if sample.sample_status == "ok"
        and sample.weighting == "natural"
        and (sample.taper is None or sample.taper == 0.0)
    ]
    if len(matches) != 1:
        raise ValueError(
            "%s has %d natural untapered ok samples, expected 1"
            % (name, len(matches))
        )
    return float(matches[0].resolution * 1e3)


def build_subarray_entry(lib: CurveLibrary, name: str) -> Tuple[Dict[str, object], Dict[str, float]]:
    info = lib.subarrays[name]
    entry: Dict[str, object] = {
        "b_min": float(info.b_min_m),
        "b_max": float(info.b_max_m),
        "N_ant": int(info.n_ant),
        "theta_nat_30_GHz": theta_nat_30_ghz_mas(lib, name),
        "beam_convention": "geometric_mean_fwhm_mas",
    }
    if info.beam_cap_arcsec is not None:
        entry["beam_cap_arcsec_30ghz"] = float(info.beam_cap_arcsec)

    curves: Dict[str, object] = {}
    errors: Dict[str, float] = {}
    for curve_key in (CURVE_POINT_SOURCE, CURVE_IMAGING):
        curve = build_export_curve(lib, name, curve_key)
        curves[curve_key], errors[curve_key] = serialize_curve(curve)
    entry["curves"] = curves
    return entry, errors


def build_export(lib: Optional[CurveLibrary] = None) -> Tuple[Dict[str, object], SplineStats]:
    lib = lib or CurveLibrary()
    out: Dict[str, object] = {"_meta": _meta()}
    curve_errors: Dict[Tuple[str, str], float] = {}

    for name in lib.names():
        entry, errors = build_subarray_entry(lib, name)
        out[name] = entry
        for curve_key, error in errors.items():
            curve_errors[(name, curve_key)] = error

    max_error = max(curve_errors.values()) if curve_errors else 0.0
    return out, SplineStats(max_relative_error=max_error, curve_errors=curve_errors)


def write_json(data: Dict[str, object], output_path: str) -> None:
    directory = os.path.dirname(os.path.abspath(output_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(output_path, "w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name.replace("+", "_"))


def write_qa_plots(lib: CurveLibrary, data: Dict[str, object], qa_dir: str) -> None:
    """Write one PNG per subarray; matplotlib is imported only here."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(qa_dir, exist_ok=True)
    for name in lib.names():
        fig, axes = plt.subplots(2, 1, figsize=(7.0, 6.2), sharex=False)
        for ax, curve_key in zip(axes, (CURVE_POINT_SOURCE, CURVE_IMAGING)):
            curve = build_export_curve(lib, name, curve_key)
            curve_json = data[name]["curves"][curve_key]
            c, x = curve_json["spline_params"]
            spline = PPoly(np.asarray(c, dtype=float), np.asarray(x, dtype=float))
            domain = curve_json["domain_log10_theta_mas"]
            in_domain = (
                (curve.log10_theta_mas >= domain[0] - 1e-12)
                & (curve.log10_theta_mas <= domain[1] + 1e-12)
            )
            theta = 10 ** curve.log10_theta_mas
            ax.plot(theta, curve.eta, "-", linewidth=1.4, label="engine")
            ax.plot(
                theta[in_domain],
                spline(curve.log10_theta_mas[in_domain]),
                "--",
                linewidth=1.2,
                label="PCHIP",
            )
            knots = np.asarray(x, dtype=float)
            ax.plot(10 ** knots, spline(knots), "o", markersize=3.0, label="knots")
            ax.set_xscale("log")
            ax.set_ylabel("eta")
            ax.set_title("%s %s" % (name, curve_key))
            ax.grid(True, which="both", alpha=0.25)
        axes[-1].set_xlabel("theta (mas)")
        axes[0].legend(loc="best", fontsize="small")
        fig.tight_layout()
        fig.savefig(os.path.join(qa_dir, _safe_name(name) + ".png"), dpi=140)
        plt.close(fig)


def export(output_path: str = DEFAULT_OUTPUT, qa_dir: Optional[str] = None) -> SplineStats:
    lib = CurveLibrary()
    data, stats = build_export(lib)
    write_json(data, output_path)
    if qa_dir:
        write_qa_plots(lib, data, qa_dir)
    return stats


def main(argv: Optional[Sequence[str]] = None) -> SplineStats:
    parser = argparse.ArgumentParser(description="Export Rev F ngECT PPoly curves.")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help="output JSON path")
    parser.add_argument(
        "--qa-dir",
        default=None,
        help="optional directory for per-subarray QA PNG plots",
    )
    args = parser.parse_args(argv)
    return export(output_path=args.output, qa_dir=args.qa_dir)


if __name__ == "__main__":
    main()

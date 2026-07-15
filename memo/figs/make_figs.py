#!/usr/bin/env python3
"""
Generate the three memo figures (taperability, imaging, heatmap) for
memo/ngvla_sa_selection.tex.

Reuses the SAME engine the selector and the HTML report use, rather than
re-deriving envelopes:
  * sa_select.curves / sa_select.envelope for the underlying (robust, taper)
    lattice interpolation;
  * curvegen.make_report.build_curve() for the point-source and imaging
    curves themselves (identical trimming/max_res-cap policy to the HTML
    report at curvegen/revf-curves.html);
  * curvegen.make_report.build_heatmap() (+ curvegen.config.grid_rows) for
    the lattice-heatmap cell table plotted in figure 3.

Run with the venv matplotlib/numpy interpreter (NOT .venv, NOT system python):
    /work2/10240/bmason72/stampede3/casaenv/bin/casapy make_figs.py

Outputs (this directory): taperability.{pdf,png}, imaging.{pdf,png},
heatmap.{pdf,png}.
"""

import csv
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "curvegen"))

import make_report as mr          # noqa: E402  (curvegen/make_report.py)

# --------------------------------------------------------------------------- #
# style

plt.rcParams.update({
    "font.size": 9.5,
    "axes.linewidth": 0.8,
    "axes.grid": True,
    "grid.linewidth": 0.5,
    "grid.alpha": 0.35,
    "legend.fontsize": 7.6,
    "legend.frameon": False,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "savefig.bbox": "tight",
})

# Okabe-Ito colorblind-safe qualitative palette (8 colors, skip pale yellow
# for print contrast -> 7 usable + black), reused per-panel (compact family /
# long-baseline family are never shown together so reuse is unambiguous).
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7",
           "#E69F00", "#56B4E9", "#000000"]

# The 14 subarrays offered in the current memo scope (curvegen/make_report's
# own ACTIVE_ORDER for the default (revF, track) combo -- single source of
# truth, so this script never hardcodes a possibly-stale list).
OFFERED = list(mr.ACTIVE_ORDER)

# Split into two families for legend readability (7 + 7): the compact/core
# family vs. the long-baseline-containing family (memo-121 campaign
# additions).  Purely a plotting choice -- both panels share the same engine
# and data source.
LONG_FAMILY = [n for n in OFFERED if "long" in n or "core-outer" in n]
COMPACT_FAMILY = [n for n in OFFERED if n not in LONG_FAMILY]

assert set(COMPACT_FAMILY) | set(LONG_FAMILY) == set(OFFERED)
print("compact family:", COMPACT_FAMILY)
print("long family:", LONG_FAMILY)

LABELS = {n: n for n in OFFERED}   # canonical names are already memo-legible

FIG_W, FIG_H = 6.5, 4.2


def color_for(i):
    return PALETTE[i % len(PALETTE)]


# --------------------------------------------------------------------------- #
# data loading: reuse make_report's own sample-trimming + cap logic exactly
# (curvegen/make_report.py main(), lines ~272-319), so the curves plotted
# here are identical to what the HTML report shows.

def load_samples_and_caps():
    samples_by = {name: [] for name in OFFERED}
    with open(mr.CURVES_CSV) as f:
        for r in csv.DictReader(f):
            name = r["subarray"]
            if name not in samples_by:
                continue
            s = dict(
                res=float(r["resolution_arcsec_30ghz"]) * 1e3,   # mas
                eta=float(r["eta"]),
                skirt=float(r["skirt"]) if r["skirt"] else None,
                weighting=r["weighting"],
                robust=float(r["robust"]) if r["robust"] else None,
                taper=float(r["taper_arcsec_30ghz"]) * 1e3
                      if r["taper_arcsec_30ghz"] else 0.0,
                capped=((r.get("sample_status") or "ok").strip()
                        == "capped_anchor"),
            )
            # same eta>ETA_CAP display trim make_report applies before
            # building the Envelope (envelope.py itself does not censor;
            # this is the report's display convention, reused here for
            # figure-to-report consistency)
            if s["eta"] > mr.ETA_CAP:
                continue
            samples_by[name].append(s)

    caps = {name: None for name in OFFERED}
    with open(mr.SUBARRAYS_CSV) as f:
        for r in csv.DictReader(f):
            if r["name"] not in caps:
                continue
            cap = r.get("beam_cap_arcsec_30ghz", "").strip()
            caps[r["name"]] = float(cap) * 1e3 if cap else None   # mas
    return samples_by, caps


# --------------------------------------------------------------------------- #
# Figure 1: point-source (taperability) envelopes

def _interleaved_legend(fig, compact_handles, compact_labels,
                        long_handles, long_labels, bottom, extra_rows=0):
    """External, non-clipping legend below both panels: 7 columns, with the
    compact-family entry on top and the long-family entry below it in each
    column, so ncol=7 column-major fill reproduces the two-row family
    grouping without truncating any label (the earlier per-axes inset
    legend clipped long subarray names against the axes edge)."""
    handles, labels = [], []
    for ch, cl, lh, ll in zip(compact_handles, compact_labels,
                              long_handles, long_labels):
        handles += [ch, lh]
        labels += [cl, ll]
    fig.legend(handles, labels, loc="lower center", ncol=7, fontsize=7.0,
              bbox_to_anchor=(0.5, bottom), frameon=False,
              columnspacing=1.0, handlelength=1.6, handletextpad=0.5)


def make_taperability(samples_by, caps):
    fig, axes = plt.subplots(1, 2, figsize=(FIG_W, FIG_H + 0.55), sharey=True)
    fam_handles = {}
    for ax, family, title in ((axes[0], COMPACT_FAMILY, "compact / core family"),
                              (axes[1], LONG_FAMILY, "long-baseline family")):
        handles, labels = [], []
        for i, name in enumerate(family):
            curve = mr.build_curve(samples_by[name], max_res=caps[name])
            if not curve:
                handles.append(plt.Line2D([0], [0], color=color_for(i)))
                labels.append(LABELS[name])
                continue
            res = np.array([c["res"] for c in curve]) / 1e3     # mas -> arcsec
            eta = np.array([c["eta"] for c in curve])
            line, = ax.plot(res, eta, lw=1.4, color=color_for(i))
            handles.append(line)
            labels.append(LABELS[name])
        fam_handles[id(ax)] = (handles, labels)
        ax.set_xscale("log")
        ax.set_xlabel("resolution at 30 GHz (arcsec)")
        ax.text(0.03, 0.95, title, transform=ax.transAxes, fontsize=8,
                ha="left", va="top", style="italic", color="0.35")
    axes[0].set_ylabel(r"$\eta$ (sensitivity-loss factor)")
    axes[0].set_ylim(bottom=1.0)
    ch, cl = fam_handles[id(axes[0])]
    lh, ll = fam_handles[id(axes[1])]
    fig.subplots_adjust(left=0.09, right=0.985, top=0.97, bottom=0.26,
                        wspace=0.08)
    _interleaved_legend(fig, ch, cl, lh, ll, bottom=0.005)
    fig.savefig(os.path.join(HERE, "taperability.pdf"))
    fig.savefig(os.path.join(HERE, "taperability.png"), dpi=170)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Figure 2: imaging (sculptability) envelopes, strict/traded/relaxed

# NOTE on the strict/traded/relaxed split: the CURRENT default engine mode
# (envelope.Envelope.solve's mode="threshold", the mode actually used by
# curves.CurveLibrary.solve -- the real selector -- and by
# curvegen/make_report.build_curve, both called with no `mode` argument)
# only exposes two per-point states: `relaxed` (False = strict, meets
# skirt <= s0) and, when relaxed, `best_skirt`.  Choice.traded is a
# leftover field that is only ever set True under mode="legacy_trade", the
# RETIRED one-for-one eta-skirt trade that the memo text (Sec. "Curve
# engine: query time") describes as the current primary objective -- that
# prose is stale relative to the shipped default (see FIGURES.md).  To
# still give the reader the three-way visual split the figure caption
# promises, "traded" here is DERIVED (not an engine flag) as a relaxed
# point whose skirt still falls at or below the legacy trade's cap
# (0.10 < skirt <= 0.25); "relaxed" proper is a relaxed point whose best
# achievable skirt exceeds 0.25.  Both are honestly the engine's own
# `relaxed`/`skirt` output, just re-bucketed by skirt value.
TRADE_CAP = mr.SKIRT_DEFAULT + 0.15   # 0.25, matching the memo's stated cap

STATE_STYLE = {
    "strict":  dict(ls="-",  lw=1.5),
    "traded":  dict(ls="--", lw=1.3),
    "relaxed": dict(ls=":",  lw=1.3),
}


def _split_by_state(curve):
    """Split a make_report curve (list of point dicts) into contiguous runs
    per state (strict / traded / relaxed), each as (res_arr, eta_arr) in
    arcsec, so plot() draws a clean dashed/dotted/solid line per state
    without connecting across a state change with the wrong style."""
    runs = {}
    cur_state, cur_res, cur_eta = None, [], []

    def state_of(c):
        if not c["relaxed"]:
            return "strict"
        if c["skirt"] is not None and c["skirt"] <= TRADE_CAP:
            return "traded"
        return "relaxed"

    def flush():
        if cur_state is not None and cur_res:
            runs.setdefault(cur_state, []).append(
                (np.array(cur_res) / 1e3, np.array(cur_eta)))

    for c in curve:
        st = state_of(c)
        if st != cur_state:
            flush()
            cur_state, cur_res, cur_eta = st, [], []
        cur_res.append(c["res"])
        cur_eta.append(c["eta"])
    flush()
    return runs


def make_imaging(samples_by, caps):
    from matplotlib.lines import Line2D
    fig, axes = plt.subplots(1, 2, figsize=(FIG_W, FIG_H + 0.75), sharey=True)
    fam_handles = {}
    for ax, family, title in ((axes[0], COMPACT_FAMILY, "compact / core family"),
                              (axes[1], LONG_FAMILY, "long-baseline family")):
        handles, labels = [], []
        for i, name in enumerate(family):
            curve = mr.build_curve(samples_by[name], skirt_max=mr.SKIRT_DEFAULT,
                                   max_res=caps[name])
            color = color_for(i)
            handles.append(Line2D([0], [0], color=color))
            labels.append(LABELS[name])
            if not curve:
                continue
            runs = _split_by_state(curve)
            for state in ("strict", "traded", "relaxed"):
                for res, eta in runs.get(state, []):
                    ax.plot(res, eta, color=color, **STATE_STYLE[state])
        fam_handles[id(ax)] = (handles, labels)
        ax.set_xscale("log")
        ax.set_xlabel("resolution at 30 GHz (arcsec)")
        ax.text(0.03, 0.95, title, transform=ax.transAxes, fontsize=8,
                ha="left", va="top", style="italic", color="0.35")
    axes[0].set_ylabel(r"$\eta$ (sensitivity-loss factor)")
    axes[0].set_ylim(bottom=1.0)

    # state-key legend (line style only; colors carry subarray identity,
    # see the interleaved subarray-name legend below it)
    state_handles = [Line2D([0], [0], color="0.25", **STATE_STYLE[s])
                     for s in ("strict", "traded", "relaxed")]
    state_names = ["strict (skirt $\\leq$ 0.10)",
                   "traded (0.10 $<$ skirt $\\leq$ 0.25, derived)",
                   "relaxed (best achievable skirt $>$ 0.25)"]
    fig.legend(state_handles, state_names, loc="lower center", ncol=3,
              fontsize=7.6, frameon=False, bbox_to_anchor=(0.5, 0.135))
    ch, cl = fam_handles[id(axes[0])]
    lh, ll = fam_handles[id(axes[1])]
    fig.subplots_adjust(left=0.09, right=0.985, top=0.97, bottom=0.30,
                        wspace=0.08)
    _interleaved_legend(fig, ch, cl, lh, ll, bottom=0.005)
    fig.savefig(os.path.join(HERE, "imaging.pdf"))
    fig.savefig(os.path.join(HERE, "imaging.png"), dpi=170)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Figure 3: robust-taper lattice heatmap for one subarray

def pick_heatmap_subarray():
    """'main' if its lattice is well filled (few skipped/failed among the
    canonical ROBUST_LIST rows), else 'core'."""
    for name, fname in (("main", "main.csv"), ("core", "core.csv")):
        path = os.path.join(REPO, "curvegen", "results", fname)
        if not os.path.isfile(path):
            continue
        rows = list(csv.DictReader(open(path)))
        n_ok = sum(1 for r in rows if r.get("status") in ("ok", "capped"))
        if rows and n_ok / len(rows) > 0.9:
            return name, path, rows
    raise SystemExit("neither main.csv nor core.csv has a well-filled lattice")


def make_heatmap(samples_by, caps):
    name, path, rows = pick_heatmap_subarray()
    cells_by_key = mr.best_result_rows(rows)
    nat = cells_by_key.get(("natural", 2.0, 0.0))
    sigma_nat = float(nat["sigma_dirty"])

    imaging_curve = mr.build_curve(samples_by[name], skirt_max=mr.SKIRT_DEFAULT,
                                   max_res=caps[name])   # keeps env_keys
    hm = mr.build_heatmap(name, rows, sigma_nat, imaging_curve)
    if hm is None:
        raise SystemExit("build_heatmap returned None for %r" % name)

    tapers_mas = hm["tapers"]                     # ascending, [0] = untapered
    n_cols = len(tapers_mas)

    # sentinel x for the untapered column: one log-step below the first
    # nonzero taper, so it reads as its own labeled band to the left of the
    # (genuinely log-spaced) tapered columns.  main's native taper range is
    # sub-mas to ~0.4 arcsec, so ticks are labeled in mas (less awkward
    # leading-zero clutter than arcsec at this subarray's scale).
    nonzero = tapers_mas[1:]
    log_step = np.log10(nonzero[1] / nonzero[0])
    x_sentinel = nonzero[0] * 10 ** (-log_step)
    x_centers = np.array([x_sentinel] + nonzero)

    # rows: natural placed as a sentinel above robust=+2.0 (0.4 above, one
    # ROBUST_LIST step, so it is evenly spaced with the briggs rows)
    row_by_label = {r["label"]: r for r in hm["rows"]}
    robust_rows = sorted((float(lbl) for lbl in row_by_label if lbl != "natural"))
    y_sentinel = max(robust_rows) + 0.4
    y_centers = np.array(robust_rows + [y_sentinel])
    row_order = ["%+.1f" % r for r in robust_rows] + ["natural"]

    n_rows = len(y_centers)
    eta_arr = np.full((n_rows, n_cols), np.nan)
    skirt_arr = np.full((n_rows, n_cols), np.nan)
    env_mask = np.zeros((n_rows, n_cols), dtype=bool)
    status_arr = np.full((n_rows, n_cols), "", dtype=object)

    for i, label in enumerate(row_order):
        row = row_by_label[label]
        for j, cell in enumerate(row["cells"]):
            if cell is None:
                continue
            status_arr[i, j] = cell.get("status", "")
            if cell.get("status") in ("ok", "capped"):
                eta_arr[i, j] = cell["eta"]
                if cell.get("skirt") is not None:
                    skirt_arr[i, j] = cell["skirt"]
                env_mask[i, j] = bool(cell.get("env"))

    fig, ax = plt.subplots(figsize=(6.5, 5.0))

    eta_clamped = np.clip(eta_arr, 1.0, 5.0)
    eta_masked = np.ma.masked_invalid(eta_clamped)
    mesh = ax.pcolormesh(x_centers, y_centers, eta_masked, shading="nearest",
                         cmap="cividis_r", vmin=1.0, vmax=5.0,
                         edgecolors="white", linewidth=0.4)
    cb = fig.colorbar(mesh, ax=ax, pad=0.02, fraction=0.05)
    cb.set_label(r"$\eta$ (clamped at 5)")

    # skirt contours at the strict (0.10) and traded-cap (0.25) thresholds;
    # dark lines throughout since the colormap is light (yellow) at low eta,
    # where the 0.10 contour mostly lies
    skirt_masked = np.ma.masked_invalid(skirt_arr)
    if np.ma.count(skirt_masked) > 4:
        try:
            cs = ax.contour(x_centers, y_centers, skirt_masked,
                            levels=[0.10, 0.25], colors=["black", "black"],
                            linewidths=[1.6, 1.3], linestyles=["-", "--"])
            ax.clabel(cs, fmt={0.10: "skirt=0.10", 0.25: "skirt=0.25"},
                      fontsize=7.0, inline=True)
        except (ValueError, RuntimeError):
            pass   # too few finite points to contour meaningfully

    # cells not measured / failed
    for i in range(n_rows):
        for j in range(n_cols):
            st = status_arr[i, j]
            if st in ("skipped", "failed") or (st == "" and
                                               np.isnan(eta_arr[i, j])):
                marker = "x" if st == "failed" else "."
                ax.plot(x_centers[j], y_centers[i], marker=marker,
                        color="0.6", ms=3.5, mew=0.8)

    # points anchoring the default (s0=0.10) imaging envelope
    ys, xs = np.where(env_mask)
    if len(xs):
        ax.scatter(x_centers[xs], y_centers[ys], s=42, facecolors="none",
                  edgecolors="red", linewidths=1.3, zorder=5,
                  label="imaging-envelope anchor (s0=0.10)")
        ax.legend(loc="upper right", fontsize=7.2)

    ax.set_xscale("log")
    xticks = list(x_centers)
    ax.set_xticks(xticks)
    ax.set_xticklabels(["0"] + ["%.3g" % t for t in nonzero], rotation=45,
                       ha="right", fontsize=7)
    ax.set_yticks(list(y_centers))
    ax.set_yticklabels(["%+.1f" % r for r in robust_rows] + ["natural"])
    ax.set_xlabel("uv taper FWHM at 30 GHz (mas); leftmost column = no taper")
    ax.set_ylabel("Briggs robust")
    ax.grid(False)

    fig.subplots_adjust(left=0.11, right=0.99, top=0.98, bottom=0.22)
    fig.savefig(os.path.join(HERE, "heatmap.pdf"))
    fig.savefig(os.path.join(HERE, "heatmap.png"), dpi=170)
    plt.close(fig)
    return name


def main():
    samples_by, caps = load_samples_and_caps()
    make_taperability(samples_by, caps)
    make_imaging(samples_by, caps)
    hm_name = make_heatmap(samples_by, caps)
    print("heatmap subarray:", hm_name)
    for fn in ("taperability.pdf", "imaging.pdf", "heatmap.pdf",
              "taperability.png", "imaging.png", "heatmap.png"):
        p = os.path.join(HERE, fn)
        print(fn, os.path.getsize(p), "bytes")


if __name__ == "__main__":
    main()

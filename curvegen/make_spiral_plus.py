"""
Compute the spiral+5 / spiral+10 core-antenna selection (Rev F only).

Definition (bmason, 7 Sep 2026; docs/plans/spiral-plus-subarrays-spec.md):

  spiral+5  = the Rev F spiral (54 stations, arms spa..spe) plus, for each
              arm, the core antenna closest to that arm's innermost spiral
              station (5 antennas total, one per arm).
  spiral+10 = spiral+5 plus, for each arm, the next core antenna inward:
              treat the antenna chosen for spiral+5 as the arm's new tip and
              take the closest not-yet-chosen core antenna to it (10 antennas
              total).

"Closest" is tangent-plane (local East-North) distance from the core
centroid, NOT 3-D geocentric distance -- the cfg files are geocentric ECEF
XYZ, so a straight XYZ distance would be dominated by the (near-uniform,
Earth-radius-scale) offset direction rather than the local geometry.  Arms
are processed in order a..e; an antenna, once chosen, is unavailable to the
remaining arms (including across the +5 -> +10 passes).

This is a CASA-free (numpy/matplotlib only), deterministic, offline
calculation: it reads the two Rev F .cfg files, does no simulation, and
writes/plots the result.  Run:

  casapy curvegen/make_spiral_plus.py
  casapy curvegen/make_spiral_plus.py --plot docs/figures/spiral_plus_selection.png
"""

import argparse
import csv
import os
import re

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT_DIR = os.path.join(REPO, "ngvla-configurations", "Rev F", "CASA Files")
CORE_CFG = os.path.join(COMPONENT_DIR, "RevF_Core_2025_01_27_xyz.cfg")
SPIRAL_CFG = os.path.join(COMPONENT_DIR, "RevF_Spiral_2025_01_16_xyz.cfg")
OUT_CSV = os.path.join(REPO, "sa_select", "data", "spiral_plus_selection.csv")

ARMS = ["spa", "spb", "spc", "spd", "spe"]

# WGS84 ellipsoid constants
_A = 6378137.0
_F = 1.0 / 298.257223563
_E2 = _F * (2.0 - _F)


def read_cfg(path):
    """Return (names, xyz) for a CASA XYZ-format .cfg file."""
    names, xyz = [], []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            xyz.append([float(parts[0]), float(parts[1]), float(parts[2])])
            names.append(parts[-1])
    return names, np.array(xyz)


def ecef_to_geodetic(x, y, z):
    """WGS84 ECEF -> geodetic (lat, lon in radians), Bowring iteration."""
    lon = np.arctan2(y, x)
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1.0 - _E2))
    for _ in range(5):
        n = _A / np.sqrt(1.0 - _E2 * np.sin(lat) ** 2)
        h = p / np.cos(lat) - n
        lat = np.arctan2(z, p * (1.0 - _E2 * n / (n + h)))
    return lat, lon


def ecef_to_enu(dxyz, lat0, lon0):
    """dxyz: (N,3) ECEF offsets from an origin -> (N,3) local East/North/Up."""
    sl, cl = np.sin(lon0), np.cos(lon0)
    sp, cp = np.sin(lat0), np.cos(lat0)
    dx, dy, dz = dxyz[:, 0], dxyz[:, 1], dxyz[:, 2]
    e = -sl * dx + cl * dy
    n = -sp * cl * dx - sp * sl * dy + cp * dz
    u = cp * cl * dx + cp * sl * dy + sp * dz
    return np.column_stack([e, n, u])


def arm_of(name):
    m = re.match(r"(sp[a-e])", name)
    return m.group(1) if m else None


def compute_selection():
    """Return (rows, geometry) where rows is a list of dicts (one per
    chosen core antenna, in selection order) and geometry carries the
    tangent-plane coordinates for plotting."""
    core_names, core_xyz = read_cfg(CORE_CFG)
    spiral_names, spiral_xyz = read_cfg(SPIRAL_CFG)

    centroid = core_xyz.mean(axis=0)
    lat0, lon0 = ecef_to_geodetic(*centroid)

    core_enu = ecef_to_enu(core_xyz - centroid, lat0, lon0)
    spiral_enu = ecef_to_enu(spiral_xyz - centroid, lat0, lon0)

    core_r = np.hypot(core_enu[:, 0], core_enu[:, 1])
    spiral_r = np.hypot(spiral_enu[:, 0], spiral_enu[:, 1])
    core_az = np.degrees(np.arctan2(core_enu[:, 0], core_enu[:, 1])) % 360.0
    spiral_az = np.degrees(np.arctan2(spiral_enu[:, 0], spiral_enu[:, 1])) % 360.0

    # sanity: core radii should be a few km at most (memo 121 core diameter
    # ~1 km scale); if this trips, the ECEF->ENU conversion is wrong.
    assert core_r.max() < 5000.0, (
        "core radius %.1f m exceeds sanity bound -- check ENU conversion"
        % core_r.max())

    # innermost station per arm
    tips = {}
    for arm in ARMS:
        idx = [i for i, nm in enumerate(spiral_names) if arm_of(nm) == arm]
        if not idx:
            raise ValueError("no spiral stations found for arm %r" % arm)
        inner = min(idx, key=lambda i: spiral_r[i])
        tips[arm] = dict(station=spiral_names[inner],
                          e=spiral_enu[inner, 0], n=spiral_enu[inner, 1],
                          r=spiral_r[inner], az=spiral_az[inner])

    chosen = set()
    rows = []

    def pick_pass(tag):
        for arm in ARMS:
            tip = tips[arm]
            best_i, best_d = None, None
            for i, nm in enumerate(core_names):
                if nm in chosen:
                    continue
                d = np.hypot(core_enu[i, 0] - tip["e"], core_enu[i, 1] - tip["n"])
                if best_d is None or d < best_d:
                    best_i, best_d = i, d
            chosen.add(core_names[best_i])
            az_diff = ((core_az[best_i] - tip["az"] + 180.0) % 360.0) - 180.0
            rows.append(dict(
                set=tag, arm=arm, tip_station=tip["station"],
                chosen_antenna=core_names[best_i],
                distance_m=best_d, r_antenna_m=core_r[best_i],
                r_tip_m=tip["r"], az_diff_deg=az_diff,
            ))
            # +10 pass treats the newly chosen antenna as the arm's new tip
            tips[arm] = dict(station=core_names[best_i],
                              e=core_enu[best_i, 0], n=core_enu[best_i, 1],
                              r=core_r[best_i], az=core_az[best_i])

    pick_pass("+5")
    pick_pass("+10")

    geometry = dict(
        core_names=core_names, core_enu=core_enu, core_r=core_r,
        spiral_names=spiral_names, spiral_enu=spiral_enu, spiral_r=spiral_r,
        centroid_lat=lat0, centroid_lon=lon0,
    )
    return rows, geometry


FIELDS = ["set", "arm", "tip_station", "chosen_antenna", "distance_m",
          "r_antenna_m", "r_tip_m", "az_diff_deg"]


def write_csv(rows, path=OUT_CSV):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({
                "set": r["set"], "arm": r["arm"],
                "tip_station": r["tip_station"],
                "chosen_antenna": r["chosen_antenna"],
                "distance_m": "%.3f" % r["distance_m"],
                "r_antenna_m": "%.3f" % r["r_antenna_m"],
                "r_tip_m": "%.3f" % r["r_tip_m"],
                "az_diff_deg": "%.2f" % r["az_diff_deg"],
            })


def print_table(rows):
    hdr = "%-4s %-4s %-12s %-14s %10s %12s %10s %9s" % (
        "set", "arm", "tip", "chosen", "dist_m", "r_ant_m", "r_tip_m", "az_diff")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print("%-4s %-4s %-12s %-14s %10.2f %12.2f %10.2f %9.2f" % (
            r["set"], r["arm"], r["tip_station"], r["chosen_antenna"],
            r["distance_m"], r["r_antenna_m"], r["r_tip_m"], r["az_diff_deg"]))


def make_plot(rows, geometry, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    core_enu = geometry["core_enu"] / 1000.0    # km
    core_names = geometry["core_names"]
    spiral_enu = geometry["spiral_enu"] / 1000.0
    spiral_names = geometry["spiral_names"]
    spiral_r = geometry["spiral_r"]

    colors = {"spa": "tab:blue", "spb": "tab:orange", "spc": "tab:green",
              "spd": "tab:red", "spe": "tab:purple"}

    chosen5 = {r["arm"]: r["chosen_antenna"] for r in rows if r["set"] == "+5"}
    chosen10 = {r["arm"]: r["chosen_antenna"] for r in rows if r["set"] == "+10"}
    tip5 = {r["arm"]: r["tip_station"] for r in rows if r["set"] == "+5"}
    tip10 = {r["arm"]: r["tip_station"] for r in rows if r["set"] == "+10"}
    name_to_enu_core = {nm: core_enu[i, :2] for i, nm in enumerate(core_names)}
    name_to_enu_spiral = {nm: spiral_enu[i, :2] for i, nm in enumerate(spiral_names)}

    def pos(name):
        return name_to_enu_core.get(name, name_to_enu_spiral.get(name))

    fig, axes = plt.subplots(1, 2, figsize=(13, 6.5))

    for ax, zoom in ((axes[0], False), (axes[1], True)):
        ax.scatter(core_enu[:, 0], core_enu[:, 1], s=8, c="0.7",
                   label="core (all)", zorder=1)

        # first 3-4 innermost stations per arm, labelled
        for arm in ARMS:
            idx = [i for i, nm in enumerate(spiral_names) if arm_of(nm) == arm]
            idx = sorted(idx, key=lambda i: spiral_r[i])[:4]
            xs = spiral_enu[idx, 0]
            ys = spiral_enu[idx, 1]
            ax.scatter(xs, ys, s=30, c=colors[arm], marker="o",
                      edgecolors="k", linewidths=0.4, zorder=3,
                      label=("spiral arm %s (innermost)" % arm) if not zoom else None)
            if not zoom:
                for i in idx:
                    ax.annotate(spiral_names[i],
                               (spiral_enu[i, 0], spiral_enu[i, 1]),
                               fontsize=6, xytext=(3, 3),
                               textcoords="offset points")

        for arm in ARMS:
            p5 = pos(chosen5[arm])
            ax.scatter(*p5, s=110, c=colors[arm], marker="o",
                      edgecolors="k", linewidths=0.8, zorder=4,
                      label=("+5 pick" if arm == ARMS[0] else None))
            ax.annotate(chosen5[arm], p5, fontsize=6.5, xytext=(4, 4),
                       textcoords="offset points", weight="bold")
            p10 = pos(chosen10[arm])
            ax.scatter(*p10, s=140, facecolors="none", edgecolors=colors[arm],
                      linewidths=2.0, marker="o", zorder=4,
                      label=("+10 pick" if arm == ARMS[0] else None))
            ax.annotate(chosen10[arm], p10, fontsize=6.5, xytext=(4, -8),
                       textcoords="offset points", weight="bold")

            t5 = pos(tip5[arm])
            ax.annotate("", xy=p5, xytext=t5,
                       arrowprops=dict(arrowstyle="->", color=colors[arm], lw=1.3))
            t10 = pos(tip10[arm])
            ax.annotate("", xy=p10, xytext=t10,
                       arrowprops=dict(arrowstyle="->", color=colors[arm], lw=1.3,
                                       linestyle="dashed"))

        ax.set_xlabel("East (km)")
        ax.set_ylabel("North (km)")
        ax.set_aspect("equal", adjustable="datalim")
        if zoom:
            all_pts = np.array([pos(chosen10[a]) for a in ARMS]
                               + [pos(chosen5[a]) for a in ARMS]
                               + [pos(tip5[a]) for a in ARMS])
            pad = 0.4
            ax.set_xlim(all_pts[:, 0].min() - pad, all_pts[:, 0].max() + pad)
            ax.set_ylim(all_pts[:, 1].min() - pad, all_pts[:, 1].max() + pad)
            ax.set_title("zoom: core edge / spiral tips")
        else:
            ax.set_title("full array")

    axes[0].legend(loc="upper left", fontsize=7, framealpha=0.9)
    fig.suptitle("spiral+5/+10: per arm, closest unselected core antenna to the "
                "arm's (recursively updated) tip, tangent-plane distance",
                fontsize=9.5)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, dpi=150)
    print("wrote figure -> %s" % out_path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plot", metavar="PATH", default=None,
                    help="also write a figure to PATH (e.g. "
                         "docs/figures/spiral_plus_selection.png)")
    ap.add_argument("--csv", metavar="PATH", default=OUT_CSV,
                    help="output selection-table CSV path (default: %s)"
                         % OUT_CSV)
    args = ap.parse_args()

    rows, geometry = compute_selection()
    print_table(rows)
    write_csv(rows, args.csv)
    print("wrote %d rows -> %s" % (len(rows), args.csv))
    if args.plot:
        make_plot(rows, geometry, args.plot)

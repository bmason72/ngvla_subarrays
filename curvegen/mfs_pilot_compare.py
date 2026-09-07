#!/usr/bin/env python3
"""
Compare two MFS imaging pilot results directories point-by-point (nchan
convergence -- docs/plans/MFS_CAMPAIGN_PLAN.md "Pilots" #2), CASA-free (plain
python3 or casapy; only stdlib).

  mfs_pilot_compare.py --ref results-A --other results-B \\
      [--subarrays core main] [--out report.md]

  mfs_pilot_compare.py --ref results-A [--subarrays core main]   # timing-only
                                                                   # (cost
                                                                   # benchmark:
                                                                   # no --other)

For each subarray, rows with status=ok are joined on the canonical
(weighting, robust, taper_mas) key (same rounding as adaptive.canon_rt /
sweep.point_key).  Per matched point this reports:
  eta_A, eta_B           sigma_dirty / that dir's own natural-seed sigma_dirty
  d_eta                  |eta_B - eta_A| / eta_A
  d_res                  |res_B - res_A| / res_A   (res_geo_arcsec)
  d_bmaj, d_bmin          relative differences of the fitted beam axes
  d_skirt                 absolute difference of the PSF skirt level
  elapsed_A, elapsed_B    tclean wall time (seconds) recorded by each sweep

Adopt-27 criteria (plan's "Adopt 27 if 27->54 gives ..."):
  * every matched point:        d_eta < 0.005  and  d_res < 0.01
  * both seed points (endpoints): d_res < 0.01  and  d_skirt < 0.02
  * envelope over the whole matched set: p95(d_eta) < 0.01, max(d_eta) < 0.02

Exit codes: 0 pass (or timing-only mode with no criteria to fail),
3 criteria fail, 2 usage/missing-data.
"""

import argparse
import csv
import json
import os
import sys

SEED_KEYS = {("natural", 2.0, 0.0), ("briggs", -2.0, 0.0)}
DEFAULT_SUBARRAYS = ("core", "main")

D_ETA_POINT_MAX = 0.005
D_RES_POINT_MAX = 0.01
D_RES_ENDPOINT_MAX = 0.01
D_SKIRT_ENDPOINT_MAX = 0.02
P95_D_ETA_MAX = 0.01
MAX_D_ETA_MAX = 0.02


# --------------------------------------------------------------------------- #
# CSV / manifest reading (no config.py import -- this tool must run without a
# casapy/MFS environment, and must never touch the real results dirs from a
# test; see the "config caching" note in tests/test_mfs_pilot.py).

def _csv_path(results_dir, subarray):
    return os.path.join(
        results_dir, subarray.replace("+", "_").replace("-", "_") + ".csv")


def canon_key(weighting, robust, taper):
    """Canonical (weighting, robust, taper) tuple -- match adaptive.canon_rt /
    sweep.point_key's rounding and negative-zero folding."""
    r = round(float(robust), 2)
    t = round(float(taper), 3)
    if r == 0.0:
        r = 0.0
    if t == 0.0:
        t = 0.0
    return (weighting, r, t)


def read_all_rows(results_dir, subarray):
    """{canon_key: row} for every row in <subarray>.csv, any status.  {} if
    the CSV does not exist (a subarray simply not yet swept)."""
    path = _csv_path(results_dir, subarray)
    rows = {}
    if not os.path.isfile(path):
        return rows
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows[canon_key(row["weighting"], row["robust"],
                           row["taper_mas"])] = row
    return rows


def read_manifest(results_dir):
    path = os.path.join(results_dir, "campaign_manifest.json")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


def manifest_nchan(manifest):
    if not manifest:
        return None
    return (manifest.get("spectral_window") or {}).get("nchan")


# --------------------------------------------------------------------------- #
# statistics (no numpy -- keep this tool importable by plain python3)

def percentile(values, pct):
    """Linear-interpolation percentile (matches numpy's default 'linear')."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def timing_stats(rows):
    """(n, median, max) of elapsed_s over ok rows that recorded one, or None."""
    elapsed = sorted(float(r["elapsed_s"]) for r in rows.values()
                     if r.get("status") == "ok" and r.get("elapsed_s"))
    if not elapsed:
        return None
    n = len(elapsed)
    median = (elapsed[n // 2] if n % 2 else
              0.5 * (elapsed[n // 2 - 1] + elapsed[n // 2]))
    return dict(n=n, median=median, max=elapsed[-1])


def imsize_of(rows):
    for r in rows.values():
        if r.get("imsize"):
            return r["imsize"]
    return None


# --------------------------------------------------------------------------- #
# comparison

def _eta_reference(rows):
    """sigma_dirty of the natural, taper=0 seed (this dir's eta=1 reference)."""
    nat = rows.get(("natural", 2.0, 0.0))
    if not nat or nat.get("status") != "ok":
        return None
    return float(nat["sigma_dirty"])


def compare_subarray(ref_dir, other_dir, subarray):
    """Returns (matched, problems) for one subarray.

    matched: list of dicts (weighting, robust, taper_mas, eta_A, eta_B, d_eta,
      d_res, d_bmaj, d_bmin, d_skirt, elapsed_A, elapsed_B, is_endpoint) for
      every key that is status=ok in BOTH dirs.
    problems: list of (key, status_A, status_B) for every key that is missing
      or non-ok in either dir (unmatched or failed/capped/skipped points).
    """
    ref_rows = read_all_rows(ref_dir, subarray)
    other_rows = read_all_rows(other_dir, subarray)
    eta0_ref = _eta_reference(ref_rows)
    eta0_other = _eta_reference(other_rows)

    matched, problems = [], []
    for key in sorted(set(ref_rows) | set(other_rows)):
        a = ref_rows.get(key)
        b = other_rows.get(key)
        status_a = (a or {}).get("status", "missing")
        status_b = (b or {}).get("status", "missing")
        if status_a != "ok" or status_b != "ok":
            problems.append((key, status_a, status_b))
            continue
        if eta0_ref is None or eta0_other is None:
            problems.append((key, "no-natural-seed-ref" if eta0_ref is None
                            else status_a,
                            "no-natural-seed-other" if eta0_other is None
                            else status_b))
            continue
        eta_a = float(a["sigma_dirty"]) / eta0_ref
        eta_b = float(b["sigma_dirty"]) / eta0_other
        res_a, res_b = float(a["res_geo_arcsec"]), float(b["res_geo_arcsec"])
        bmaj_a, bmaj_b = float(a["bmaj_arcsec"]), float(b["bmaj_arcsec"])
        bmin_a, bmin_b = float(a["bmin_arcsec"]), float(b["bmin_arcsec"])
        skirt_a, skirt_b = float(a["skirt"]), float(b["skirt"])
        matched.append(dict(
            weighting=key[0], robust=key[1], taper_mas=key[2],
            eta_A=eta_a, eta_B=eta_b,
            d_eta=(abs(eta_b - eta_a) / eta_a if eta_a else float("inf")),
            d_res=(abs(res_b - res_a) / res_a if res_a else float("inf")),
            d_bmaj=(abs(bmaj_b - bmaj_a) / bmaj_a if bmaj_a else float("inf")),
            d_bmin=(abs(bmin_b - bmin_a) / bmin_a if bmin_a else float("inf")),
            d_skirt=abs(skirt_b - skirt_a),
            elapsed_A=float(a.get("elapsed_s") or 0.0),
            elapsed_B=float(b.get("elapsed_s") or 0.0),
            is_endpoint=key in SEED_KEYS))
    return matched, problems


def evaluate(matched):
    """Return (failures, p95_d_eta, max_d_eta) for one subarray's matched set."""
    failures = []
    for m in matched:
        label = "%s_%.2f_%.3f" % (m["weighting"], m["robust"], m["taper_mas"])
        if m["d_eta"] >= D_ETA_POINT_MAX or m["d_res"] >= D_RES_POINT_MAX:
            failures.append(
                "point %s: d_eta=%.4g (limit %.3g), d_res=%.4g (limit %.3g)"
                % (label, m["d_eta"], D_ETA_POINT_MAX, m["d_res"], D_RES_POINT_MAX))
        if m["is_endpoint"] and (m["d_res"] >= D_RES_ENDPOINT_MAX
                                 or m["d_skirt"] >= D_SKIRT_ENDPOINT_MAX):
            failures.append(
                "endpoint %s: d_res=%.4g (limit %.3g), d_skirt=%.4g (limit %.3g)"
                % (label, m["d_res"], D_RES_ENDPOINT_MAX, m["d_skirt"],
                   D_SKIRT_ENDPOINT_MAX))
    d_etas = [m["d_eta"] for m in matched]
    p95 = percentile(d_etas, 95)
    mx = max(d_etas) if d_etas else None
    if p95 is not None and p95 >= P95_D_ETA_MAX:
        failures.append("p95(d_eta)=%.4g exceeds %.3g" % (p95, P95_D_ETA_MAX))
    if mx is not None and mx >= MAX_D_ETA_MAX:
        failures.append("max(d_eta)=%.4g exceeds %.3g" % (mx, MAX_D_ETA_MAX))
    return failures, p95, mx


# --------------------------------------------------------------------------- #
# reporting

def _fmt(v, spec="%.4g"):
    return spec % v if isinstance(v, float) else str(v)


def build_timing_table(dirs_labels, subarrays):
    """dirs_labels: [(label, results_dir), ...].  Markdown timing table."""
    lines = ["| subarray | variant | nchan | imsize | n_ok | median_s | max_s |",
             "|---|---|---|---|---|---|---|"]
    for label, d in dirs_labels:
        manifest = read_manifest(d)
        nchan = manifest_nchan(manifest)
        for sa in subarrays:
            rows = read_all_rows(d, sa)
            stats = timing_stats(rows)
            imsize = imsize_of(rows)
            if stats is None:
                lines.append("| %s | %s | %s | %s | 0 | - | - |"
                             % (sa, label, nchan, imsize))
            else:
                lines.append("| %s | %s | %s | %s | %d | %.1f | %.1f |"
                             % (sa, label, nchan, imsize, stats["n"],
                                stats["median"], stats["max"]))
    return lines


def build_report(ref_dir, other_dir, subarrays):
    """Returns (report_lines, overall_ok:bool)."""
    lines = ["# MFS imaging pilot: nchan convergence", ""]
    ref_manifest = read_manifest(ref_dir)
    other_manifest = read_manifest(other_dir)
    lines.append("ref: `%s` (nchan=%s)" % (ref_dir, manifest_nchan(ref_manifest)))
    lines.append("other: `%s` (nchan=%s)" % (other_dir, manifest_nchan(other_manifest)))
    lines.append("")
    lines.append("## Timing")
    lines.extend(build_timing_table(
        [("ref", ref_dir), ("other", other_dir)], subarrays))
    lines.append("")

    overall_ok = True
    all_failures = []
    for sa in subarrays:
        matched, problems = compare_subarray(ref_dir, other_dir, sa)
        lines.append("## %s: matched points (%d)" % (sa, len(matched)))
        lines.append("| weighting | robust | taper_mas | eta_A | eta_B | "
                     "d_eta | d_res | d_bmaj | d_bmin | d_skirt | elapsed_A | "
                     "elapsed_B | endpoint |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for m in sorted(matched, key=lambda m: (m["weighting"], m["robust"],
                                                m["taper_mas"])):
            lines.append(
                "| %s | %.2f | %.3f | %.4g | %.4g | %.4g | %.4g | %.4g | "
                "%.4g | %.4g | %.1f | %.1f | %s |"
                % (m["weighting"], m["robust"], m["taper_mas"], m["eta_A"],
                   m["eta_B"], m["d_eta"], m["d_res"], m["d_bmaj"], m["d_bmin"],
                   m["d_skirt"], m["elapsed_A"], m["elapsed_B"],
                   "yes" if m["is_endpoint"] else ""))
        if problems:
            lines.append("")
            lines.append("### %s: unmatched / non-ok points (%d)"
                         % (sa, len(problems)))
            lines.append("| weighting | robust | taper_mas | status_ref | "
                         "status_other |")
            lines.append("|---|---|---|---|---|")
            for key, sa_ref, sa_other in problems:
                lines.append("| %s | %.2f | %.3f | %s | %s |"
                             % (key[0], key[1], key[2], sa_ref, sa_other))
        failures, p95, mx = evaluate(matched)
        lines.append("")
        lines.append("**%s criteria:** p95(d_eta)=%s max(d_eta)=%s -> %s"
                     % (sa, _fmt(p95) if p95 is not None else "n/a",
                        _fmt(mx) if mx is not None else "n/a",
                        "PASS" if not failures else "FAIL"))
        if failures:
            overall_ok = False
            for f in failures:
                lines.append("  - FAIL: %s" % f)
        all_failures.extend("%s: %s" % (sa, f) for f in failures)
        lines.append("")

    lines.append("## Result: %s" % ("PASS" if overall_ok else "FAIL"))
    if all_failures:
        lines.append("")
        lines.append("Failing criteria:")
        for f in all_failures:
            lines.append("- %s" % f)
    return lines, overall_ok


def build_timing_only_report(ref_dir, subarrays):
    lines = ["# MFS imaging pilot: timing (cost benchmark)", ""]
    manifest = read_manifest(ref_dir)
    lines.append("dir: `%s` (nchan=%s)" % (ref_dir, manifest_nchan(manifest)))
    lines.append("")
    lines.extend(build_timing_table([("ref", ref_dir)], subarrays))
    return lines


# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", required=True, help="reference results dir")
    ap.add_argument("--other", help="the other results dir (omit for "
                    "timing-only / cost-benchmark mode)")
    ap.add_argument("--subarrays", nargs="+", default=list(DEFAULT_SUBARRAYS))
    ap.add_argument("--out", help="write the markdown report here too")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.ref):
        print("error: --ref is not a directory: %s" % args.ref, file=sys.stderr)
        return 2
    if args.other is not None and not os.path.isdir(args.other):
        print("error: --other is not a directory: %s" % args.other,
              file=sys.stderr)
        return 2

    if args.other is None:
        lines = build_timing_only_report(args.ref, args.subarrays)
        ok = True
    else:
        lines, ok = build_report(args.ref, args.other, args.subarrays)

    report = "\n".join(lines) + "\n"
    print(report)
    if args.out:
        outdir = os.path.dirname(args.out)
        if outdir:
            os.makedirs(outdir, exist_ok=True)
        with open(args.out, "w") as f:
            f.write(report)

    if args.other is None:
        return 0
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())

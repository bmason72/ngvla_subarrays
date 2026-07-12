"""
Collect sweep results into the sa_select curve-sample table.

Reads curvegen/results/<subarray>.csv files, computes eta for every point as
sigma_dirty / sigma_dirty(natural, untapered), and writes all subarrays'
samples to sa_select/data/revf_curves.csv in the schema documented in
sa_select/schema.py (same columns as bootstrap_curves.csv, freq_orig = 30).

Run:  .../python3 collect.py            # all result files
"""

import csv
import glob
import os

from config import RESULTS_DIR, REPO, OVERSAMPLE, REV, SIM_MODE

DATA_DIR = os.path.join(REPO, "sa_select", "data")


def registry_paths(rev=REV, sim_mode=SIM_MODE):
    """(subarrays_csv, samples_csv) absolute paths for the active (rev,
    sim_mode), resolved through sa_select/data/config_registry.csv.  This is
    the SAME registry sa_select.CurveLibrary.for_config reads, so a campaign's
    output lands exactly where the selector will look for it.  An unregistered
    combination is a hard error telling the operator to add a row."""
    reg_path = os.path.join(DATA_DIR, "config_registry.csv")
    with open(reg_path, newline="") as f:
        for r in csv.DictReader(f):
            if r["rev"].strip() == rev and r["sim_mode"].strip() == sim_mode:
                return (os.path.join(DATA_DIR, r["subarrays_csv"].strip()),
                        os.path.join(DATA_DIR, r["samples_csv"].strip()))
    raise SystemExit(
        "collect.py: no config_registry.csv row for (rev=%r, sim_mode=%r).\n"
        "Add a row 'rev,sim_mode,subarrays_csv,samples_csv' to %s before "
        "collecting this campaign's curves." % (rev, sim_mode, reg_path))


SUBARRAYS_CSV, OUT = registry_paths()


def offered_subarrays():
    """Subarrays the selector offers (rows of the active combo's subarrays
    CSV).  Result files for other subarrays (e.g. in-progress campaign members,
    or the dropped core+mid) are skipped until their metadata lands."""
    with open(SUBARRAYS_CSV, newline="") as f:
        return {r["name"].strip() for r in csv.DictReader(f)}

OUT_FIELDS = ["subarray", "resolution_arcsec_30ghz", "eta", "skirt",
              "weighting", "robust", "taper_arcsec_30ghz", "freq_orig_ghz",
              "source", "note", "sample_status"]


def check_cell_convention(r, path):
    """Refuse to publish measurements imaged under a stale cell convention.

    run_point uses cell = max(native, taper_mas/OVERSAMPLE/1e3); Briggs
    weights depend on the gridded uv density, so a row imaged with a
    finer-than-adaptive cell is measured under a DIFFERENT weighting
    convention (the 9 Jul 2026 stale-sculpt-block incident: fake strict
    islands in the imaging curves).  Hard failure by design -- repair with
    curvegen/repair_stale_cells.py rather than silently mixing conventions.
    """
    taper_mas = float(r["taper_mas"])
    if taper_mas <= 0 or not r["cell_arcsec"]:
        return
    need = taper_mas / OVERSAMPLE / 1e3
    if float(r["cell_arcsec"]) < need * 0.999:
        raise RuntimeError(
            "%s: %s r=%s t=%s imaged with cell %s < adaptive %.6g arcsec "
            "(stale convention) -- run curvegen/repair_stale_cells.py"
            % (path, r["weighting"], r["robust"], r["taper_mas"],
               r["cell_arcsec"], need))


def collect_one(path):
    # capped rows (beam beyond the heterogeneous cap) are collected as
    # interpolation ANCHORS (sample_status=capped_anchor): they extend row
    # coverage up to the cap so the offered curve can end exactly there,
    # but the engine/report/selector never offer a beam beyond the cap
    # (9 Jul 2026; see PLAN.md and sa_select/schema.py)
    with open(path, newline="") as f:
        rows = [r for r in csv.DictReader(f)
                if r["status"] in ("ok", "capped")]
    if not rows:
        return []
    nat = [r for r in rows if r["status"] == "ok"
           and r["weighting"] == "natural" and float(r["taper_mas"]) == 0]
    if not nat:
        raise RuntimeError("%s has no natural/untapered reference point" % path)
    sigma_nat = float(nat[0]["sigma_dirty"])

    out, seen = [], set()
    for r in rows:
        check_cell_convention(r, path)
        taper_mas = float(r["taper_mas"])
        eta = float(r["sigma_dirty"]) / sigma_nat
        # hygiene (post-mortem M4d): -0.0 and 0.0 are one robust value, and
        # a lattice point measured twice is one sample (first kept)
        robust = "" if r["weighting"] == "natural" else \
            "%g" % (abs(float(r["robust"])) if float(r["robust"]) == 0
                    else float(r["robust"]))
        key = (r["subarray"], r["weighting"], robust, round(taper_mas, 6))
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(
            subarray=r["subarray"],
            resolution_arcsec_30ghz="%.6g" % float(r["res_geo_arcsec"]),
            eta="%.4f" % eta,
            skirt=r["skirt"],
            weighting=r["weighting"],
            robust=robust,
            taper_arcsec_30ghz="" if taper_mas == 0 else "%.6g" % (taper_mas / 1e3),
            freq_orig_ghz="30.0",
            source="revf-sim:%s:%s_r%s_t%s" % (r["subarray"], r["weighting"],
                                               r["robust"], r["taper_mas"]),
            note="",
            sample_status="ok" if r["status"] == "ok" else "capped_anchor",
        ))
    return out


# subarrays excluded from the curve table.  core+mid was fully measured
# (v2 beam-cap sweep, clean) but DROPPED from the offered set (bmason,
# 6 Jul 2026): no science case requested it and its uv coverage is poor.
# The sweep results remain in results/ as the record.
DEFERRED = {"core_mid.csv"}


def main():
    offered = offered_subarrays()
    samples = []
    for path in sorted(glob.glob(os.path.join(RESULTS_DIR, "*.csv"))):
        if ".csv.shard_" in os.path.basename(path):
            continue                    # sweep_parallel.py in-flight shards
        if os.path.basename(path) in DEFERRED:
            print("%-28s deferred (heterogeneous; see PLAN.md)"
                  % os.path.basename(path))
            continue
        got = collect_one(path)
        if got and got[0]["subarray"] not in offered:
            print("%-28s skipped (subarray %r not offered yet)"
                  % (os.path.basename(path), got[0]["subarray"]))
            continue
        print("%-28s %3d samples" % (os.path.basename(path), len(got)))
        samples += got
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(samples)
    print("wrote %d samples -> %s" % (len(samples), OUT))


if __name__ == "__main__":
    main()

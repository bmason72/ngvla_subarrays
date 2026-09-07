"""
MFS-2d / V1 retrospective replay harness (docs/plans/mfs-v1-replay-spec.md).

CASA-free, pure sa_select + curvegen planning logic: never runs tclean or
simulate.py.  Replays each EXISTING mono map's full point table through the
adaptive sampler policy (curvegen/adaptive.py) as a simulated acquisition,
where each "measurement" is a table lookup (ReplaySweep) rather than a new
tclean image, then scores the replayed subset against the full-table truth.
This is the V1 gate (docs/features/MFS2_ADAPTIVE_SAMPLER_SPEC.md,
"Validation gates") that must pass before any fresh-seed MFS wave deploys.

Oracle rule (spec finding #3): acceptance metrics are computed on EXACT
point_key hits only.  A policy request with no exact hit is an "unsupported
request" -- ReplaySweep keeps the simulation moving with a flagged fallback
(nearest full-table row, never re-measured, never scored) so the sampler's
own topology/certification logic can proceed exactly as it would on a real
partially-measured map, but every metric below is computed from the
exact-hit subset only.

Architecture finding (orchestrator, 5 Sep 2026): the sampler's default fresh
seed uses 7 log-uniform taper levels that do NOT coincide with the measured
14 (or 18, heterogeneous) canonical taper lattice, so a literal fresh replay
would make almost every tapered request an "unsupported request".  The fix
(threaded through adaptive.py as the new, default-preserving `seed_tapers`
argument) is to seed the replay's fresh-mode QuadTree with the SAME
every-other canonical taper grid the retrofit branch derives -- see
`_canonical_seed_tapers` below and `QuadTree._seed_nodes`.

Invocation:

    casapy replay_v1.py <subarray>      # replay ONE map in the CURRENT env
                                         # combo (NGVLA_REV / NGVLA_SIM_MODE)
    casapy replay_v1.py --suite         # the fixed 10-map suite across all
                                         # four combos (spawns one casapy
                                         # subprocess per map, since config.py
                                         # resolves RESULTS_DIR/BEAM_CAP_ARCSEC
                                         # from the environment at import time)

Output: curvegen/reports/v1_replay/<rev>_<sim_mode>_<subarray>.json per map
(metrics, requests/hits/fallbacks, stop reason, wave log) and
curvegen/reports/v1_replay/REPORT.md (one row per map + verdict + p90
sample fraction), written by --suite (a single `<subarray>` run writes only
its own per-map JSON).
"""

import argparse
import csv
import io
import json
import math
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from config import (REV, SIM_MODE, BEAM_CAP_ARCSEC, SUBARRAYS, grid_rows)
from adaptive import (PointTable, Sampler, run_wave_loop, results_csv_path,
                      robust_to_u, taper_to_v, _Envelope, STEP, TAU,
                      AUDIT_FRESH)
from adaptive_support import point_key
from make_report import build_curve, SKIRT_SETPOINTS

# casapy wrapper (docs/ops/casaLocation.md): every subprocess --suite spawns
# imports curvegen modules, so it MUST run under this interpreter (overridable
# for portability, e.g. a different TACC allocation/checkout).
CASAPY_BIN = os.environ.get("NGVLA_CASAPY",
                            "/work2/10240/bmason72/stampede3/casaenv/bin/casapy")

DEFAULT_OUT_DIR = os.path.join(REPO, "curvegen", "reports", "v1_replay")

# scoring constants (spec "Scoring")
N_REGRET_BINS = 40          # "~40 log-spaced resolution bins"
REGRET_TOL = 0.1            # max regret <= 0.1
RES_MARGIN = 0.05           # "+-5% resolution" (skirt feasibility windows)
SIGMA_SKIRT = TAU[2]        # spec's "SIGMA skirt (0.02)" -- adaptive.TAU's
#                             skirt tolerance component (0.02); the spec
#                             names it "SIGMA" informally, there is no
#                             separate skirt-jitter constant with that value.
SAMPLE_FRACTION_P90_MAX = 0.6

# the fixed stratified 10-map suite (spec finding #12 / "Suite")
SUITE = [
    ("revD", "snapshot", ["main+long", "long", "main"]),
    ("revF", "snapshot", ["main+long", "long+mid+spiral+core-outer"]),
    ("revD", "track", ["long", "main+long", "spiral+mid"]),
    ("revF", "track", ["long", "core+spiral"]),
]


# --------------------------------------------------------------------------- #
# ReplaySweep: the simulated acquisition (spec Deliverable 1).

class ReplaySweep(object):
    """A CASA-free stand-in for sweep.Sweep that replays an existing map's
    full point table instead of measuring.  Passed as `run_wave_loop`'s
    `sweep=` argument, so the sampler's own wave-planning/certification code
    drives the replay unmodified.

    `full_rows` is the list of raw CSV row dicts (sweep.FIELDS schema) for
    ONE (subarray, combo) results CSV -- the ground truth.  `.rows` starts
    EMPTY and is filled by `run_point`, exactly as a real Sweep's would be:

      * exact `point_key` hit -> copy the full-table row into `.rows` under
        that key, record it as a hit, return the copy.
      * miss ("unsupported request") -> record it, then pick the NEAREST
        not-yet-used full-table row in normalized (robust_to_u, taper_to_v)
        coordinates, insert a COPY of it into `.rows` under the REQUESTED key
        with weighting/robust/taper_mas rewritten to the request (flagged in
        `.fallbacks`), and return that -- so the acquisition can keep moving.
        This NEVER raises for a normal miss.

    Fallback rows are real full-table measurements physically relocated to a
    different (weighting, robust, taper) key: they let the sampler's topology
    reconstruction proceed, but they are never real evidence at the requested
    location, so callers must score from `hit_keys` only (see replay_map).

    `on_miss` (follow-up experiment, 5 Sep 2026: isolate whether the fresh
    budget or the fallback-fabrication itself blocks convergence):
      * "fallback" (default, unchanged) -- as above.
      * "fail" -- a miss instead inserts a row for the REQUESTED key with
        status="failed" (mimicking a failed tclean point, which the sampler
        already tolerates: the key is "attempted" so never re-proposed, but
        contributes no corner/stencil evidence and is never scored).  No
        donor is consulted; `.fallbacks` stays empty.
    """

    def __init__(self, full_rows, on_miss="fallback"):
        if on_miss not in ("fallback", "fail"):
            raise ValueError("on_miss must be 'fallback' or 'fail', got %r"
                             % on_miss)
        self.on_miss = on_miss
        self.full_table = PointTable(list(full_rows))
        self._subarray = next((r.get("subarray") for r in full_rows
                              if r.get("subarray")), "")
        self._by_key = {}
        for r in full_rows:
            try:
                key = point_key(r["weighting"], r["robust"], r["taper_mas"])
            except (KeyError, TypeError, ValueError):
                continue
            if (r.get("status") or "").strip() in ("ok", "capped"):
                self._by_key[key] = r          # last wins, matches PointTable

        self.rows = {}                  # sim table: run_wave_loop's source
        self.requests = []              # every point_key requested, in order
        self.hit_keys = []              # exact-hit keys (the scoring subset)
        self.unsupported = []           # miss keys ("unsupported request")
        self.fallbacks = {}             # requested key -> donor key
        self._donor_used = set()
        self.calls = 0

    @property
    def hits(self):
        return len(self.hit_keys)

    def _uv(self, weighting, robust, taper):
        """Normalized (robust_to_u, taper_to_v) coordinates for nearest-row
        search.  Natural uses the established robust=+2 proposal convention
        (adaptive.py KEY_NAT); taper=0 (the untapered seam) has no log-taper
        coordinate, so it gets a fixed sentinel v that clusters all taper=0
        candidates together (nearest search then falls back to robust
        distance among them, which is the only meaningful axis there)."""
        r = 2.0 if weighting == "natural" else float(robust)
        u = robust_to_u(r)
        taper = float(taper)
        t = self.full_table
        if taper > 0 and t.t_min and t.t_max:
            v = taper_to_v(taper, t.t_min, t.t_max)
        else:
            v = -1.0
        return u, v

    def _nearest_donor(self, weighting, robust, taper, exclude_used=True):
        uq, vq = self._uv(weighting, robust, taper)
        best_key, best_d = None, None
        for k, r in self._by_key.items():
            if exclude_used and k in self._donor_used:
                continue
            try:
                w2 = r["weighting"]
                rb2 = float(r["robust"]) if w2 == "briggs" else 2.0
                tp2 = float(r["taper_mas"])
            except (KeyError, TypeError, ValueError):
                continue
            u2, v2 = self._uv(w2, rb2, tp2)
            d = (uq - u2) ** 2 + (vq - v2) ** 2
            if best_d is None or d < best_d:
                best_d, best_key = d, k
        return best_key

    def run_point(self, weighting, robust, taper):
        self.calls += 1
        key = point_key(weighting, robust, taper)
        self.requests.append(key)
        row = self._by_key.get(key)
        if row is not None:
            copy = dict(row)
            self.rows[key] = copy
            self.hit_keys.append(key)
            return copy

        # miss: an "unsupported request" at this exact key.
        self.unsupported.append(key)

        if self.on_miss == "fail":
            # mimic a failed tclean point at the REQUESTED key: no donor, no
            # evidence, but "attempted" so it is never re-proposed -- exactly
            # sweep.run_point's existing failure contract (adaptive.py's
            # run_wave_loop already tolerates this).
            row = dict(subarray=self._subarray, weighting=weighting,
                      robust=("" if weighting == "natural"
                             else "%.2f" % float(robust)),
                      taper_mas="%.3f" % float(taper),
                      res_geo_arcsec="", sigma_dirty="", skirt="",
                      status="failed", note="REPLAY_ONMISS_FAIL")
            self.rows[key] = row
            return row

        # "fallback": keep the acquisition moving with the nearest unused
        # full-table row; if every row has already donated once, relax that
        # restriction rather than stall (a corner case on a small/sparse map,
        # never expected on a real ~230-500 row campaign map).
        donor_key = self._nearest_donor(weighting, robust, taper)
        if donor_key is None:
            donor_key = self._nearest_donor(weighting, robust, taper,
                                            exclude_used=False)
        if donor_key is None:
            return None                 # no usable full-table row at all
        self._donor_used.add(donor_key)
        donor = self._by_key[donor_key]
        fb = dict(donor)
        fb["weighting"] = weighting
        fb["robust"] = "" if weighting == "natural" else "%.2f" % float(robust)
        fb["taper_mas"] = "%.3f" % float(taper)
        fb["note"] = ((fb.get("note") or "")
                      + " REPLAY_FALLBACK<-%s" % donor_key).strip()
        self.rows[key] = fb
        self.fallbacks[key] = donor_key
        return fb


# --------------------------------------------------------------------------- #
# seed derivation (architecture finding)

def _canonical_seed_tapers(table, subarray):
    """Fresh-mode seed tapers derived from the map's OWN measured anchors,
    exactly as QuadTree's retrofit branch derives its seed grid: every-other
    of the canonical (config.grid_rows) taper lattice, with the coarsest rim
    forced in.  Because the canonical lattice is itself log-uniform, this
    also guarantees the first bisection's geometric-mean midpoints land
    exactly on the skipped canonical tapers (exact keys)."""
    rows = grid_rows(table.res_fine, table.res_nat, subarray)
    canonical = [round(float(tp), 3) for tp in rows[0][2] if tp > 0]
    seed_t = canonical[::2]
    if canonical and canonical[-1] not in seed_t:
        seed_t = seed_t + [canonical[-1]]
    return seed_t


# --------------------------------------------------------------------------- #
# scoring (spec "Scoring")

def _log_bins(lo, hi, n):
    if lo is None or hi is None or lo <= 0 or hi <= lo:
        return []
    xlo, xhi = math.log(lo), math.log(hi)
    return [math.exp(xlo + (xhi - xlo) * i / (n - 1)) for i in range(n)]


def _overlaps(a, b):
    return a[0] <= b[1] and b[0] <= a[1]


def _res_ranges(sampler, cells):
    out = []
    for cell in cells:
        cm = sampler._corner_mvecs(cell)
        rng = sampler._leaf_res_range(cell, cm)
        if rng is not None:
            out.append(rng)
    return out


def _feasible(samples, res, margin, setpoint):
    lo, hi = res * (1 - margin), res * (1 + margin)
    return any(lo <= s["res"] <= hi and s["skirt"] is not None
               and s["skirt"] <= setpoint for s in samples)


def _best_skirt(samples, res, margin):
    lo, hi = res * (1 - margin), res * (1 + margin)
    vals = [s["skirt"] for s in samples
           if s["skirt"] is not None and lo <= s["res"] <= hi]
    return min(vals) if vals else None


def _score(full_table, scoring_table, truth_sampler, scoring_sampler,
          beam_cap_mas):
    """Regret / cuts / skirt scoring on EXACT hits only (spec "Scoring"):
    `scoring_table`/`scoring_sampler` must already be built from the
    exact-hit subset (see replay_map) -- this function does not filter
    fallbacks itself."""
    full_samples = full_table.display_samples()
    subset_samples = scoring_table.display_samples()

    full_curve = build_curve(full_samples, None, max_res=beam_cap_mas)
    subset_curve = build_curve(subset_samples, None, max_res=beam_cap_mas)
    full_env = _Envelope(full_curve)
    subset_env = _Envelope(subset_curve)

    # regret split (follow-up experiment, 5 Sep 2026): "covered" = bins where
    # the SUBSET also has coverage (the honest regret number); "uncovered" =
    # bins where truth has coverage but the subset doesn't (a distinct
    # failure mode -- budget/oracle starvation, not bad interpolation).  The
    # combined pass logic is unchanged: both must be clean to pass.
    bins = _log_bins(full_env.coverage_min, full_env.coverage_max,
                     N_REGRET_BINS)
    regret_max_covered, uncovered_bins = 0.0, []
    for res in bins:
        e_full = full_env.eta_at(res)
        if e_full is None:
            continue                    # truth itself has no coverage here
        e_sub = subset_env.eta_at(res)
        if e_sub is None:
            uncovered_bins.append(res)
            continue
        regret_max_covered = max(regret_max_covered, e_sub - e_full)
    n_uncovered_bins = len(uncovered_bins)
    regret_pass = (regret_max_covered <= REGRET_TOL) and (n_uncovered_bins == 0)

    truth_steps = [c for c in truth_sampler.feature_cells() if c.feature == STEP]
    replay_steps = [c for c in scoring_sampler.feature_cells() if c.feature == STEP]
    truth_ranges = _res_ranges(truth_sampler, truth_steps)
    replay_ranges = _res_ranges(scoring_sampler, replay_steps)
    false_cuts = [r for r in replay_ranges
                 if not any(_overlaps(r, t) for t in truth_ranges)]
    missed_cuts = [t for t in truth_ranges
                  if not any(_overlaps(t, r) for r in replay_ranges)]
    cuts_pass = not false_cuts and not missed_cuts

    skirt_mistakes = []
    for res in bins:
        best_full = _best_skirt(full_samples, res, RES_MARGIN)
        if best_full is None:
            continue
        for setpoint in SKIRT_SETPOINTS:
            if best_full > setpoint or (setpoint - best_full) <= SIGMA_SKIRT:
                continue                # truth infeasible here, or borderline
            if not _feasible(subset_samples, res, RES_MARGIN, setpoint):
                skirt_mistakes.append((setpoint, res))
    skirt_pass = not skirt_mistakes

    return dict(regret_max_covered=regret_max_covered,
               n_uncovered_bins=n_uncovered_bins,
               false_cuts=len(false_cuts), missed_cuts=len(missed_cuts),
               skirt_mistakes=len(skirt_mistakes),
               regret_pass=regret_pass, cuts_pass=cuts_pass,
               skirt_pass=skirt_pass)


# --------------------------------------------------------------------------- #
# the replay driver (spec Deliverable 1)

def _read_rows(csv_path):
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def replay_map(csv_path, subarray, beam_cap_mas=None, budget=None, out=None,
              seed_tapers=None, on_miss="fallback"):
    """Replay one (subarray, combo) map's full point table as a simulated
    fresh-mode acquisition and score it against the full-table truth.
    Returns a metrics dict (see the per-map JSON schema in the module
    docstring).  Raises only for a missing/malformed CSV or a full table
    missing the two SEEDS anchors -- every "unsupported request" during the
    replay itself is handled by ReplaySweep and never raises.

    `on_miss` is forwarded to ReplaySweep -- "fallback" (default) or "fail";
    see ReplaySweep's docstring."""
    full_rows = _read_rows(csv_path)
    if not full_rows:
        raise ValueError("%s: no rows" % csv_path)
    full_table = PointTable(full_rows, subarray=subarray,
                           beam_cap_mas=beam_cap_mas)
    if not full_table.has_anchors:
        raise ValueError("%s: full table is missing the SEEDS anchors "
                         "(natural/untapered + briggs r=-2/untapered)"
                         % csv_path)

    if seed_tapers is None:
        seed_tapers = _canonical_seed_tapers(full_table, subarray)

    sweep = ReplaySweep(full_rows, on_miss=on_miss)
    buf = out if out is not None else io.StringIO()
    wave_result = run_wave_loop(subarray, sweep=sweep, mode="fresh",
                               budget=budget, beam_cap_mas=beam_cap_mas,
                               out=buf, seed_tapers=seed_tapers)
    stop_reason = wave_result["stopped"]

    # Scoring subset: EXACT hits only (fallback rows excluded from every
    # metric AND from the topology used to build them, spec "Scoring").
    hit_rows = [sweep.rows[k] for k in sweep.hit_keys]
    scoring_table = PointTable(hit_rows, subarray=subarray,
                               beam_cap_mas=beam_cap_mas)
    scoring_sampler = Sampler(subarray, table=scoring_table, mode="fresh",
                              seed_tapers=seed_tapers)
    truth_sampler = Sampler(subarray, table=full_table, mode="retrofit")

    metrics = _score(full_table, scoring_table, truth_sampler,
                     scoring_sampler, beam_cap_mas)

    # sample_fraction = share of the full table's distinct NON-capped ("ok")
    # evidence the replay actually used.  Count only hits that landed on ok
    # rows: the denominator excludes capped rows, and counting capped-row
    # hits in the numerator inflated the fraction above 1 on maps with many
    # capped rows (INVESTIGATION.md Q1, 6 Sep 2026).  n_hits still reports
    # every exact hit (ok + capped).
    n_ok_rows = full_table.n_effective - full_table.n_capped
    n_ok_hits = sum(1 for r in hit_rows
                    if (r.get("status") or "").strip() == "ok")
    sample_fraction = (n_ok_hits / n_ok_rows) if n_ok_rows else 0.0
    n_requests = len(sweep.requests)
    exact_hit_fraction = (sweep.hits / n_requests) if n_requests else 0.0

    budget_fail = (stop_reason == "audit cap reached")
    passed = (not budget_fail and metrics["regret_pass"]
             and metrics["cuts_pass"] and metrics["skirt_pass"])

    return dict(
        subarray=subarray, csv_path=csv_path, on_miss=on_miss,
        stop_reason=stop_reason, budget_fail=budget_fail,
        converged=(stop_reason == "no proposals (converged/classified)"),
        n_requests=n_requests, n_hits=sweep.hits, n_ok_hits=n_ok_hits,
        n_fallbacks=len(sweep.fallbacks), n_unsupported=len(sweep.unsupported),
        n_ok_rows=n_ok_rows,
        sample_fraction=sample_fraction, exact_hit_fraction=exact_hit_fraction,
        regret_max_covered=metrics["regret_max_covered"],
        n_uncovered_bins=metrics["n_uncovered_bins"],
        false_cuts=metrics["false_cuts"], missed_cuts=metrics["missed_cuts"],
        skirt_mistakes=metrics["skirt_mistakes"],
        regret_pass=metrics["regret_pass"], cuts_pass=metrics["cuts_pass"],
        skirt_pass=metrics["skirt_pass"],
        passed=passed,
        wave_log=buf.getvalue(),
    )


# --------------------------------------------------------------------------- #
# CLI: one map (worker mode, also usable standalone) + --suite (orchestrator)

def _resolve_beam_cap_mas(subarray):
    if subarray in BEAM_CAP_ARCSEC:
        return BEAM_CAP_ARCSEC[subarray] * 1e3
    return None


def _report_stem(rev, sim_mode, subarray):
    return "%s_%s_%s" % (rev, sim_mode, subarray.replace("+", "_"))


def run_one(subarray, out_dir=None, budget=None, on_miss="fallback"):
    """Replay the CURRENT env combo's (NGVLA_REV/NGVLA_SIM_MODE) map for
    `subarray`, print a one-line summary, and write its per-map JSON report.
    Returns the JSON report path."""
    out_dir = out_dir or DEFAULT_OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    csv_path = results_csv_path(subarray)
    beam_cap_mas = _resolve_beam_cap_mas(subarray)
    result = replay_map(csv_path, subarray, beam_cap_mas=beam_cap_mas,
                        budget=budget, on_miss=on_miss)

    stem = _report_stem(REV, SIM_MODE, subarray)
    payload = dict(result, rev=REV, sim_mode=SIM_MODE, budget=budget)
    out_path = os.path.join(out_dir, stem + ".json")
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    os.replace(tmp, out_path)

    print("%-40s sample_fraction %.3f  exact_hit %.3f  regret_cov %.3f  "
         "uncovered %d  false/missed cuts %d/%d  skirt_mistakes %d  "
         "stop=%s  %s"
         % (stem, result["sample_fraction"], result["exact_hit_fraction"],
            result["regret_max_covered"], result["n_uncovered_bins"],
            result["false_cuts"], result["missed_cuts"],
            result["skirt_mistakes"], result["stop_reason"],
            "PASS" if result["passed"] else "FAIL"))
    return out_path


def _percentile(sorted_vals, q):
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(idx)), int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    frac = idx - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


def write_report_md(report_paths, out_dir):
    rows = []
    for p in report_paths:
        with open(p) as f:
            rows.append(json.load(f))

    lines = ["# MFS-2d / V1 retrospective replay report", "",
             "Generated by `curvegen/replay_v1.py --suite` "
             "(docs/plans/mfs-v1-replay-spec.md).", "",
             "| map | sample_fraction | exact_hit_fraction | "
             "regret_max_covered | n_uncovered_bins | false_cuts | "
             "missed_cuts | skirt_mistakes | stop_reason | verdict |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    fractions = []
    for r in rows:
        stem = "%s/%s/%s" % (r["rev"], r["sim_mode"], r["subarray"])
        verdict = "PASS" if r["passed"] else "FAIL"
        lines.append("| %s | %.3f | %.3f | %.3f | %d | %d | %d | %d | %s | %s |"
                     % (stem, r["sample_fraction"], r["exact_hit_fraction"],
                        r["regret_max_covered"], r["n_uncovered_bins"],
                        r["false_cuts"], r["missed_cuts"],
                        r["skirt_mistakes"], r["stop_reason"], verdict))
        fractions.append(r["sample_fraction"])
    fractions.sort()
    p90 = _percentile(fractions, 0.90)
    all_pass = bool(rows) and all(r["passed"] for r in rows)
    acceptance = all_pass and p90 <= SAMPLE_FRACTION_P90_MAX

    lines += ["", "p90 sample_fraction: %.3f (acceptance threshold <= %.2f)"
             % (p90, SAMPLE_FRACTION_P90_MAX), "",
             "**Acceptance (ALL maps pass AND p90 sample_fraction <= %.2f): %s**"
             % (SAMPLE_FRACTION_P90_MAX, "PASS" if acceptance else "FAIL")]

    out_path = os.path.join(out_dir, "REPORT.md")
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, out_path)
    return out_path


def run_suite(out_dir=None, budget=None, timeout_s=600, on_miss="fallback"):
    """The whole fixed 10-map suite, one casapy subprocess per map (each combo
    needs its OWN NGVLA_REV/NGVLA_SIM_MODE at config.py import time, so
    per-combo isolation is via subprocess env, not in-process reimport)."""
    out_dir = out_dir or DEFAULT_OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    script = os.path.abspath(__file__)
    report_paths = []
    for rev, sim_mode, subarrays in SUITE:
        for sa in subarrays:
            env = dict(os.environ)
            env["NGVLA_REV"] = rev
            env["NGVLA_SIM_MODE"] = sim_mode
            for stray in ("NGVLA_BAND", "NGVLA_CAMPAIGN_VARIANT", "NGVLA_NCHAN"):
                env.pop(stray, None)
            cmd = [CASAPY_BIN, script, sa, "--out-dir", out_dir,
                  "--on-miss", on_miss]
            if budget is not None:
                cmd += ["--budget", str(budget)]
            t0 = time.time()
            try:
                proc = subprocess.run(cmd, cwd=REPO, env=env,
                                      capture_output=True, text=True,
                                      timeout=timeout_s)
            except subprocess.TimeoutExpired:
                raise SystemExit(
                    "replay_v1.py --suite: %s/%s/%s exceeded the %ds "
                    "per-map timeout -- stopping the suite"
                    % (rev, sim_mode, sa, timeout_s))
            elapsed = time.time() - t0
            if proc.returncode != 0:
                sys.stdout.write(proc.stdout)
                sys.stderr.write(proc.stderr)
                raise SystemExit("replay_v1.py --suite: %s/%s/%s failed "
                                 "(rc=%d)" % (rev, sim_mode, sa,
                                              proc.returncode))
            sys.stdout.write(proc.stdout)
            print("  (%.1fs)" % elapsed)
            report_paths.append(os.path.join(
                out_dir, _report_stem(rev, sim_mode, sa) + ".json"))

    report_path = write_report_md(report_paths, out_dir)
    print("wrote %s" % report_path)
    return report_paths


def main(argv=None):
    ap = argparse.ArgumentParser(description="MFS-2d / V1 retrospective "
                                 "replay harness (docs/plans/"
                                 "mfs-v1-replay-spec.md).")
    ap.add_argument("subarray", nargs="?",
                    help="replay ONE subarray's map in the CURRENT env "
                         "combo (NGVLA_REV/NGVLA_SIM_MODE); omit with "
                         "--suite")
    ap.add_argument("--suite", action="store_true",
                    help="run the fixed 10-map suite across all 4 combos "
                         "(spawns one casapy subprocess per map)")
    ap.add_argument("--out-dir", default=None,
                    help="override curvegen/reports/v1_replay")
    ap.add_argument("--budget", type=int, default=None,
                    help="override the fresh audit cap (evals; default %d)"
                         % AUDIT_FRESH)
    ap.add_argument("--on-miss", choices=("fallback", "fail"),
                    default="fallback",
                    help="unsupported-request policy (default fallback): "
                         "'fallback' relocates the nearest unused full-table "
                         "row to the requested key (today's behaviour); "
                         "'fail' records status=failed at the requested key "
                         "instead (no fabricated evidence, mimics a real "
                         "failed tclean point) -- follow-up experiment to "
                         "separate the fresh budget from the replay oracle "
                         "as the cause of non-convergence")
    args = ap.parse_args(argv)

    if args.suite:
        run_suite(out_dir=args.out_dir, budget=args.budget,
                  on_miss=args.on_miss)
        return 0
    if not args.subarray:
        ap.error("subarray is required unless --suite is given")
    if args.subarray not in SUBARRAYS:
        ap.error("unknown subarray %r for %s/%s; choices: %s"
                 % (args.subarray, REV, SIM_MODE, sorted(SUBARRAYS)))
    run_one(args.subarray, out_dir=args.out_dir, budget=args.budget,
           on_miss=args.on_miss)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
CASA-free tests for curvegen/replay_v1.py (docs/plans/mfs-v1-replay-spec.md,
the MFS-2d / V1 retrospective replay harness).

Synthetic point tables in the real sweep-result schema, built with the same
`_row`/`synth_rows`/model-function pattern as tests/test_adaptive.py, written
to a tmp dir so replay_map's csv_path argument never touches the repo's real
results/ trees.  No CASA / tclean anywhere here -- ReplaySweep replaces
measurement with table lookups by construction.

Run from the repository root:

    casapy -m unittest tests.test_replay_v1
"""

import csv
import importlib
import math
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "curvegen"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load():
    try:
        A = importlib.import_module("adaptive")
        R = importlib.import_module("replay_v1")
        from config import grid_rows
        from adaptive_support import point_key
        return A, R, grid_rows, point_key
    except ImportError as e:                       # pragma: no cover
        raise unittest.SkipTest("curvegen modules need CASA here: %s" % e)


A, R, grid_rows, point_key = _load()


# --------------------------------------------------------------------------- #
# synthetic-table helpers (same schema/pattern as tests/test_adaptive.py)

FIELDS = ["subarray", "weighting", "robust", "taper_mas", "imsize",
         "cell_arcsec", "bmaj_arcsec", "bmin_arcsec", "bpa_deg",
         "res_geo_arcsec", "sigma_dirty", "skirt", "status", "error",
         "elapsed_s", "note"]


def _row(subarray, weighting, robust, taper, res_mas, eta, skirt, status="ok"):
    return dict(subarray=subarray, weighting=weighting, robust=robust,
                taper_mas=taper,
                res_geo_arcsec=("" if res_mas is None else res_mas / 1e3),
                sigma_dirty=("" if eta is None else eta),   # sigma_nat forced 1
                skirt=("" if skirt is None else skirt),
                status=status, note="")


def synth_rows(model, subarray="core"):
    """A full CANONICAL lattice (natural row + 11 robusts x [0 + N tapers]) in
    the sweep schema -- the "existing mono map" replay_map replays.  Mirrors
    tests/test_adaptive.py's synth_rows (sigma_nat forced to 1)."""
    res_nat = model("natural", 2.0, 0.0)[0]
    res_fine = model("briggs", -2.0, 0.0)[0]
    spec = grid_rows(res_fine, res_nat, subarray)
    rows = []
    for (w, r, tapers) in spec:
        for t in tapers:
            res, eta, skirt = model(w, r, t)
            rows.append(_row(subarray, w, r, t, res, eta, skirt))
    return rows


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            full = dict.fromkeys(FIELDS, "")
            full.update(r)
            w.writerow(full)


# analytic models ----------------------------------------------------------- #

def model_smooth(w, r, t):
    """Everywhere smooth and cheap; skirt constant and well under every
    setpoint."""
    rr = 2.0 if w == "natural" else r
    return (1.0 + (rr + 2.0) / 4.0 * 0.2) * (1.0 + t) ** 0.5, 1.0 + 0.05 * t, 0.05


def model_cliff(w, r, t):
    """A genuine, known taper-onset resolution discontinuity at t*=1.0 (ported
    from tests/test_adaptive.py): below it a fine branch, at/after it the
    resolution jumps by a factor ~2 with no interior resolution -- the truth
    (retrofit) and replayed (fresh) samplers must find the SAME cut here."""
    rr = 2.0 if w == "natural" else r
    base = 1.0 + (rr + 2.0) / 4.0 * 0.3
    if t < 1.0:
        return base * (1.0 + 0.08 * t), 1.0 + 0.05 * t, 0.05
    return 2.2 * (1.0 + 0.08 * (t - 1.0)), 1.8 + 0.08 * (t - 1.0), 0.05


def model_bilinear(w, r, t):
    """Exactly affine-bilinear in (u, ln t) (ported from test_adaptive's
    model_bilinear_seed): every refined cell's residual is ~0, so -- given
    enough budget -- the replay genuinely CONVERGES ("no proposals"), rather
    than stopping only because the fresh audit cap ran out.  Used as the
    positive control that "no proposals" is reachable at all."""
    u = 0.5 if w == "natural" else (r + 2.0) / 4.0
    lt = math.log(t) if t > 0 else math.log(1e-3)
    lnres = 0.5 + 0.1 * u + 0.15 * lt + 0.02 * u * lt
    eta = 1.0 + 0.05 * u + 0.03 * lt + 0.01 * u * lt
    return math.exp(lnres), max(eta, 1.0 + 1e-6), 0.05


class FakeSampler(object):
    """A cut-free stand-in for adaptive.Sampler: `_score` only calls
    `feature_cells()` (for STEP cells) and, on any cells it returns,
    `_corner_mvecs`/`_leaf_res_range` -- an empty feature_cells() means those
    are never invoked, isolating the regret/skirt logic in TestScoreToy from
    the sampler/quadtree machinery entirely."""

    def feature_cells(self):
        return []


# --------------------------------------------------------------------------- #
# 1. seed_tapers default-preserving (architecture finding)

class TestSeedTapersDefaultUnchanged(unittest.TestCase):

    def _anchor_table(self):
        rows = [_row("core", "natural", 2.0, 0.0, 1.30, 1.0, 0.05),
                _row("core", "briggs", -2.0, 0.0, 1.00, 1.02, 0.05)]
        return A.PointTable(rows, subarray="core")

    def test_omitted_and_explicit_none_match_log_uniform_seed(self):
        table = self._anchor_table()
        expected = [round(A.v_to_taper(k / (A.N_SEED_TAPERS - 1),
                                       table.t_min, table.t_max), 3)
                   for k in range(A.N_SEED_TAPERS)]
        omitted = A.QuadTree(table, mode="fresh")
        explicit_none = A.QuadTree(table, mode="fresh", seed_tapers=None)
        self.assertEqual(omitted.seed_tapers, expected)
        self.assertEqual(explicit_none.seed_tapers, expected)
        self.assertEqual(omitted.seed_robusts, explicit_none.seed_robusts)

    def test_override_replaces_log_uniform_seed_without_touching_robusts(self):
        table = self._anchor_table()
        override = [0.5, 1.0, 2.0, 4.0]
        tree = A.QuadTree(table, mode="fresh", seed_tapers=override)
        self.assertEqual(tree.seed_tapers, override)
        self.assertEqual(tree.seed_robusts, A.SEED_ROBUSTS)   # unaffected

    def test_manifest_is_not_a_function_of_seed_tapers(self):
        before = A.manifest()
        A.QuadTree(A.PointTable([], subarray="core"), mode="fresh",
                  seed_tapers=[1.0, 2.0, 3.0])
        after = A.manifest()
        self.assertEqual(before, after)

    def test_retrofit_mode_ignores_the_override(self):
        # the override only changes fresh-mode seeding (spec: "fresh mode
        # uses it instead"); retrofit derives its own dyadic grid regardless.
        rows = synth_rows(model_smooth, "core")
        table = A.PointTable(rows, subarray="core")
        with_override = A.QuadTree(table, mode="retrofit",
                                   seed_tapers=[1.0, 2.0])
        without = A.QuadTree(table, mode="retrofit")
        self.assertEqual(with_override.seed_tapers, without.seed_tapers)


# --------------------------------------------------------------------------- #
# 2. ReplaySweep: the V1 oracle (exact hit / unsupported request / fallback)

class TestReplaySweep(unittest.TestCase):

    def setUp(self):
        self.rows = synth_rows(model_smooth, "core")

    def test_exact_hit_copies_full_row_and_is_never_a_fallback(self):
        sweep = R.ReplaySweep(self.rows)
        row = sweep.run_point("briggs", -2.0, 0.0)
        self.assertEqual(row["status"], "ok")
        self.assertEqual(sweep.hits, 1)
        self.assertEqual(sweep.unsupported, [])
        self.assertEqual(sweep.fallbacks, {})
        self.assertIn(point_key("briggs", -2.0, 0.0), sweep.hit_keys)

    def test_miss_never_raises_and_flags_a_fallback(self):
        sweep = R.ReplaySweep(self.rows)
        key = point_key("briggs", 0.13, 0.777)          # off the lattice
        row = sweep.run_point("briggs", 0.13, 0.777)
        self.assertIsNotNone(row)
        self.assertIn(key, sweep.unsupported)
        self.assertIn(key, sweep.fallbacks)
        self.assertEqual(row["weighting"], "briggs")
        self.assertAlmostEqual(float(row["robust"]), 0.13, places=2)
        self.assertAlmostEqual(float(row["taper_mas"]), 0.777, places=3)
        self.assertEqual(sweep.hits, 0)
        self.assertNotIn(key, sweep.hit_keys)

    def test_requests_hits_fallbacks_are_tracked(self):
        sweep = R.ReplaySweep(self.rows)
        sweep.run_point("briggs", -2.0, 0.0)             # hit
        sweep.run_point("natural", 2.0, 0.0)             # hit
        sweep.run_point("briggs", 0.13, 0.777)           # miss -> fallback
        self.assertEqual(len(sweep.requests), 3)
        self.assertEqual(sweep.hits, 2)
        self.assertEqual(len(sweep.fallbacks), 1)
        self.assertEqual(len(sweep.unsupported), 1)

    def test_fallback_donors_are_not_reused(self):
        # two off-lattice requests close enough together to share a nearest
        # full-table row -- the SECOND must get a different donor.
        sweep = R.ReplaySweep(self.rows)
        k1 = point_key("briggs", 0.131, 0.501)
        k2 = point_key("briggs", 0.132, 0.502)
        sweep.run_point("briggs", 0.131, 0.501)
        sweep.run_point("briggs", 0.132, 0.502)
        self.assertNotEqual(sweep.fallbacks[k1], sweep.fallbacks[k2])

    def test_on_miss_fail_records_a_failed_row_with_no_fallback(self):
        # follow-up experiment (5 Sep 2026): on_miss="fail" mimics a real
        # failed tclean point at the REQUESTED key instead of relocating a
        # donor -- never a fallback, never a hit, but still "attempted" (the
        # sampler's existing failed-point contract).
        sweep = R.ReplaySweep(self.rows, on_miss="fail")
        key = point_key("briggs", 0.13, 0.777)           # off the lattice
        row = sweep.run_point("briggs", 0.13, 0.777)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["weighting"], "briggs")
        self.assertAlmostEqual(float(row["robust"]), 0.13, places=2)
        self.assertAlmostEqual(float(row["taper_mas"]), 0.777, places=3)
        self.assertIn(key, sweep.unsupported)
        self.assertEqual(sweep.fallbacks, {})            # no donor consulted
        self.assertEqual(sweep.hits, 0)
        self.assertNotIn(key, sweep.hit_keys)
        self.assertIn(key, sweep.rows)                   # "attempted"

    def test_on_miss_fail_key_is_attempted_and_never_reproposed(self):
        # a "failed" key must occupy the table (PointTable.present) exactly
        # like a real failed sweep row, so run_wave_loop never re-requests it.
        sweep = R.ReplaySweep(self.rows, on_miss="fail")
        sweep.run_point("briggs", 0.13, 0.777)
        table = A.PointTable(list(sweep.rows.values()), subarray="core")
        key = point_key("briggs", 0.13, 0.777)
        self.assertTrue(table.present(key))
        self.assertFalse(table.hit(key))

    def test_default_on_miss_is_fallback(self):
        self.assertEqual(R.ReplaySweep(self.rows).on_miss, "fallback")

    def test_invalid_on_miss_rejected(self):
        with self.assertRaises(ValueError):
            R.ReplaySweep(self.rows, on_miss="bogus")


# --------------------------------------------------------------------------- #
# 3. _score in isolation: a toy table with a known coverage gap

class TestScoreToy(unittest.TestCase):

    def test_regret_and_skirt_flag_a_real_coverage_gap(self):
        full_rows = synth_rows(model_smooth, "core")
        full_table = A.PointTable(full_rows, subarray="core")

        # subset: only the coarsest THIRD of each row's taper levels is
        # dropped -- a genuine resolution-coverage gap at the coarse end (not
        # a missing branch: every robust and natural stays represented).
        tapers = sorted({round(float(r["taper_mas"]), 3) for r in full_rows
                        if r["weighting"] == "briggs" and float(r["taper_mas"]) > 0})
        cutoff = tapers[2 * len(tapers) // 3]
        subset_rows = [r for r in full_rows if float(r["taper_mas"]) <= cutoff]
        scoring_table = A.PointTable(subset_rows, subarray="core")

        metrics = R._score(full_table, scoring_table, FakeSampler(),
                          FakeSampler(), None)

        self.assertGreater(metrics["n_uncovered_bins"], 0)
        self.assertGreater(metrics["skirt_mistakes"], 0)
        self.assertFalse(metrics["regret_pass"])
        self.assertFalse(metrics["skirt_pass"])
        self.assertTrue(metrics["cuts_pass"])      # vacuous: no cells offered

    def test_identical_subset_has_zero_regret_and_no_skirt_mistakes(self):
        full_rows = synth_rows(model_smooth, "core")
        full_table = A.PointTable(full_rows, subarray="core")
        scoring_table = A.PointTable(list(full_rows), subarray="core")

        metrics = R._score(full_table, scoring_table, FakeSampler(),
                          FakeSampler(), None)

        self.assertEqual(metrics["n_uncovered_bins"], 0)
        self.assertAlmostEqual(metrics["regret_max_covered"], 0.0, places=9)
        self.assertEqual(metrics["skirt_mistakes"], 0)
        self.assertTrue(metrics["regret_pass"])
        self.assertTrue(metrics["skirt_pass"])


# --------------------------------------------------------------------------- #
# 4. replay_map end to end (tmp CSVs, never the repo's real results/ trees)

class TestReplayMapToy(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="replay_v1_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def _write(self, model, subarray="core"):
        rows = synth_rows(model, subarray)
        path = os.path.join(self.tmpdir, subarray.replace("+", "_") + ".csv")
        write_csv(path, rows)
        return path, rows

    def test_bilinear_map_genuinely_converges_given_enough_budget(self):
        # positive control: convergence ("no proposals") IS reachable, not
        # only budget exhaustion -- a purely bilinear map's residual is ~0
        # everywhere, so the sampler certifies rather than perpetually
        # discovering fabricated fallback "structure".
        path, _rows = self._write(model_bilinear)
        result = R.replay_map(path, "core", budget=400)
        self.assertEqual(result["stop_reason"], "no proposals (converged/classified)")
        self.assertFalse(result["budget_fail"])
        self.assertEqual(result["false_cuts"], 0)
        self.assertEqual(result["missed_cuts"], 0)
        self.assertTrue(result["cuts_pass"])
        self.assertLessEqual(result["regret_max_covered"], R.REGRET_TOL)
        self.assertTrue(result["skirt_pass"])

    def test_known_cliff_is_found_by_both_truth_and_replay(self):
        path, _rows = self._write(model_cliff)
        result = R.replay_map(path, "core")
        self.assertEqual(result["false_cuts"], 0)
        self.assertEqual(result["missed_cuts"], 0)
        self.assertTrue(result["cuts_pass"])

    def test_on_miss_fail_end_to_end_never_fabricates_fallbacks(self):
        # follow-up experiment: replay_map(on_miss="fail") must run to
        # completion (never raise), record zero fallbacks, and still exclude
        # every unsupported request from the scoring subset.
        path, _rows = self._write(model_smooth)
        result = R.replay_map(path, "core", on_miss="fail")
        self.assertEqual(result["on_miss"], "fail")
        self.assertEqual(result["n_fallbacks"], 0)
        self.assertGreaterEqual(result["n_unsupported"], 0)
        self.assertEqual(result["n_hits"] + result["n_unsupported"],
                         result["n_requests"])

    def test_sample_fraction_counts_only_ok_row_hits(self):
        # INVESTIGATION.md Q1 (6 Sep 2026): hits on capped rows must not be
        # counted against a denominator that excludes capped rows, otherwise
        # sample_fraction can exceed 1.  Mark every coarse-taper row capped.
        rows = synth_rows(model_smooth, "core")
        tapers = sorted({float(r["taper_mas"]) for r in rows})
        cut = tapers[len(tapers) // 2]
        for r in rows:
            if float(r["taper_mas"]) >= cut:
                r["status"] = "capped"
        path = os.path.join(self.tmpdir, "capped_core.csv")
        write_csv(path, rows)
        result = R.replay_map(path, "core", on_miss="fail")
        n_ok = sum(1 for r in rows if r["status"] == "ok")
        self.assertEqual(result["n_ok_rows"], n_ok)
        self.assertLessEqual(result["n_ok_hits"], result["n_hits"])
        self.assertLessEqual(result["sample_fraction"], 1.0)
        self.assertAlmostEqual(result["sample_fraction"],
                               result["n_ok_hits"] / n_ok)

    def test_metrics_exclude_fallback_rows(self):
        rows = synth_rows(model_smooth, "core")
        full_table = A.PointTable(rows, subarray="core")
        seed_tapers = R._canonical_seed_tapers(full_table, "core")

        # a fresh-mode seed vertex (SEED_ROBUSTS[1], seed_tapers[2]) -- drop
        # it so the wave-0 request for it MUST become a fallback.
        target_robust, target_taper = A.SEED_ROBUSTS[1], seed_tapers[2]
        victim = next(r for r in rows if r["weighting"] == "briggs"
                     and abs(float(r["robust"]) - target_robust) < 1e-9
                     and abs(float(r["taper_mas"]) - target_taper) < 1e-9)
        victim_key = point_key("briggs", target_robust, target_taper)
        rows_missing = [r for r in rows if r is not victim]

        sweep = R.ReplaySweep(rows_missing)
        import io
        A.run_wave_loop("core", sweep=sweep, mode="fresh", out=io.StringIO(),
                        seed_tapers=seed_tapers)

        self.assertIn(victim_key, sweep.requests, "test setup: victim must "
                     "actually be requested by wave 0's seed grid")
        self.assertIn(victim_key, sweep.fallbacks)
        self.assertNotIn(victim_key, sweep.hit_keys)

        scoring_keys = {point_key(r["weighting"], r["robust"], r["taper_mas"])
                       for r in (sweep.rows[k] for k in sweep.hit_keys)}
        self.assertNotIn(victim_key, scoring_keys)

    def test_result_has_the_documented_metric_keys(self):
        path, _rows = self._write(model_smooth)
        result = R.replay_map(path, "core")
        for key in ("subarray", "stop_reason", "budget_fail", "n_requests",
                   "n_hits", "n_fallbacks", "n_unsupported", "n_ok_rows",
                   "sample_fraction", "exact_hit_fraction", "regret_max_covered",
                   "n_uncovered_bins", "false_cuts", "missed_cuts",
                   "skirt_mistakes", "regret_pass", "cuts_pass", "skirt_pass",
                   "passed", "wave_log"):
            self.assertIn(key, result)
        self.assertGreaterEqual(result["sample_fraction"], 0.0)
        self.assertLessEqual(result["exact_hit_fraction"], 1.0)


if __name__ == "__main__":
    unittest.main()

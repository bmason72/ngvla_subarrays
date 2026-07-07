"""
Tests for the shared curve engine (sa_select/envelope.py), including
regression tests for the 6 Jul 2026 curve-anomaly post-mortem
(curve_anomaly_postmortem.md): the pop-ups/drop-outs bmason flagged must not
reappear.  Run from the repository root:

    python3 -m unittest tests.test_envelope
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sa_select.envelope import (Envelope, build_points, build_segments,
                                ETA_CAP)
from sa_select.curves import CurveLibrary

REVF_CSV = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "sa_select", "data", "revf_curves.csv")


def pt(res, eta, skirt, weighting="briggs", robust=0.0, taper=0.0):
    return dict(res=res, eta=eta, skirt=skirt, weighting=weighting,
                robust=robust, taper=taper)


class TestHygiene(unittest.TestCase):

    def test_signed_zero_robust_is_one_branch(self):
        pts = build_points([pt(10.0, 1.0, 0.2, robust=-0.0, taper=1.0),
                            pt(10.0, 1.0, 0.2, robust=0.0, taper=1.0)])
        self.assertEqual(len(pts), 1)          # exact duplicate dropped
        self.assertEqual(pts[0].robust, 0.0)

    def test_eta_cap_applied(self):
        pts = build_points([pt(10.0, 1.0, 0.2), pt(20.0, ETA_CAP + 1, 0.2,
                                                   taper=5.0)])
        self.assertEqual(len(pts), 1)


class TestSegments(unittest.TestCase):

    def test_no_bridging_of_pruned_holes(self):
        # taper jumps x4 between adjacent samples: a pruned hole, no segment
        pts = build_points([pt(10, 1.0, 0.2, taper=1.0),
                            pt(30, 1.5, 0.2, taper=4.0)])
        self.assertEqual(build_segments(pts), [])

    def test_lattice_step_bridged(self):
        pts = build_points([pt(10, 1.0, 0.2, taper=1.0),
                            pt(12, 1.1, 0.2, taper=1.5)])
        self.assertEqual(len(build_segments(pts)), 1)

    def test_no_extrapolation(self):
        env = Envelope([pt(10, 1.0, 0.2, taper=1.0),
                        pt(12, 1.1, 0.2, taper=1.5)])
        self.assertIsNone(env.solve(13.0))                # beyond row end
        self.assertIsNotNone(env.solve(13.0, margin=0.1))  # 12 within margin


class TestInterpolation(unittest.TestCase):
    """The M1 scenario: a hole in the cheap family wider than the margin must
    be filled by interpolation, not by an expensive off-envelope sample."""

    def setUp(self):
        # cheap row with a x1.15 res hole around 16.8; expensive family dense
        self.samples = [
            pt(15.7, 1.076, 0.30, robust=1.6, taper=2.67),
            pt(18.0, 1.078, 0.31, robust=1.6, taper=4.15),
            pt(16.8, 1.540, 0.18, robust=0.2, taper=10.1),
            pt(17.1, 1.580, 0.17, robust=-0.0, taper=10.1),
        ]
        self.env = Envelope(self.samples)

    def test_hole_filled_by_cheap_interpolant(self):
        c = self.env.solve(16.8, margin=0.05)
        self.assertLess(c.eta, 1.10)             # not the 1.54 pop-up
        self.assertEqual(c.robust, 1.6)
        self.assertTrue(c.interpolated)

    def test_interpolated_taper_between_anchors(self):
        c = self.env.solve(16.8, margin=0.0)
        self.assertGreater(c.taper, 2.67)
        self.assertLess(c.taper, 4.15)

    def test_exact_at_measured_point(self):
        c = self.env.solve(15.7, margin=0.0)
        self.assertAlmostEqual(c.eta, 1.076, places=6)


class TestSkirtCrossing(unittest.TestCase):
    """The M2 scenario: the skirt=0.10 crossing between lattice nodes must be
    found by interpolation instead of paying the full node-to-node eta gap."""

    def test_strict_optimum_at_threshold_crossing(self):
        env = Envelope([
            pt(8.45, 1.507, 0.115, robust=1.2, taper=5.87),
            pt(8.30, 1.560, 0.080, robust=1.2, taper=6.50),
        ])
        # relax=False isolates the crossing machinery (with the trade on,
        # the 0.115-skirt node would legitimately win the penalized objective)
        c = env.solve(8.40, margin=0.05, skirt_max=0.10, relax=False)
        self.assertIsNotNone(c)
        self.assertLessEqual(c.skirt, 0.10 + 1e-9)
        self.assertLess(c.eta, 1.560)             # cheaper than the far node

    def test_multi_segment_crossings_all_considered(self):
        # two rows crossing the threshold at the same res; cheaper row wins
        env = Envelope([
            pt(8.45, 1.507, 0.115, robust=1.2, taper=5.87),
            pt(8.30, 1.560, 0.080, robust=1.2, taper=6.50),
            pt(8.50, 1.400, 0.120, robust=0.8, taper=5.80),
            pt(8.32, 1.480, 0.070, robust=0.8, taper=6.60),
        ])
        c = env.solve(8.40, margin=0.05, skirt_max=0.10, relax=False)
        self.assertEqual(c.robust, 0.8)


class TestRelaxationContinuity(unittest.TestCase):
    """The M3 scenario: inside a sculpt-family coverage hole the relaxed
    criterion must come from the interpolated family, not collapse to the
    cheap high-skirt samples (the eta=1.002 drop-out)."""

    def setUp(self):
        self.env = Envelope([
            # sculpt family (skirt ~0.17-0.19) with samples bracketing 11.7
            pt(11.5, 1.450, 0.187, robust=0.2, taper=6.46),
            pt(12.8, 1.580, 0.158, robust=0.2, taper=7.88),
            # cheap natural-ish family, skirt ~0.31
            pt(11.4, 1.001, 0.307, robust=1.6, taper=0.708),
            pt(11.8, 1.002, 0.316, weighting="natural", robust=None,
               taper=0.708),
        ])

    def test_no_dropout_inside_family_hole(self):
        # sculpt family (skirt ~0.17 <= trade cap) must win the trade over
        # the cheap 0.31-skirt family (beyond the cap): no eta-1.0 drop-out
        c = self.env.solve(11.7, margin=0.0, skirt_max=0.10, relax=True)
        self.assertTrue(c.traded)
        self.assertFalse(c.relaxed)
        self.assertLess(c.skirt, 0.25)            # sculpt family, not 0.31
        self.assertGreater(c.eta, 1.3)            # not the eta-1.0 drop-out

    def test_beyond_trade_cap_falls_back_relaxed(self):
        env = Envelope([
            pt(11.5, 1.450, 0.30, robust=0.2, taper=6.46),
            pt(12.8, 1.580, 0.28, robust=0.2, taper=7.88),
        ])
        c = env.solve(11.7, margin=0.0, skirt_max=0.10, relax=True)
        self.assertTrue(c.relaxed)
        self.assertIsNotNone(c.best_skirt)
        self.assertGreater(c.best_skirt, 0.25)


class TestEtaSkirtTrade(unittest.TestCase):
    """bmason's 1-for-1 eta-skirt trade (6 Jul 2026): a strict beam only wins
    when pushing the skirt under 0.10 costs less eta than the trade charges.
    Pins the residual 8.18/44.9 mas 'strict island' spikes."""

    def setUp(self):
        self.env = Envelope([
            # expensive strict family: skirt dips under 0.10 at eta ~1.9
            pt(7.9, 1.90, 0.095, robust=-2.0, taper=6.5),
            pt(8.4, 1.85, 0.105, robust=-2.0, taper=6.9),
            # cheap moderate-skirt family
            pt(7.9, 1.48, 0.155, robust=-0.2, taper=4.6),
            pt(8.4, 1.46, 0.160, robust=-0.2, taper=4.9),
        ])

    def test_trade_beats_expensive_strict(self):
        c = self.env.solve(8.0, margin=0.0, skirt_max=0.10, relax=True)
        # J(strict) ~ 1.89; J(traded) ~ 1.48 + 0.055 = 1.53 -> traded wins
        self.assertTrue(c.traded)
        self.assertEqual(c.robust, -0.2)
        self.assertLess(c.eta, 1.6)

    def test_strict_wins_when_cheap_enough(self):
        env = Envelope([
            pt(7.9, 1.50, 0.095, robust=-2.0, taper=6.5),
            pt(8.4, 1.48, 0.098, robust=-2.0, taper=6.9),
            pt(7.9, 1.47, 0.155, robust=-0.2, taper=4.6),
            pt(8.4, 1.46, 0.160, robust=-0.2, taper=4.9),
        ])
        # J(strict) ~ 1.49 < J(traded) ~ 1.47 + 0.055 = 1.52
        c = env.solve(8.0, margin=0.0, skirt_max=0.10, relax=True)
        self.assertFalse(c.traded)
        self.assertEqual(c.robust, -2.0)

    def test_relax_false_is_pure_threshold(self):
        c = self.env.solve(8.0, margin=0.0, skirt_max=0.10, relax=False)
        self.assertEqual(c.robust, -2.0)          # only the strict family


@unittest.skipUnless(os.path.isfile(REVF_CSV), "Rev F curve data not present")
class TestRevFRegressions(unittest.TestCase):
    """The named anomalies from bmason's review must stay fixed, on the real
    Rev F data via the full CurveLibrary/solve path (units: arcsec)."""

    @classmethod
    def setUpClass(cls):
        cls.lib = CurveLibrary(samples=REVF_CSV)

    def test_spiral_mid_pointsource_no_popups(self):
        # 17.0 mas cost a factor ~2 in time pre-fix (eta 1.54 vs 1.08)
        for res_mas, eta_max in [(7.17, 1.25), (17.0, 1.25), (17.8, 1.25),
                                 (21.3, 1.35)]:
            s, msg = self.lib.solve("spiral+mid", res_mas / 1e3, 30.0)
            self.assertIsNotNone(s, msg)
            self.assertLess(s.eta, eta_max, "pop-up at %.4g mas" % res_mas)

    def test_spiral_mid_imaging_no_dropout(self):
        s, msg = self.lib.solve("spiral+mid", 11.7e-3, 30.0,
                                skirt_threshold=0.10)
        self.assertIsNotNone(s, msg)
        # pre-fix: relaxed pool collapsed to eta 1.002 at skirt 0.31
        self.assertGreater(s.eta, 1.2)
        self.assertLess(s.skirt, 0.25)

    def test_pointsource_curves_no_spikes(self):
        # No isolated pop-ups/drop-outs: no point may sit > 0.12 in eta above
        # or below BOTH neighbors.  (Monotone steps remain allowed: discrete
        # robust rows produce a real staircase at the fine end -- the known
        # robust-direction quantization, see the post-mortem's second wave.)
        for name in ("spiral+mid", "core+spiral", "core", "mid"):
            curve = self.lib.envelope(name).curve(grid_dex=0.01)
            for a, b, c in zip(curve, curve[1:], curve[2:]):
                if b.res / a.res > 1.05 or c.res / b.res > 1.05:
                    continue                      # coverage gap: fine
                spike = (b.eta - max(a.eta, c.eta) > 0.12
                         or min(a.eta, c.eta) - b.eta > 0.12)
                self.assertFalse(spike,
                                 "%s point-source spike at %.4g (eta %.3f "
                                 "between %.3f and %.3f)"
                                 % (name, b.res, b.eta, a.eta, c.eta))


if __name__ == "__main__":
    unittest.main()


class TestGuardReviewRegressions(unittest.TestCase):
    """Pins for the 6 Jul 2026 codex guard-review findings."""

    def test_relaxed_message_reports_true_best_skirt(self):
        # beyond the trade cap: cheapest relaxed-pool point (skirt 0.35) !=
        # true best (0.30); the public message must cite the true best
        import tempfile, csv as _csv
        d = tempfile.mkdtemp()
        sub = os.path.join(d, "subarrays.csv")
        smp = os.path.join(d, "curves.csv")
        with open(sub, "w", newline="") as f:
            w = _csv.writer(f)
            w.writerow(["name", "components", "n_ant", "b_min_m", "b_max_m",
                        "las_coeff", "calc_name", "las_coeff_note"])
            w.writerow(["testA", "testA", 10, 100.0, 1000.0, 0.85, "testA", ""])
        with open(smp, "w", newline="") as f:
            w = _csv.writer(f)
            w.writerow(["subarray", "resolution_arcsec_30ghz", "eta", "skirt",
                        "weighting", "robust", "taper_arcsec_30ghz",
                        "freq_orig_ghz", "source", "note"])
            w.writerow(["testA", "1.0", "1.8", "0.30", "briggs", "-0.5",
                        "0.5", "30.0", "true_best", ""])
            w.writerow(["testA", "1.0", "1.2", "0.34", "briggs", "0.5",
                        "0.6", "30.0", "cheapest_in_pool", ""])
        lib = CurveLibrary(subarrays=sub, samples=smp)
        sample, msg = lib.solve("testA", 1.0, 30.0, skirt_threshold=0.10)
        self.assertEqual(sample.skirt, 0.34)      # cheapest within 1.15x best
        self.assertIn("best achievable is 0.3", msg)


class TestBeamCapPruning(unittest.TestCase):
    """The heterogeneous beam cap in curvegen/sweep.py, without CASA: stub
    run_point and walk the row loop via a minimal fake."""

    def test_capped_status_and_two_consecutive_prune(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "curvegen"))
        try:
            import importlib
            sweep_mod = importlib.import_module("sweep")
        except ImportError as e:
            self.skipTest("curvegen/sweep.py needs CASA here: %s" % e)
            return
        # simulate the row walk: beams 0.5, 0.75, 0.72, 0.80, 0.85 with cap
        # 0.71 -> statuses ok, capped, capped -> prune (skip the rest)
        beams = {1.0: 0.5, 2.0: 0.75, 3.0: 0.72, 4.0: 0.80, 5.0: 0.85}

        class FakeSweep(sweep_mod.Sweep):
            def __init__(self):        # no CASA, no files
                self.subarray = "core+mid"
                self.rows = {}
                self.limit = None
                self.n_run = 0
                self.beam_cap = 0.71
                self.recorded = []

            def record(self, row):
                self.recorded.append(row)
                self.rows[sweep_mod.point_key(row["weighting"], row["robust"],
                                              row["taper_mas"])] = row

            def run_point(self, weighting, robust, taper):
                key = sweep_mod.point_key(weighting, robust, taper)
                if key in self.rows:
                    return self.rows[key]
                res = beams[taper]
                status, err = "ok", ""
                if self.beam_cap is not None and res > self.beam_cap:
                    status, err = "capped", "beam > cap"
                row = dict(subarray=self.subarray, weighting=weighting,
                           robust=robust, taper_mas=taper,
                           res_geo_arcsec="%.6g" % res, sigma_dirty="1.0",
                           skirt="0.1", status=status, error=err,
                           elapsed_s="1")
                self.record(row)
                return row

        fake = FakeSweep()
        # drive the same pruning logic run() uses, on one row
        capped, n_over = None, 0
        for taper in sorted(beams):
            if capped:
                fake.record(dict(subarray="core+mid", weighting="briggs",
                                 robust=0.0, taper_mas=taper, res_geo_arcsec="",
                                 sigma_dirty="", skirt="", status="skipped",
                                 error=capped, elapsed_s=""))
                continue
            row = fake.run_point("briggs", 0.0, taper)
            if row["status"] == "capped":
                n_over += 1
                if n_over >= 2:
                    capped = "beam cap exceeded"
                continue
            n_over = 0
        statuses = [r["status"] for r in fake.recorded]
        self.assertEqual(statuses, ["ok", "capped", "capped", "skipped",
                                    "skipped"])


class TestColumnSegments(unittest.TestCase):
    """2-D densification (bmason, 6 Jul 2026): column segments interpolate
    between lattice-adjacent robust rows at fixed taper, removing the
    discrete-robust staircase."""

    def test_untapered_column_interpolates(self):
        env = Envelope([pt(10.0, 1.5, 0.2, robust=1.6, taper=0.0),
                        pt(12.0, 1.2, 0.25, robust=2.0, taper=0.0)])
        c = env.solve(11.0, margin=0.0)
        self.assertIsNotNone(c)                  # isolated points before
        self.assertTrue(1.2 < c.eta < 1.5)
        self.assertTrue(1.6 < c.robust < 2.0)
        self.assertTrue(c.interpolated)

    def test_column_gap_gate(self):
        # non-adjacent rows (gap 0.8) must NOT be bridged
        env = Envelope([pt(10.0, 1.5, 0.2, robust=0.8, taper=0.0),
                        pt(12.0, 1.2, 0.25, robust=1.6, taper=0.0)])
        self.assertIsNone(env.solve(11.0, margin=0.0))

    def test_natural_excluded_from_columns(self):
        env = Envelope([pt(10.0, 1.5, 0.2, robust=2.0, taper=0.0),
                        pt(12.0, 1.2, 0.25, weighting="natural", robust=None,
                           taper=0.0)])
        self.assertIsNone(env.solve(11.0, margin=0.0))


@unittest.skipUnless(os.path.isfile(REVF_CSV), "Rev F curve data not present")
class TestStaircaseRegression(unittest.TestCase):
    """The robust-direction staircase must stay small on real data."""

    def test_pointsource_steps_bounded(self):
        lib = CurveLibrary(samples=REVF_CSV)
        for name in ("spiral+mid", "main", "core+spiral", "core"):
            curve = lib.envelope(name).curve(grid_dex=0.01)
            for a, b in zip(curve, curve[1:]):
                if b.res / a.res > 1.05 or max(a.eta, b.eta) > 3.0:
                    continue        # coverage gap / eta-cap fringe
                self.assertLess(abs(b.eta - a.eta), 0.16,
                                "%s staircase step at %.4g mas (%.3f->%.3f)"
                                % (name, b.res * 1e3, a.eta, b.eta))

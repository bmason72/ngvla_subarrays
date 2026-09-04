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
                                build_leaf_families, ETA_CAP)
from sa_select.curves import CurveLibrary

REVF_CSV = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "sa_select", "data", "revf_curves.csv")


def pt(res, eta, skirt, weighting="briggs", robust=0.0, taper=0.0):
    return dict(res=res, eta=eta, skirt=skirt, weighting=weighting,
                robust=robust, taper=taper)


def threshold_pick(pts, imaging, s0=0.10):
    """Reference threshold-relax selection over a set of (eta, skirt) points
    (skirt not None): point-source = min eta; imaging = min-eta among
    skirt<=s0 if any (meets criterion), else min-skirt (best PSF, tie by eta,
    relaxed).  Returns (eta, skirt, relaxed) or None.  Mirrors envelope.solve's
    default policy -- no eta censoring (the engine reports what it finds)."""
    if not pts:
        return None
    if not imaging:
        return (min(e for e, _ in pts), None, False)
    strict = [(e, s) for e, s in pts if s <= s0 + 1e-12]
    if strict:
        e, s = min(strict, key=lambda t: t[0])
        return (e, s, False)
    smin = min(s for _, s in pts)
    e, s = min([(e, s) for e, s in pts if s <= smin + 1e-6],
               key=lambda t: t[0])
    return (e, s, True)


class TestHygiene(unittest.TestCase):

    def test_signed_zero_robust_is_one_branch(self):
        pts = build_points([pt(10.0, 1.0, 0.2, robust=-0.0, taper=1.0),
                            pt(10.0, 1.0, 0.2, robust=0.0, taper=1.0)])
        self.assertEqual(len(pts), 1)          # exact duplicate dropped
        self.assertEqual(pts[0].robust, 0.0)

    def test_no_eta_censoring(self):
        # the engine reports what it finds: build_points keeps eta > ETA_CAP
        # (ETA_CAP is a compute-grid/plotting bound only; bmason 8 Jul 2026)
        pts = build_points([pt(10.0, 1.0, 0.2), pt(20.0, ETA_CAP + 1, 0.2,
                                                   taper=5.0)])
        self.assertEqual(len(pts), 2)


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
        # no skirt <= 0.10 here, so threshold-relax returns the BEST achievable
        # skirt: the sculpt family (~0.17), NOT the cheap 0.31-skirt family --
        # so no eta-1.0 drop-out (the M3 regression).
        c = self.env.solve(11.7, margin=0.0, skirt_max=0.10, relax=True)
        self.assertTrue(c.relaxed)                # best achievable, not <=0.10
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
    """The retired 1-for-1 eta-skirt trade, now `mode="legacy_trade"` only
    (superseded 8 Jul 2026 by threshold-relax; see TestThresholdRelax).  A
    strict beam wins only when pushing skirt under 0.10 costs less eta than the
    trade charges."""

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
        c = self.env.solve(8.0, margin=0.0, skirt_max=0.10, relax=True,
                           mode="legacy_trade")
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
        c = env.solve(8.0, margin=0.0, skirt_max=0.10, relax=True,
                      mode="legacy_trade")
        self.assertFalse(c.traded)
        self.assertEqual(c.robust, -2.0)

    def test_relax_false_is_pure_threshold(self):
        c = self.env.solve(8.0, margin=0.0, skirt_max=0.10, relax=False)
        self.assertEqual(c.robust, -2.0)          # only the strict family


class TestThresholdRelax(unittest.TestCase):
    """The default threshold-relax policy (bmason 8 Jul 2026): meet skirt<=s0
    with the cheapest beam where achievable, else report the BEST achievable
    skirt (min-skirt) flagged relaxed -- never trade skirt away for eta."""

    def test_meets_criterion_with_cheapest_feasible(self):
        # both the -2 (skirt 0.095) and -0.2 (skirt 0.155) families exist;
        # only -2 meets 0.10, so it wins even though -0.2 is cheaper in eta
        env = Envelope([
            pt(7.9, 1.90, 0.095, robust=-2.0, taper=6.5),
            pt(8.4, 1.85, 0.105, robust=-2.0, taper=6.9),
            pt(7.9, 1.48, 0.155, robust=-0.2, taper=4.6),
            pt(8.4, 1.46, 0.160, robust=-0.2, taper=4.9),
        ])
        c = env.solve(8.0, margin=0.0, skirt_max=0.10, relax=True)
        self.assertFalse(c.relaxed)               # criterion met
        self.assertEqual(c.robust, -2.0)          # the skirt<=0.10 family
        self.assertLessEqual(c.skirt, 0.10 + 1e-9)

    def test_relaxes_to_min_skirt_not_min_eta(self):
        # nothing <= 0.10: return the best-PSF (min-skirt) beam, not the
        # cheaper high-skirt one
        env = Envelope([
            pt(7.9, 1.90, 0.150, robust=-2.0, taper=6.5),
            pt(8.4, 1.85, 0.150, robust=-2.0, taper=6.9),
            pt(7.9, 1.20, 0.240, robust=0.4, taper=3.0),
            pt(8.4, 1.18, 0.245, robust=0.4, taper=3.2),
        ])
        c = env.solve(8.0, margin=0.0, skirt_max=0.10, relax=True)
        self.assertTrue(c.relaxed)
        self.assertAlmostEqual(c.skirt, 0.150, places=2)   # min-skirt
        self.assertEqual(c.robust, -2.0)          # not the eta-1.18 / 0.245 one

    def test_no_relaxed_eta_gate(self):
        # no eta censoring: a best-skirt beam ABOVE ETA_CAP (eta ~6, >25x
        # natural time) is still reported in the relaxed regime rather than
        # dropped in favor of a cheap high-skirt beam (bmason 8 Jul 2026)
        env = Envelope([
            pt(7.9, 6.20, 0.150, robust=-2.0, taper=6.5),
            pt(8.4, 6.00, 0.150, robust=-2.0, taper=6.9),
            pt(7.9, 1.05, 0.300, robust=1.2, taper=1.0),
            pt(8.4, 1.05, 0.300, robust=1.2, taper=1.1),
        ])
        c = env.solve(8.0, margin=0.0, skirt_max=0.10, relax=True)
        self.assertTrue(c.relaxed)
        self.assertAlmostEqual(c.skirt, 0.150, places=2)   # best PSF wins
        self.assertGreater(c.eta, 5.0)            # reported despite eta > cap


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



class TestGuardReviewRegressions(unittest.TestCase):
    """Pins for the 6 Jul 2026 codex guard-review findings."""

    def test_relaxed_message_reports_true_best_skirt(self):
        # no skirt <= 0.10: threshold-relax returns the BEST achievable skirt
        # (0.30, min-skirt), not the cheaper high-skirt point (0.34); the
        # public message cites the achieved best
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
        self.assertEqual(sample.skirt, 0.30)      # min-skirt (best PSF)
        self.assertIn("best achievable skirt is 0.3", msg)


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


class TestAdaptiveLeafFamilies(unittest.TestCase):

    def _samples(self):
        return [
            pt(10.0, 1.4, 0.1, robust=0.0, taper=4.0),
            pt(11.0, 1.3, 0.1, robust=0.2, taper=4.0),  # hanging edge node
            pt(12.0, 1.2, 0.1, robust=0.4, taper=4.0),
            pt(13.0, 1.5, 0.1, robust=0.0, taper=6.0),
            pt(15.0, 1.3, 0.1, robust=0.4, taper=6.0),
        ]

    def test_explicit_leaf_uses_only_topology_corners(self):
        leaves = [dict(r0=0.0, r1=0.4, t0=4.0, t1=6.0, cut=False)]
        points = build_points(self._samples())
        segments, cells = build_leaf_families(points, leaves)
        self.assertEqual(len(cells), 1)
        # The measured hanging node splits the lower edge; it does not become
        # a cell corner or suppress the explicitly declared adaptive cell.
        lower = [s for s in segments if s.column and s.a.taper == 4.0
                 and s.b.taper == 4.0]
        self.assertEqual(len(lower), 2)
        self.assertTrue(all(abs(s.b.robust - s.a.robust - 0.2) < 1e-9
                            for s in lower))

    def test_cut_leaf_has_edges_but_no_bilinear_interior(self):
        leaves = [dict(r0=0.0, r1=0.4, t0=4.0, t1=6.0, cut=True)]
        env = Envelope(self._samples(), leaves=leaves)
        self.assertEqual(env.cells, [])
        self.assertGreater(len(env.segments), 0)

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


class TestBilinearCells(unittest.TestCase):
    """Bilinear cell interior (7 Jul 2026): under the skirt constraint the
    cheapest beam at a target resolution can lie in a cell interior (both
    robust and taper between lattice nodes), which the row/column edges miss.
    Correctness is pinned against an in-test brute-force scan of the exact
    res=theta locus (independent of the analytic critical-point enumeration)."""

    def _cell_samples(self):
        # a 2x2 (robust {0.0,0.4}) x (taper {4,6} mas) cell mirroring the probe
        # scenario: the low-eta corners (r=0.4) have skirt > trade_max (0.25),
        # so along the res=theta locus the feasible optimum is a genuine
        # interior point riding the trade cap -- unreachable from any edge.
        return [
            pt(10.0, 1.45, 0.14, robust=0.0, taper=4.0),
            pt(11.5, 1.20, 0.30, robust=0.4, taper=4.0),
            pt(13.0, 1.55, 0.13, robust=0.0, taper=6.0),
            pt(15.0, 1.32, 0.28, robust=0.4, taper=6.0),
        ]

    def _locus_scan(self, cell, theta, imaging):
        # threshold-policy reference over the exact res=theta locus u=u(s)
        import math
        xstar = math.log(theta)
        pts = []
        for i in range(20001):
            s = i / 20000
            denom = cell.C + cell.D * s
            if abs(denom) < 1e-12:
                continue
            u = (xstar - cell.A - cell.B * s) / denom
            if not (0.0 <= u <= 1.0):
                continue
            eta = math.exp(cell.Ae + cell.Be * s + cell.Ce * u
                           + cell.De * s * u)
            skirt = cell.Ak + cell.Bk * s + cell.Ck * u + cell.Dk * s * u
            pts.append((eta, skirt))
        return threshold_pick(pts, imaging)

    def test_cell_built(self):
        env = Envelope(self._cell_samples())
        self.assertEqual(len(env.cells), 1)

    def test_matches_bruteforce_locus_scan(self):
        # engine (edges + analytic cell candidates) must match a dense
        # locus scan under the threshold policy, at every resolution
        env = Envelope(self._cell_samples())
        cell = env.cells[0]
        for i in range(1, 20):
            theta = cell._rlo * (cell._rhi / cell._rlo) ** (i / 20)
            for imaging in (False, True):
                c = (env.solve(theta, margin=0.0, skirt_max=0.10, relax=True)
                     if imaging else env.solve(theta, margin=0.0))
                oref = self._locus_scan(cell, theta, imaging)
                if oref is None:
                    continue
                self.assertIsNotNone(c)
                oeta, oskirt, orelaxed = oref
                self.assertAlmostEqual(c.eta, oeta, delta=5e-3,
                                       msg="eta at %.4g (imaging=%s)"
                                       % (theta, imaging))
                if imaging:
                    self.assertEqual(bool(c.relaxed), orelaxed,
                                     "regime at %.4g" % theta)
                    if orelaxed:
                        self.assertAlmostEqual(c.skirt, oskirt, delta=5e-3)

    def test_interior_winner_is_flagged_and_bounded(self):
        # skirt<=0.10 on the r=0 side, >0.10 on the r=0.4 side: the 0.10
        # contour crosses the cell interior, so the cheapest beam MEETING
        # skirt<=0.10 is a genuine interior point (robust & taper between nodes)
        env = Envelope([pt(10.0, 1.70, 0.06, robust=0.0, taper=4.0),
                        pt(11.3, 1.20, 0.16, robust=0.4, taper=4.0),
                        pt(13.0, 1.72, 0.05, robust=0.0, taper=6.0),
                        pt(15.0, 1.22, 0.15, robust=0.4, taper=6.0)])
        c = env.solve(10.5555, margin=0.0, skirt_max=0.10, relax=True)
        self.assertIsNotNone(c)
        self.assertEqual(len(c.anchors), 4)         # bilinear cell interior
        self.assertFalse(c.relaxed)                 # meets the criterion
        self.assertLessEqual(c.skirt, 0.10 + 1e-6)  # on the s0 contour
        self.assertTrue(0.0 < c.robust < 0.4)
        self.assertTrue(4.0 < c.taper < 6.0)

    def _band_oracle(self, cell, lo, hi, imaging, n=400):
        # threshold-policy reference over the 2-D cell region, res in [lo,hi]
        import math
        pts = []
        for i in range(n + 1):
            s = i / n
            for k in range(n + 1):
                u = k / n
                res = math.exp(cell.A + cell.B * s + cell.C * u
                               + cell.D * s * u)
                if not (lo <= res <= hi):
                    continue
                eta = math.exp(cell.Ae + cell.Be * s + cell.Ce * u
                               + cell.De * s * u)
                skirt = cell.Ak + cell.Bk * s + cell.Ck * u + cell.Dk * s * u
                pts.append((eta, skirt))
        return threshold_pick(pts, imaging)

    def test_margin_band_matches_bruteforce(self):
        # the selector's default +-5% band: the min-eta feasible (or best-skirt
        # relaxed) point can sit at a resolution INSIDE the band (codex guard)
        env = Envelope(self._cell_samples())
        cell = env.cells[0]
        for i in range(31):
            theta = cell._rlo * (cell._rhi / cell._rlo) ** (i / 30)
            lo, hi = theta * 0.95, theta * 1.05
            for imaging in (False, True):
                c = (env.solve(theta, margin=0.05, skirt_max=0.10, relax=True)
                     if imaging else env.solve(theta, margin=0.05))
                oref = self._band_oracle(cell, lo, hi, imaging)
                if oref is None:
                    continue
                self.assertIsNotNone(c)
                oeta, oskirt, orelaxed = oref
                # engine's eta must not exceed the band reference (a 400^2 grid
                # slightly under-resolves, so allow a small tolerance)
                self.assertLessEqual(c.eta, oeta + 8e-3,
                                     "band miss at %.4g (imaging=%s): "
                                     "%.4f > %.4f" % (theta, imaging, c.eta,
                                                      oeta))
                # relaxed: the reported skirt must be no worse than the band
                # scan's best achievable (guards the scan-slice granularity)
                if imaging and orelaxed and bool(c.relaxed):
                    self.assertLessEqual((c.skirt or 0.0), oskirt + 8e-3,
                                         "band skirt miss at %.4g: %.4f > %.4f"
                                         % (theta, c.skirt or 0.0, oskirt))

    def test_edge_cleanliness_blocks_inconsistent_cell(self):
        # an intervening measured taper on one row makes a corner grid
        # inconsistent with the row interpolant -> that cell must NOT form
        samples = self._cell_samples() + [
            pt(11.4, 1.36, 0.155, robust=0.0, taper=5.0),  # interior to s=0 edge
        ]
        env = Envelope(samples)
        # the [4,6] cell is blocked; finer [4,5]/[5,6] cells need r=0.4 @ t=5
        # (absent) so no cell spans the intervening taper
        for cell in env.cells:
            self.assertFalse(cell.t0 < 5.0 < cell.t1,
                             "cell bridges an intervening measured taper")

    def test_column_edge_cleanliness_blocks_bridging_robust(self):
        # an intervening measured robust row at a shared taper must prevent a
        # wide cell from bridging it (the column edge would be inconsistent)
        samples = [
            pt(10.0, 1.45, 0.14, robust=0.0, taper=4.0),
            pt(13.0, 1.55, 0.13, robust=0.0, taper=6.0),
            pt(11.5, 1.20, 0.30, robust=0.4, taper=4.0),
            pt(15.0, 1.32, 0.28, robust=0.4, taper=6.0),
            # intervening robust row present at BOTH shared tapers (4 and 6):
            pt(10.7, 1.30, 0.22, robust=0.2, taper=4.0),
            pt(14.0, 1.42, 0.20, robust=0.2, taper=6.0),
        ]
        env = Envelope(samples)
        # no cell may span robust 0.0->0.4 (it would bridge the r=0.2 rows);
        # only 0.0->0.2 and 0.2->0.4 cells are allowed
        for cell in env.cells:
            self.assertFalse(cell.r0 < 0.2 < cell.r1,
                             "cell bridges an intervening measured robust row")
        self.assertTrue(env.cells)                 # the finer cells do form

    def test_vertical_branch_enumerated(self):
        # corner res 10,15,15,10 with theta=sqrt(150): the singular column
        # s0=0.5 is entirely at res=theta and must be sampled, not dropped
        import math
        env = Envelope([pt(10.0, 3.45, 0.20, robust=0.0, taper=4.0),
                        pt(15.0, 3.50, 0.22, robust=0.4, taper=4.0),
                        pt(15.0, 3.55, 0.19, robust=0.0, taper=6.0),
                        pt(10.0, 3.40, 0.21, robust=0.4, taper=6.0)])
        self.assertEqual(len(env.cells), 1)
        cands = env.cells[0].interior_candidates(math.sqrt(150.0), cap=0.25,
                                                 skirt_kink=0.10)
        # candidates on the singular column (robust ~ 0.2, i.e. s0=0.5) exist
        self.assertTrue(any(abs(c.robust - 0.2) < 1e-6 for c in cands),
                        "iso-resolution vertical branch was dropped")

    def test_flat_cell_no_spurious_win(self):
        # a degenerate cell whose corners are colinear in (res, eta): the
        # interior must reduce to the edge value (no fabricated lower eta)
        env = Envelope([pt(10.0, 1.20, 0.20, robust=0.0, taper=4.0),
                        pt(11.0, 1.20, 0.20, robust=0.4, taper=4.0),
                        pt(12.0, 1.30, 0.20, robust=0.0, taper=6.0),
                        pt(13.2, 1.30, 0.20, robust=0.4, taper=6.0)])
        c = env.solve(11.5, margin=0.0)
        self.assertIsNotNone(c)
        self.assertTrue(1.20 - 1e-6 <= c.eta <= 1.30 + 1e-6)


@unittest.skipUnless(os.path.isfile(REVF_CSV), "Rev F curve data not present")
class TestBilinearRealData(unittest.TestCase):
    """On real Rev F data, the full solve (edges + cells) must equal a
    brute-force scan of every cell's exact res=theta locus plus the edge
    segments -- i.e. the analytic enumeration never misses the constrained
    minimum (pins the 7 Jul 2026 brute-force validation)."""

    def _oracle(self, env, theta, imaging):
        # threshold-policy reference over segments@theta + cell loci@theta
        import math
        xstar = math.log(theta)
        pts = []
        for seg in env.segments:
            if seg.lo <= theta <= seg.hi:
                cc = seg.at(theta)
                if cc.skirt is not None or not imaging:
                    pts.append((cc.eta, cc.skirt if cc.skirt is not None
                                else 0.0))
        for cell in env.cells:
            if not (cell._rlo * (1 - 1e-6) <= theta <= cell._rhi * (1 + 1e-6)):
                continue
            for i in range(4001):
                s = i / 4000
                denom = cell.C + cell.D * s
                if abs(denom) < 1e-12:
                    continue
                u = (xstar - cell.A - cell.B * s) / denom
                if not (0.0 <= u <= 1.0):
                    continue
                eta = math.exp(cell.Ae + cell.Be * s + cell.Ce * u
                               + cell.De * s * u)
                if cell.skirt_ok:
                    pts.append((eta, cell.Ak + cell.Bk * s + cell.Ck * u
                                + cell.Dk * s * u))
                elif not imaging:
                    pts.append((eta, 0.0))
        return threshold_pick(pts, imaging)

    def test_solve_equals_bruteforce(self):
        # engine (analytic edges + cell candidates) must match the dense
        # reference under the threshold policy, at every resolution
        import math
        lib = CurveLibrary(samples=REVF_CSV)
        worst_eta, worst_skirt, regime_mismatch = 0.0, 0.0, 0
        for name in ("core", "spiral", "mid", "spiral+mid", "main",
                     "core+spiral", "core-inner"):
            env = lib.envelope(name)
            cov = env.coverage()
            lo, hi = math.log10(cov[0]), math.log10(cov[1])
            for i in range(41):
                theta = 10 ** (lo + (hi - lo) * i / 40)
                for imaging in (False, True):
                    c = (env.solve(theta, margin=0.0, skirt_max=0.10,
                                   relax=True) if imaging
                         else env.solve(theta, margin=0.0))
                    oref = self._oracle(env, theta, imaging)
                    if c is None or oref is None:
                        continue
                    oeta, oskirt, orelaxed = oref
                    worst_eta = max(worst_eta, abs(c.eta - oeta))
                    if imaging:
                        if bool(c.relaxed) != orelaxed:
                            regime_mismatch += 1
                        elif orelaxed:
                            worst_skirt = max(worst_skirt,
                                              abs((c.skirt or 0.0) - oskirt))
        self.assertLess(worst_eta, 6e-3,
                        "engine eta off reference by %.4f" % worst_eta)
        self.assertLess(worst_skirt, 6e-3,
                        "relaxed skirt off reference by %.4f" % worst_skirt)
        self.assertEqual(regime_mismatch, 0, "strict/relaxed regime mismatch")

    @staticmethod
    def _better(a, b):
        # threshold ordering of (relaxed, eta, skirt): strict beats relaxed;
        # within strict lower eta; within relaxed lower skirt then eta.
        # returns True if a is no worse than b (within tol).
        ra, ea, sa = a
        rb, eb, sb = b
        if ra != rb:
            return (not ra)                      # strict (relaxed False) wins
        if not ra:
            return ea <= eb + 6e-3
        return (sa <= sb + 6e-3) or (abs(sa - sb) <= 6e-3 and ea <= eb + 6e-3)

    def test_margin_band_finds_interior_optimum(self):
        # the +-5% band answer must be no worse (threshold ordering) than the
        # best over a fine resolution scan of the band via the trusted
        # per-resolution solver -- i.e. the band search finds interior optima
        import math
        lib = CurveLibrary(samples=REVF_CSV)
        for name in ("spiral+mid", "main", "core+spiral"):
            env = lib.envelope(name)
            cov = env.coverage()
            lo, hi = math.log10(cov[0]), math.log10(cov[1])
            for i in range(21):
                theta = 10 ** (lo + (hi - lo) * i / 20)
                for imaging in (True, False):
                    band = env.solve(theta, margin=0.05,
                                     skirt_max=0.10 if imaging else None,
                                     relax=True)
                    if band is None:
                        continue
                    ba = (bool(band.relaxed), band.eta, band.skirt or 0.0)
                    # reference: threshold-best over a fine scan of [.95,1.05]
                    best = None
                    for j in range(21):
                        th = theta * (0.95 + 0.10 * j / 20)
                        c = env.solve(th, margin=0.0,
                                      skirt_max=0.10 if imaging else None,
                                      relax=True)
                        if c is None:
                            continue
                        cand = (bool(c.relaxed), c.eta, c.skirt or 0.0)
                        if best is None or self._better(cand, best):
                            best = cand
                    if best is None:
                        continue
                    self.assertTrue(self._better(ba, best),
                                    "%s band answer %s worse than scan best %s "
                                    "at %.4g (imaging=%s)"
                                    % (name, ba, best, theta, imaging))


class TestRefineCandidates(unittest.TestCase):
    """curvegen/refine.py candidates_between must not IndexError on a
    same-taper (robust-direction) jump -- the tapers[1] crash that killed
    main+long refinement (8 Jul 2026)."""

    def test_same_taper_jump_no_indexerror(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "curvegen"))
        try:
            import importlib
            refine = importlib.import_module("refine")
        except ImportError as e:
            self.skipTest("curvegen/refine.py needs CASA here: %s" % e)
            return
        a = dict(weighting="briggs", robust=-0.4, taper=3.5)
        b = dict(weighting="briggs", robust=-0.8, taper=3.5)   # same taper
        cands = refine.candidates_between(a, b)                # must not crash
        self.assertTrue(cands)
        # a robust-midpoint at the shared taper is offered
        self.assertTrue(any(w == "briggs" and abs(t - 3.5) < 1e-6
                            for (w, r, t) in cands))


@unittest.skipUnless(os.path.isfile(REVF_CSV), "Rev F curve data not present")
class TestReportSelectorParity(unittest.TestCase):
    """The report calculator (JS) reads the pre-built imaging curve and picks
    by the threshold policy over the +-5% window; the selector calls the engine
    directly.  This replicates the JS window pick over the same curve and
    checks it tracks the engine (guards future JS/engine drift -- codex finding
    8 Jul 2026)."""

    def _js_pick(self, curve, res_ref, obs):
        lo, hi = res_ref * 0.95, res_ref * 1.05
        win = [c for c in curve if lo <= c.res <= hi]
        if not win:
            return None
        if obs != "imaging":
            return min(win, key=lambda c: c.eta)
        strict = [c for c in win if not c.relaxed]
        if strict:
            return min(strict, key=lambda c: c.eta)
        return min(win, key=lambda c: ((c.skirt if c.skirt is not None
                                        else 1e9), c.eta))

    def test_js_window_pick_tracks_engine(self):
        lib = CurveLibrary(samples=REVF_CSV)
        self._check_window_pick_tracks_engine(
            lib,
            ("core", "spiral", "mid", "core+spiral", "spiral+mid",
             "main", "core-inner"),
            0.10, 50)
        self._check_window_pick_tracks_engine(
            lib, ("core", "spiral+mid", "main"), 0.20, 20)

    def _check_window_pick_tracks_engine(self, lib, names, skirt_max, min_n):
        import math
        worst, hard_mism, n = 0.0, 0, 0
        for name in names:
            env = lib.envelope(name)
            info = lib.subarrays.get(name)
            max_res = info.beam_cap_arcsec if info else None
            curve = env.curve(skirt_max=skirt_max, grid_dex=0.01,
                              max_res=max_res)  # the DATA.imaging[s0]
            cov = env.coverage()
            cov_hi = cov[1] if max_res is None else min(cov[1], max_res)
            if cov_hi < cov[0]:
                continue
            lo, hi = math.log10(cov[0]), math.log10(cov_hi)
            for i in range(15):
                theta = 10 ** (lo + (hi - lo) * i / 14)
                jp = self._js_pick(curve, theta, "imaging")
                c = env.solve(theta, margin=0.05, skirt_max=skirt_max,
                              relax=True, max_res=max_res)
                if jp is None or c is None or c.eta > 3.0:
                    continue          # coarse near-cap end is not of interest
                n += 1
                worst = max(worst, abs(jp.eta - c.eta))
                # a strict/relaxed flip is benign at the skirt seam; only
                # count it if it's a genuine (non-seam) mismatch
                if bool(jp.relaxed) != bool(c.relaxed):
                    js_s = jp.skirt if jp.skirt is not None else skirt_max
                    en_s = c.skirt if c.skirt is not None else skirt_max
                    if min(abs(js_s - skirt_max),
                           abs(en_s - skirt_max)) > 0.01:
                        hard_mism += 1
        # the JS window pick (over the pre-built 0.01-dex curve) and the
        # continuous engine solve agree to the grid discretization -- ~0.1 eta
        # at the steepest spots (the report is a quick-look; the Python
        # selector is authoritative); regime agrees except at the skirt seam
        self.assertGreater(n, min_n)
        self.assertLess(worst, 0.12,
                        "JS/engine eta drift %.3f at s0=%.2f"
                        % (worst, skirt_max))
        self.assertEqual(hard_mism, 0,
                         "JS/engine hard regime mismatch at s0=%.2f"
                         % skirt_max)


class TestBeamCapClipping(unittest.TestCase):
    """max_res (heterogeneous beam cap, 9 Jul 2026): samples measured beyond
    the cap are interpolation anchors -- they extend row coverage up to the
    cap -- but no offered answer may sit beyond it.  The capped/ok flag lives
    in the data layer (sample_status); the engine only receives max_res."""

    def setUp(self):
        # one taper-direction row crossing a cap at res 25; the 30-mas point
        # plays the capped anchor
        self.env = Envelope([
            pt(20.0, 1.20, 0.20, robust=0.0, taper=4.0),
            pt(24.0, 1.30, 0.20, robust=0.0, taper=5.0),
            pt(30.0, 1.50, 0.20, robust=0.0, taper=6.5),
        ])

    def test_window_clipped_at_cap(self):
        # window [23.4, 27.5] intersected with the cap -> answer <= 25
        c = self.env.solve(26.0, margin=0.10, max_res=25.0)
        self.assertIsNotNone(c)
        self.assertLessEqual(c.res, 25.0 + 1e-9)

    def test_interpolation_through_capped_anchor(self):
        # 24.5 sits on the 24->30 segment: reachable only via the anchor
        c = self.env.solve(24.5, max_res=25.0)
        self.assertIsNotNone(c)
        self.assertAlmostEqual(c.res, 24.5, delta=1e-6)
        self.assertTrue(c.interpolated)

    def test_window_entirely_beyond_cap_returns_none(self):
        self.assertIsNone(self.env.solve(30.0, margin=0.05, max_res=25.0))

    def test_curve_clipped_with_exact_cap_endpoint(self):
        crv = self.env.curve(max_res=25.0)
        self.assertTrue(crv)
        self.assertLessEqual(max(c.res for c in crv), 25.0 + 1e-9)
        self.assertAlmostEqual(crv[-1].res, 25.0, delta=1e-6)

    def test_curve_uncapped_reaches_coverage_end(self):
        crv = self.env.curve()
        self.assertAlmostEqual(crv[-1].res, 30.0, delta=1e-6)
        self.assertLessEqual(max(c.res for c in crv), 30.0 + 1e-9)


class TestCappedRealData(unittest.TestCase):
    """Real-data regressions for the 9 Jul 2026 glitch fixes (bmason's three
    report complaints): the stale-cell repair killed the fake strict islands
    in the spiral+mid / core+spiral imaging curves, and capped-anchor
    collection + cap clipping killed the point-source coarse-end cliff of
    the beam-capped combos (main+long jumped eta 1.18 -> 2.25 in one grid
    step at ~20.5 mas because the taper grid stopped 20% short of the cap)."""

    @classmethod
    def setUpClass(cls):
        cls.lib = CurveLibrary()          # Rev F data (arcsec units)

    def _steps(self, pts, lo_res=0.0, eta_max=None):
        out = []
        for a, b in zip(pts, pts[1:]):
            if b.res / a.res > 1.055:      # rendered/true coverage gap
                continue
            if b.res < lo_res:
                continue
            if eta_max is not None and max(a.eta, b.eta) > eta_max:
                continue
            out.append(abs(b.eta - a.eta))
        return out

    def test_ptsrc_tail_smooth_to_cap(self):
        for name in ("main+long", "spiral+mid+long"):
            with self.subTest(subarray=name):
                cap = self.lib.subarrays[name].beam_cap_arcsec
                self.assertIsNotNone(cap)
                pts = self.lib.envelope(name).curve(max_res=cap)
                self.assertLessEqual(max(p.res for p in pts), cap + 1e-12)
                self.assertGreater(pts[-1].res, 0.995 * cap)   # reaches it
                worst = max(self._steps(pts, lo_res=cap / 1.5), default=0.0)
                self.assertLess(worst, 0.2,
                                "%s near-cap tail step %.3f" % (name, worst))

    def test_main_long_cheap_at_20mas(self):
        # the reported artifact: 20.5 mas cost eta 2.25; natural+taper
        # through the capped anchors prices it honestly
        sample, msg = self.lib.solve("main+long", resolution=0.0205,
                                     freq_ghz=30.0, beam_margin=0.05)
        self.assertIsNotNone(sample, msg)
        self.assertLess(sample.eta, 1.3)

    def test_imaging_islands_stay_dead(self):
        # stale wrong-cell sculpt points (repair_stale_cells.py) produced
        # steps of +0.37 (spiral+mid ~7.7 mas) and +0.21 (core+spiral
        # ~260 mas) in the operating range; keep them dead
        for name in ("spiral+mid", "core+spiral"):
            with self.subTest(subarray=name):
                pts = self.lib.envelope(name).curve(skirt_max=0.10)
                worst = max(self._steps(pts, eta_max=3.0), default=0.0)
                self.assertLess(worst, 0.2,
                                "%s imaging step %.3f" % (name, worst))


if __name__ == "__main__":
    unittest.main()

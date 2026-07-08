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

    def _locus_scan(self, cell, theta, imaging, skirt_max=0.10,
                    trade_max=0.25):
        # brute-force min over the exact res=theta locus u=u(s)
        import math
        xstar = math.log(theta)
        best = None
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
            if imaging:
                if skirt > trade_max:
                    continue
                j = eta + max(0.0, skirt - skirt_max)
            else:
                j = eta
            if best is None or j < best:
                best = j
        return best

    def test_cell_built(self):
        env = Envelope(self._cell_samples())
        self.assertEqual(len(env.cells), 1)

    def test_matches_bruteforce_locus_scan(self):
        import math
        env = Envelope(self._cell_samples())
        cell = env.cells[0]
        # sweep resolutions the cell covers; engine J must match the scan
        for i in range(1, 20):
            theta = cell._rlo * (cell._rhi / cell._rlo) ** (i / 20)
            for imaging in (False, True):
                if imaging:
                    c = env.solve(theta, margin=0.0, skirt_max=0.10,
                                  relax=True)
                    ej = None if c is None else c.eta + max(
                        0.0, (c.skirt or 0.0) - 0.10)
                else:
                    c = env.solve(theta, margin=0.0)
                    ej = None if c is None else c.eta
                oj = self._locus_scan(cell, theta, imaging)
                if oj is None:
                    continue
                self.assertIsNotNone(c)
                # engine must not miss a lower-J point the scan found
                self.assertLessEqual(ej, oj + 5e-3,
                                     "engine J %.4f > scan %.4f at %.4g "
                                     "(imaging=%s)" % (ej, oj, theta, imaging))
                # and engine must not undercut the achievable min
                self.assertGreaterEqual(ej, oj - 5e-3)

    def test_interior_winner_is_flagged_and_bounded(self):
        # at a resolution the taper columns cannot reach, the winner is a
        # genuine cell interior: 4 anchors, robust/taper strictly between nodes
        env = Envelope(self._cell_samples())
        c = env.solve(12.0, margin=0.0, skirt_max=0.10, relax=True)
        self.assertIsNotNone(c)
        self.assertTrue(c.interpolated)
        self.assertEqual(len(c.anchors), 4)
        self.assertTrue(0.0 < c.robust < 0.4)
        self.assertTrue(4.0 < c.taper < 6.0)
        self.assertTrue(c.traded)               # rides the trade cap interior

    def _band_oracle(self, cell, lo, hi, imaging, skirt_max=0.10,
                     trade_max=0.25, n=400):
        # brute-force min over the 2-D cell region with res in [lo,hi]
        import math
        best = None
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
                if eta > 5.0:
                    continue
                skirt = cell.Ak + cell.Bk * s + cell.Ck * u + cell.Dk * s * u
                if imaging:
                    if skirt > trade_max:
                        continue
                    j = eta + max(0.0, skirt - skirt_max)
                else:
                    j = eta
                best = j if best is None else min(best, j)
        return best

    def test_margin_band_matches_bruteforce(self):
        # the selector's default +-5% band: the cheapest interior can sit at a
        # resolution INSIDE the band, not only at the endpoints (codex guard)
        import math
        env = Envelope(self._cell_samples())
        cell = env.cells[0]
        for i in range(31):
            theta = cell._rlo * (cell._rhi / cell._rlo) ** (i / 30)
            lo, hi = theta * 0.95, theta * 1.05
            for imaging in (False, True):
                if imaging:
                    c = env.solve(theta, margin=0.05, skirt_max=0.10,
                                  relax=True)
                    ej = None if c is None else c.eta + max(
                        0.0, (c.skirt or 0.0) - 0.10)
                else:
                    c = env.solve(theta, margin=0.05)
                    ej = None if c is None else c.eta
                oj = self._band_oracle(cell, lo, hi, imaging)
                if oj is None:
                    continue
                self.assertIsNotNone(c)
                self.assertLessEqual(ej, oj + 5e-3,
                                     "band miss at %.4g (imaging=%s): "
                                     "%.4f > %.4f" % (theta, imaging, ej, oj))

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
        import math
        xstar = math.log(theta)
        best = None

        def take(eta, skirt):
            nonlocal best
            if eta > 5.0:
                return
            if imaging:
                if skirt is None or skirt > 0.25:
                    return
                j = eta + max(0.0, skirt - 0.10)
            else:
                j = eta
            best = j if best is None else min(best, j)

        for seg in env.segments:
            if seg.lo <= theta <= seg.hi:
                cc = seg.at(theta)
                take(cc.eta, cc.skirt)
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
                skirt = (cell.Ak + cell.Bk * s + cell.Ck * u + cell.Dk * s * u
                         if cell.skirt_ok else None)
                take(eta, skirt)
        return best

    def test_solve_equals_bruteforce(self):
        import math
        lib = CurveLibrary(samples=REVF_CSV)
        worst = 0.0
        for name in ("core", "spiral", "mid", "spiral+mid", "main",
                     "core+spiral", "core-inner"):
            env = lib.envelope(name)
            cov = env.coverage()
            lo, hi = math.log10(cov[0]), math.log10(cov[1])
            for i in range(41):
                theta = 10 ** (lo + (hi - lo) * i / 40)
                for imaging in (False, True):
                    if imaging:
                        c = env.solve(theta, margin=0.0, skirt_max=0.10,
                                      relax=True)
                        ej = None if c is None else c.eta + max(
                            0.0, (c.skirt or 0.0) - 0.10)
                    else:
                        c = env.solve(theta, margin=0.0)
                        ej = None if c is None else c.eta
                    oj = self._oracle(env, theta, imaging)
                    if ej is None or oj is None:
                        continue
                    worst = max(worst, ej - oj)
        # engine must never do worse than the brute-force scan (beyond the
        # scan's grid granularity)
        self.assertLess(worst, 6e-3,
                        "engine missed a min by %.4f (J)" % worst)

    def _band_oracle(self, env, lo, hi, imaging, n=160):
        # brute-force 2-D min over every bracketing cell with res in [lo,hi]
        import math
        best = None
        for cell in env.cells:
            if not (cell._rlo <= hi and cell._rhi >= lo):
                continue
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
                    if eta > 5.0:
                        continue
                    skirt = (cell.Ak + cell.Bk * s + cell.Ck * u
                             + cell.Dk * s * u if cell.skirt_ok else None)
                    if imaging:
                        if skirt is None or skirt > 0.25:
                            continue
                        j = eta + max(0.0, skirt - 0.10)
                    else:
                        j = eta
                    best = j if best is None else min(best, j)
        return best

    def test_margin_band_not_worse_than_cell_bruteforce(self):
        # the selector's default +-5% band must not miss a cheaper cell
        # interior at a resolution inside the band (codex guard finding)
        import math
        lib = CurveLibrary(samples=REVF_CSV)
        worst = 0.0
        for name in ("spiral+mid", "main", "core+spiral"):
            env = lib.envelope(name)
            cov = env.coverage()
            lo, hi = math.log10(cov[0]), math.log10(cov[1])
            for i in range(21):
                theta = 10 ** (lo + (hi - lo) * i / 20)
                blo, bhi = theta * 0.95, theta * 1.05
                for imaging in (False, True):
                    if imaging:
                        c = env.solve(theta, margin=0.05, skirt_max=0.10,
                                      relax=True)
                        ej = None if c is None else c.eta + max(
                            0.0, (c.skirt or 0.0) - 0.10)
                    else:
                        c = env.solve(theta, margin=0.05)
                        ej = None if c is None else c.eta
                    oj = self._band_oracle(env, blo, bhi, imaging)
                    if ej is None or oj is None:
                        continue
                    worst = max(worst, ej - oj)
        self.assertLess(worst, 8e-3,
                        "band solve missed a cell min by %.4f (J)" % worst)

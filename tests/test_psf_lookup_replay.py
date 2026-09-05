"""Python replay of the report's `nearestPsfKey` ranking.

This re-implements, in Python, the parameter-space nearest-PSF ranking used
by `nearestPsfKey` in curvegen/report_template.html (see the 4 Sep PSF audit
in docs/ops/RUN_CAMPAIGNS.md).  It is a standalone mirror kept only for testing the
*algorithm* against small synthetic lattices -- it is NOT imported by the
report and must be kept in sync by hand if `nearestPsfKey` changes.
"""

import math
import unittest


def parse_psf_key(key):
    weighting, robust, taper = key.split("_")
    return {"weighting": weighting, "robust": float(robust), "taper": float(taper)}


def is_near_natural_family(weighting, robust):
    return weighting == "natural" or robust >= 1.99


def nearest_psf_key(candidates, point):
    """Mirrors nearestPsfKey(data, point) in report_template.html.

    `candidates` is {key: res_geo_mas}; `point` is a dict with weighting,
    robust (None for natural), taper (mas, may be None/0), and res (mas).
    """
    target_res = point["res"]
    target_weighting = point["weighting"]
    target_robust = 2.0 if (target_weighting == "natural" or point.get("robust") is None) \
        else float(point["robust"])
    target_taper = float(point.get("taper") or 0.0)
    taper_scale = 0.1 * target_res if target_res > 0 else float("nan")
    target_near_natural = is_near_natural_family(target_weighting, target_robust)

    best = None
    for key, res in candidates.items():
        if not (res > 0 and target_res > 0):
            continue
        parsed = parse_psf_key(key)
        same_family = (parsed["weighting"] == target_weighting or
                       (target_near_natural and
                        is_near_natural_family(parsed["weighting"], parsed["robust"])))
        d_robust = (parsed["robust"] - target_robust) / 0.2
        d_taper = (parsed["taper"] - target_taper) / taper_scale if taper_scale > 0 else 0.0
        candidate = {
            "key": key,
            "family": 0 if same_family else 1,
            "param_distance": d_robust * d_robust + d_taper * d_taper,
            "res_distance": abs(math.log(res / target_res)),
        }
        if (best is None or candidate["family"] < best["family"] or
                (candidate["family"] == best["family"] and
                 (candidate["param_distance"] < best["param_distance"] - 1e-12 or
                  (abs(candidate["param_distance"] - best["param_distance"]) <= 1e-12 and
                   candidate["res_distance"] < best["res_distance"])))):
            best = candidate
    return best["key"] if best else None


class TestNearestPsfKeyReplay(unittest.TestCase):
    def test_picks_matching_weighting_family_over_resolution_nearest(self):
        # MAIN-like case from the audit: curve point is briggs -0.22, taper
        # 40 mas, res 87 mas.  The resolution-nearest capture is a *natural*
        # point (86.9 mas); the correct answer is the briggs capture (98.6
        # mas) even though it is farther away in resolution.
        point = {"weighting": "briggs", "robust": -0.22, "taper": 40.0, "res": 87.0}
        candidates = {
            "natural_2.00_7.245": 86.9,
            "briggs_-0.20_38.299": 98.6,
        }
        self.assertEqual(nearest_psf_key(candidates, point), "briggs_-0.20_38.299")

    def test_natural_target_treats_high_robust_briggs_as_same_family(self):
        # Target is natural (taper 10, res 118).  briggs robust=2.00 counts
        # as the natural family and may win the tie; a low-robust briggs
        # capture must never win even though its resolution is closest.
        point = {"weighting": "natural", "robust": None, "taper": 10.0, "res": 118.0}
        candidates = {
            "briggs_2.00_10.489": 118.5,
            "natural_2.00_10.489": 118.7,
            "briggs_0.40_12.621": 118.0,
        }
        winner = nearest_psf_key(candidates, point)
        self.assertIn(winner, ("briggs_2.00_10.489", "natural_2.00_10.489"))
        self.assertNotEqual(winner, "briggs_0.40_12.621")

    def test_falls_back_to_other_family_when_none_match(self):
        # Target briggs, but only natural captures exist -- must still
        # return a key (the best available), not None.
        point = {"weighting": "briggs", "robust": -0.30, "taper": 20.0, "res": 90.0}
        candidates = {
            "natural_2.00_5.000": 88.0,
            "natural_2.00_9.000": 95.0,
        }
        winner = nearest_psf_key(candidates, point)
        self.assertIsNotNone(winner)
        self.assertIn(winner, candidates)


if __name__ == "__main__":
    unittest.main()

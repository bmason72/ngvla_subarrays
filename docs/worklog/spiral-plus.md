# spiral+5 / spiral+10 (Rev F)

Spec: `docs/plans/spiral-plus-subarrays-spec.md`. Worktree
`/work2/10240/bmason72/stampede3/ngvla_wt_spiral`, branch `feature/spiral-plus`.
Not merged to `main` yet (per spec, wait for the running campaign's collect
stage to finish and be checked, since it reads the subarray metadata CSVs).

## Current status

- **Built:** `curvegen/make_spiral_plus.py` (selection rule + CSV + figure),
  `spiral+5`/`spiral+10` added to `curvegen/config.py`'s Rev F `_SUBARRAYS`
  dict (defined only -- absent from `MFS_SUBARRAYS`/`RUN_SET`), a
  `core-spiral+5`/`core-spiral+10` pseudo-component in `curvegen/build_configs.py`
  resolved by antenna name against the cached selection CSV, metadata rows
  added to the three `subarrays_revf_*.csv` files, tests in
  `tests/test_spiral_plus.py`, figure at
  `docs/figures/spiral_plus_selection.png`.
- **Run:** nothing simulated (out of scope; CASA-free deliverable).
- **Tests:** `casapy -m unittest discover -s tests -t .` from the worktree
  root: 433 tests, OK (1 unrelated skip), ~59 s.
- **Decisions needed:** none. The "closest" reading below was confirmed by
  bmason 7 Sep 2026 (D11) and re-approved 21 Sep 2026 after reviewing
  `docs/figures/spiral_plus_selection.png`.
- **Next actions:** none pending for this piece; ready for bmason's review,
  then merge to `main` once the running campaign's collect stage is done.

## Assumption for bmason to confirm

"Closest (radially, from the core center)" was implemented as: work in a
local East-North tangent plane centred on the core centroid (114-antenna
mean), and for each arm take the core antenna with the smallest **tangent-
plane (2-D East/North) distance** to the arm's current tip -- not 3-D
distance, and not a purely radial (|r_antenna - r_tip|) comparison. For the
+10 pass, the arm's tip is advanced to the antenna chosen for +5, and the
next-closest *unselected* core antenna to that new tip is chosen. Arms are
processed in a..e order; an antenna, once chosen (by any arm, either pass),
is unavailable afterward. See the figure for a visual check: spiral radii
increase monotonically outward along each arm's station numbering, and core
radii top out under 5 km (both asserted in tests as an ENU-conversion sanity
check).

## Selection table (`sa_select/data/spiral_plus_selection.csv`)

| set | arm | tip | chosen | distance_m | r_antenna_m | r_tip_m | az_diff_deg |
| --- | --- | --- | --- | --- | --- | --- | --- |
| +5  | spa | spa001 | cor060 | 543.93 | 2160.50 | 2550.80 | 9.26 |
| +5  | spb | spb001 | cor064 | 601.92 | 1857.78 | 2388.89 | 7.71 |
| +5  | spc | spc001 | cor059 | 580.92 | 2170.51 | 2564.81 | 10.37 |
| +5  | spd | spd001 | cor078 | 437.62 | 2123.99 | 2461.15 | 7.00 |
| +5  | spe | spe001 | cor062 | 403.86 | 2059.03 | 2392.79 | 5.87 |
| +10 | spa | cor060 | cor080 | 312.85 | 1990.19 | 2160.50 | 7.26 |
| +10 | spb | cor064 | cor082 | 359.61 | 1531.82 | 1857.78 | 5.16 |
| +10 | spc | cor059 | cor068 | 375.33 | 1960.86 | 2170.51 | 8.65 |
| +10 | spd | cor078 | cor109 | 299.79 | 1894.67 | 2123.99 | 5.52 |
| +10 | spe | cor062 | cor102 | 287.52 | 1814.63 | 2059.03 | 4.49 |

spiral+5 = 54 spiral + {cor060, cor064, cor059, cor078, cor062} = 59 antennas.
spiral+10 = spiral+5 + {cor080, cor082, cor068, cor109, cor102} = 64 antennas.

## Log

### 2026-09-07

- Read the spec, `CLAUDE.md`, `curvegen/config.py` (lines ~150-320) and
  `curvegen/build_configs.py` to find the composition mechanism: `_SUBARRAYS`
  maps a subarray name to a list of "component" tokens; most tokens are cfg
  keys (`core`, `spiral`, `mid`, `long`) but `core-inner`/`core-outer` are
  precedents for a computed *named subset* of the core cfg (innermost/outer
  57 by 3-D radius from centroid, resolved in `build_configs.py`).
- Extended that precedent with `core-spiral+5`/`core-spiral+10`: pseudo-
  components resolved by exact antenna name against
  `sa_select/data/spiral_plus_selection.csv` (new
  `spiral_plus_core_lines()` in `build_configs.py`). `+10` reads both
  `+5` and `+10` tagged rows (10 names total), so spiral+10 already contains
  spiral+5's antennas without re-deriving them.
- `curvegen/make_spiral_plus.py`: reads the two Rev F cfgs (geocentric ECEF
  XYZ), converts to a local ENU tangent plane centred on the 114-antenna core
  centroid (WGS84 geodetic lat/lon of the centroid via a 5-iteration Bowring
  solve, then the standard ECEF->ENU rotation), computes radii, finds each
  arm's innermost spiral station by name-prefix (`spa`..`spe`), and runs the
  two nearest-unselected-core-antenna passes described above. Verified core
  radii top out at ~2.2 km (asserted `< 5000 m` in the script and in
  `tests/test_spiral_plus.py`) and that spiral radii increase outward along
  each arm's station numbering -- both fail loudly if the ENU conversion is
  wrong.
- `_SUBARRAYS["revF"]` (config.py) gained `"spiral+5": ["spiral",
  "core-spiral+5"]` and `"spiral+10": ["spiral", "core-spiral+10"]`,
  purely additive (`git diff` confirms every pre-existing line untouched);
  `MFS_SUBARRAYS` and `RUN_SET` were NOT touched, so the two new subarrays
  are "defined" (importable, buildable) but not in any offered/run set --
  matches the CSVs' existing precedent for seed-only entries like
  `core-outer`.
- Metadata rows appended (not regenerated) to `subarrays_revf_snapshot.csv`,
  `subarrays_revf_mfs_band4_snapshot.csv`, `subarrays_revf_mfs_band4_track.csv`
  (glob `subarrays_revf_*.csv` from the spec). `subarrays.csv` (the
  authoritative revF/track default, hand-maintained and explicitly protected
  by `build_subarrays_csv.py`) was left untouched -- it does not match the
  spec's named glob and there is no defined/offered status column to mark
  these entries against, so the CSV membership itself is the scoping
  mechanism. `n_ant`/`b_min_m`/`b_max_m` computed the same way
  `build_subarrays_csv.py` does (pairwise baseline stats over the raw
  antenna positions, no spurious-short filter -- spiral+5/10 have none of
  LONG's pathology); `calc_name` and beam-cap columns left blank, matching
  the pattern for other unmeasured/uncalibrated additions
  (`spiral+core-outer` etc.). `components` column follows the existing
  `"+".join(SUBARRAYS[name])` convention:
  `spiral+core-spiral+5` / `spiral+core-spiral+10`.
- Figure: `docs/figures/spiral_plus_selection.png` (matplotlib Agg, two
  panels: full array and a zoom on the core edge/spiral tips). Core in grey,
  each arm's innermost 4 spiral stations labelled and coloured, +5 picks as
  filled circles, +10 picks as open circles (same arm colour), solid arrows
  tip->+5 pick, dashed arrows +5 pick->+10 pick, equal aspect, km axes,
  legend, one-line title stating the rule.
- Tests: `tests/test_spiral_plus.py` (selection-rule invariants: exactly 5
  and 10 distinct choices, no repeats, all choices are core stations, +10
  superset of +5, one pick per arm per pass, ENU sanity checks; config
  membership: antenna counts 59/64, byte-identical pre-existing
  `_SUBARRAYS`, absence from `RUN_SET`/`MFS_SUBARRAYS` in both mono and MFS
  import modes; metadata: rows present/parse in the three touched CSVs with
  blank beam caps, absent from `subarrays.csv`). Also updated two
  pre-existing row-count assertions that the new rows changed:
  `tests/test_sa_select.py` (`("revF","snapshot")` count 14 -> 16) and
  `tests/test_mfs_campaign.py::test_mfs_metadata_keeps_native_caps_out_of_30ghz_field`
  (7 -> 9 rows per MFS band4 CSV).
- Full suite: `casapy -m unittest discover -s tests -t .` -> 433 tests, OK
  (1 skip, pre-existing/unrelated), ~59 s.
- Not committed (per task instructions); worktree diff is additive except
  for the two row-count assertions above.

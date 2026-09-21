# Plan: bring spiral+5 / spiral+10 / mid+spiral+5 / mid+spiral+10 into the Rev F release

Status: **planned, not started** (21 Sep 2026).  Rolling status lives in
`docs/worklog/spiral-plus.md`; append to it, not to this file.

Predecessor work: `docs/plans/spiral-plus-subarrays-spec.md` (the selection
rule), `docs/worklog/spiral-plus.md` (what was built on branch
`feature/spiral-plus`).  bmason approved the selection 7 Sep 2026 (D11) and
approved it again 21 Sep 2026 after reviewing
`docs/figures/spiral_plus_selection.png`.

## Goal

Add four subarrays to the released Rev F 4-hour-track campaign so the
selection tool can rank them:

| name | components | n_ant | b_min (m) | b_max (m) |
| --- | --- | --- | --- | --- |
| `spiral+5` | spiral + 5 core antennas | 59 | 403.86 | 39270.01 |
| `spiral+10` | spiral + 10 core antennas | 64 | 287.52 | 39270.01 |
| `mid+spiral+5` | mid + spiral+5 | 105 | 403.86 | 1272904.19 |
| `mid+spiral+10` | mid + spiral+10 | 110 | 287.52 | 1272904.19 |

The `spiral+5` / `spiral+10` geometry is already computed and cached in
`sa_select/data/spiral_plus_selection.csv`.  The two `mid+` combos are new in
this plan; their n_ant above is arithmetic (mid = 46) and **must be recomputed
from the cfg files**, not trusted from this table.

Science point of the exercise: the added core antennas cut b_min by half or
more relative to plain `spiral` (811 m to 404 m, then to 288 m), which doubles
the nominal LAS at fixed n_ant cost.

## Decisions

| id | date | decision |
| --- | --- | --- |
| D11 | 7 Sep 2026 | Selection rule: per arm, the nearest unselected core antenna in the tangent plane to the arm's current tip; a second round for +10. Re-approved 21 Sep from the figure. |
| D12 | 21 Sep 2026 | Run **revF/track only**. It is the only Rev F combo in `make_report.RELEASE_COMBOS`, and it yields both curve types. The mono-snapshot and Band-4 MFS views do not get these subarrays for now. |
| D13 | 21 Sep 2026 | Merge **`feature/spiral-plus` only**. `feature/curve-limits` stays unmerged pending a separate decision (action item A4 stays open for it). |
| D14 | 21 Sep 2026 | Add an explicit **subarray-subset flag** to the campaign chain, so the backfill provably cannot alter the already-released curves. |
| D15 | 21 Sep 2026 | **No beam caps.** bmason: "whatever you do for spiral should be fine for spiral+5,10 - same cap, if any." `spiral` and `spiral+mid` are both absent from `_BEAM_CAP_DEFAULT`, so all four new subarrays run uncapped: 14 tapers, no cap pruning. |

### Risk carried by D15

`spiral+5` is structurally closer to `spiral+core-outer` (spiral plus core
antennas), which **is** capped at core-outer's native beam, than it is to
plain `spiral`.  Uncapped, its coarse-taper branch may run into the regime
where the image is effectively made by the five added core antennas alone.
Check the delivered curve for a long, flat, high-eta coarse tail before the
data is released; if one appears, revisit the cap with bmason.

## Facts established 21 Sep 2026 (verified, with sources)

1. **The offered set is the metadata CSV, not code.** `campaign_tasks._offered`
   reads the combo's `subarrays_csv` from `sa_select/data/config_registry.csv`.
   `config.RUN_SET` (`curvegen/config.py:266`) is **dead** — nothing outside
   `config.py` reads it. For revF/track the CSV is the hand-maintained
   `sa_select/data/subarrays.csv`, which `build_subarrays_csv.py` explicitly
   refuses to rewrite.
2. **The sweep is resumable per point.** `sweep.Sweep.run_point` returns early
   when the key is already recorded (`curvegen/sweep.py:297`), and refine
   "runs on top of sweep.py's resumable results so re-runs are free"
   (`curvegen/refine.py` docstring). So re-running a settled combo is cheap.
   D14 is about provable isolation, not about cost.
3. **revF/track caps are hardcoded**, in `config._BEAM_CAP_DEFAULT`;
   `fill_beam_caps.py` is a deliberate no-op for that combo
   (`curvegen/fill_beam_caps.py:101`, `:121`). Nothing measures a cap for us.
4. **A missing sensitivity anchor is a hard error, not a silent wrong number.**
   `selector.py:327` falls back to the subarray *name* when `calc_name` is
   blank, and `sensitivity._resolve_calc_name` raises `ValueError` for an
   unknown name. The four new names therefore need `_DONOR_N_ANT` entries
   (the `spiral+core-outer` precedent, donor-rescaled from `main`).
5. **Latent bug on the branch.** `feature/spiral-plus` added `spiral+5` /
   `spiral+10` rows to both Band-4 MFS metadata CSVs but did not add the names
   to `config.MFS_SUBARRAYS`. In MFS mode `config.SUBARRAYS` and `IMSIZE` are
   filtered to `MFS_SUBARRAYS`, so a future Band-4 run would offer those
   subarrays and then die on a `KeyError`. Must be resolved at merge (task S0).
6. **`IMSIZE` has no entries for any of the four.** `config._IMSIZE["revF"]`
   lacks `spiral+5` and `spiral+10` even on the branch. A missing entry is a
   `KeyError` mid-sweep, not a preflight failure.
7. **Disk is not a constraint.** `$WORK` holds 22 GB of a 1 TB quota; track
   MSes run 0.25 to 1.2 GB each.
8. **Timing is soft.** The one track sweep log covering all six light
   subarrays (job 3415635_3) ran 4 h 52 m, but that job was partly
   re-verifying already-measured points, so it prices a resumed run, not a
   fresh one. Treat "about one hour of sweep per light subarray" as an
   order-of-magnitude figure with a factor-of-two uncertainty, and give the
   sweep generous walltime rather than trying to predict it.

## Safety against other open loops

- **No campaign is queued or running** (checked 21 Sep 2026: only an
  interactive dev job). The `CLAUDE.md` campaign freeze is **not** active, so
  tasks S0 to S4 may edit `curvegen/`, `sa_select/` and the data CSVs on
  `main` directly. Once S5 is launched the freeze rule applies again and all
  further code work moves to a worktree.
- **`feature/curve-limits` stays unmerged** (D13). It also edits
  `curvegen/make_report.py`, and task S1 edits that file's `ORDER` list, so
  expect a small merge conflict there whenever curve-limits is finally taken.
  Note it in `docs/plans/NEXT_AGENT.md` rather than pre-solving it.
- **Action items A2 (memo T6 review) and A3 (Band-4 report review)** are
  independent of this work and are not blocked by it.
- **The released mono curves must not move.** That is what D14 buys. The
  acceptance test for the whole exercise is that
  `sa_select/data/revf_curves.csv` changes only by the addition of rows for
  the four new subarrays.

## Tasks

Effort and model suggestions follow the `CLAUDE.md` convention. "Anthropic /
OpenAI" names the agent role from `AGENTS.toml`.

### S0 — Merge `feature/spiral-plus` to main, and fix the MFS latent bug

Effort: medium. Model: sonnet_worker / terra_worker. Root agent reviews.

The branch lives in worktree
`/work2/10240/bmason72/stampede3/ngvla_wt_spiral` with **uncommitted**
changes (7 modified files, 6 untracked). Commit there first, then merge.

1. In the worktree, update `docs/worklog/spiral-plus.md` so the "Decisions
   needed" line reads as confirmed (D11, and re-approved 21 Sep 2026) rather
   than "to confirm".
2. Resolve fact 5. Remove the `spiral+5` and `spiral+10` rows from
   `sa_select/data/subarrays_revf_mfs_band4_snapshot.csv` and
   `sa_select/data/subarrays_revf_mfs_band4_track.csv`: under D12 those
   combos are out of scope, and a metadata CSV must never offer a subarray
   the config cannot build. Revert the two row-count assertions in
   `tests/test_mfs_campaign.py` accordingly (9 back to 7).
3. Commit, merge to `main` with `--no-ff`, run
   `casapy -m unittest discover -s tests -t .` from the repo root, and record
   the count.
4. Update `docs/ACTION_ITEMS.md`: A4 becomes "curve-limits only".

### S1 — Define the two mid combos and all four sets of metadata

Effort: medium. Model: sonnet_worker / terra_worker. Root agent reviews the
numbers before anything is launched.

1. `curvegen/config.py`, `_SUBARRAYS["revF"]`: add
   `"mid+spiral+5": ["mid", "spiral", "core-spiral+5"]` and
   `"mid+spiral+10": ["mid", "spiral", "core-spiral+10"]`. The
   `core-spiral+N` pseudo-components already resolve in `build_configs.py`.
   Name order follows the existing `mid+spiral+core-outer`.
2. `curvegen/config.py`, `_IMSIZE["revF"]`: add all four. `spiral+5` and
   `spiral+10` take 4096, mirroring `spiral` (same b_max, uncapped).
   `mid+spiral+5` and `mid+spiral+10` take 8192, mirroring `spiral+mid`.
   Do **not** add any of the four to `_BEAM_CAP_DEFAULT` or `CAP_REFERENCE`
   (D15).
3. `sa_select/sensitivity.py`, `_DONOR_N_ANT`: add the four names with their
   **computed** antenna counts. Compute them, do not copy this plan's table.
4. `sa_select/data/subarrays.csv`: append four rows. Geometry (`n_ant`,
   `b_min_m`, `b_max_m`) computed exactly the way `build_subarrays_csv.py`
   computes it, over the built cfg files, honouring `config.MIN_UVRANGE_M`.
   `las_coeff` 0.80 with the standard note; `beam_cap_arcsec_30ghz` blank
   (uncapped); `calc_name` blank (falls through to the name, per fact 4).
   That file is hand-maintained and `build_subarrays_csv.py` refuses to touch
   it, so append deliberately and leave every existing row byte-identical.
5. `curvegen/make_report.py`, `ORDER`: append the four names so they receive
   colour slots and appear in the report.
6. Tests: antenna counts of the built cfgs (59 / 64 / 105 / 110, computed);
   `mid+spiral+N` is a strict superset of `spiral+N`; the four resolve
   through `sensitivity.natural_rms` without raising; the four appear in
   `offered_order(subarrays.csv)`; every pre-existing row of
   `subarrays.csv` is unchanged.
   Note `tests/test_sa_select.py::test_campaign_metadata_csvs_load` asserts
   row counts for revD/track, revF/snapshot and revC/track but **not** for
   revF/track, so the four new rows break nothing. Add a revF/track entry to
   that count map (14 becomes 18) so the file is guarded from now on.

### S2 — Subarray-subset flag for the campaign chain

Effort: medium-high (it is the safety mechanism; get it exactly right).
Model: sonnet_worker / terra_worker. Root agent reviews.

Add an opt-in restriction, unset by default, so that existing behaviour is
byte-identical when it is not used.

1. `curvegen/campaign_tasks.py`: honour an `NGVLA_SUBARRAYS` environment
   variable (comma- or space-separated names) in `_offered`, so `groups`,
   `narray` and `seeds` all narrow together. A name not present in the
   combo's metadata CSV is a **fail-closed** error, never a silent drop.
2. `curvegen/submit_campaign.sh`: a `--subarrays "a b c"` option that
   validates the names and exports `NGVLA_SUBARRAYS` into the `EXP` export
   string for every stage. Echo the restricted set prominently in the
   submission banner.
3. **Collect is deliberately NOT subset.** `collect.py` must keep reading the
   whole offered set, or the routed curves CSV would lose the existing
   subarrays. Add a comment saying so, and a test that proves collect ignores
   `NGVLA_SUBARRAYS`.
4. Tests: unset means an unchanged group layout for revF/track; a subset of
   two names gives the expected `groups`/`narray`/`seeds`; an unknown name
   exits non-zero; collect is unaffected.

### S3 — Fail-closed preflight on the offered set

Effort: low. Model: sonnet_worker / luna_worker.

Fact 5 and fact 6 are the same class of bug: the metadata CSV offers a
subarray that the config cannot build or size. Add a check that every offered
subarray is present in both `config.SUBARRAYS` and `config.IMSIZE`, raising a
clear error naming the offenders. Wire it into `campaign_tasks.groups` (so it
fires before any node is allocated) and cover it with a test.

### S4 — CASA-free preflight and review gate

Effort: low. Model: haiku_scouter / luna_worker. **Root agent reviews the
output and signs off before anything is submitted.**

Build the cfgs and print, without running CASA imaging: the four antenna
counts; b_min / b_max; the resolved IMSIZE; the `grid_rows` point count per
subarray (expect 12 rows by 15 tapers = 180 base points, uncapped); the
restricted `groups` / `narray` under the subset flag; and confirmation that
all four are absent from the cap tables. Full test suite green on main.

### S5 — Prep (seed) stage — **bmason launches**

Agents prepare the command line only.

```bash
bash /home1/10240/bmason72/Code/ngvla_subarrays/curvegen/submit_campaign.sh \
  revF track --prep-only \
  --subarrays "spiral+5 spiral+10 mid+spiral+5 mid+spiral+10" \
  --time 48:00:00
```

QA gate: read the seed beams in `prep_<jobid>.log` before going on. The four
natural beams should sit close to `spiral` (for the two `spiral+N`) and to
`spiral+mid` (for the two `mid+spiral+N`). A wild value means the cfg or the
pseudo-component resolution is wrong.

### S6 — Sweep, refine and collect — **bmason launches**

`--prep-only` prints the exact follow-on `sbatch` lines with the right
dependency and array size. Use them. Give the sweep generous walltime per
fact 8. Refine stays at the campaign default (60 / 3) to match how the
existing mono track curves were made.

### S7 — Harvest and release

Effort: medium. Model: sonnet_worker for the mechanics; root agent validates
the science with bmason.

1. Confirm zero failed and zero skipped points, and that refine reported no
   unresolved defects.
2. **Acceptance test for D14**: diff `sa_select/data/revf_curves.csv` against
   its pre-run state. `collect.py` rewrites that file wholesale from a sorted
   glob of the per-subarray result files (`curvegen/collect.py:193`), so the
   new subarrays' rows interleave rather than append. The test is therefore
   that the diff contains **only added lines** — no deleted and no modified
   lines — and that every added line names one of the four new subarrays.
   Archive the pre-run copy before S6 is launched, not after.
3. Inspect the four curves for the D15 risk (a long, flat, high-eta
   coarse-taper tail).
4. Rebuild the reports, commit the routed CSV and results, update
   `docs/worklog/spiral-plus.md`, `docs/plans/PLAN-session-log.md`,
   `docs/ACTION_ITEMS.md`, and the memo's subarray table.

## Open questions

None blocking. A7 in `docs/ACTION_ITEMS.md` (whether to run these subarrays
in the snapshot and MFS combos too) is answered "not now" by D12 and should
be reworded, not closed.

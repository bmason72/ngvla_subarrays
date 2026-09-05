# Polish sampling and `$SCRATCH` / `$WORK` storage

Short answer: “polish” performs targeted, adaptive, mostly sub-grid
sampling. It does not simply sample adjacent points of the original
lattice.

## How polish samples

The polish commands rerun the normal campaign with `--refine-budget 200
--refine-rounds 8`. Because the base lattice is resumable and already
complete, prep, sweep, and grid filling are effectively no-ops; refinement
does the new work. The 200-point budget is per subarray, not per whole
campaign. See `docs/ops/RUN_CAMPAIGNS.md` and `curvegen/campaign_sweep.sbatch`.

For each round, `refine.py`:

1. Builds both published curves:

   - Imaging/sculpted curve with skirt setpoint `0.10`.
   - Point-source curve with no skirt constraint.

   Only `ok`/`capped` measurements with `eta <= 5` participate.

2. Evaluates those curves on the report’s fine resolution grid, spaced by
   `0.01 dex`. These are interpolated envelope points—not necessarily raw
   measured lattice points.

3. Looks at adjacent points on that rendered/interpolated curve and targets:

   - An eta jump larger than `0.25`, provided the resolution ratio is no
     more than `1.35`.
   - For beam-capped heterogeneous subarrays only, resolution gaps larger
     than `1.35` are also targeted. Homogeneous-array gaps that large are
     treated as real infeasibility gaps.

For each problematic adjacent curve pair `(a,b)`, it proposes these Briggs
measurements:

| Probe | Robust value | Taper value |
|---|---:|---:|
| Central midpoint | `(r_a + r_b)/2` | Geometric mean `sqrt(t_a t_b)` |
| Zero-taper midpoint | `(r_a + r_b)/2` | If one taper is zero, half the nonzero taper |
| Robust bracketing around `a` | `r_a ± 0.2` | `t_a` |
| Robust bracketing around `b` | `r_b ± 0.2` | `t_b` |
| Taper bracketing around `a` | `r_a` | `t_a × 1.22`, `t_a ÷ 1.22` |
| Taper bracketing around `b` | `r_b` | `t_b × 1.22`, `t_b ÷ 1.22` |

Natural weighting is treated as Briggs robust `+2` for this calculation.
Robust is constrained to `[-2,+2]`; existing measurements are discarded
from the candidate list.

So, specifically:

- The original robust grid is spaced by `0.4`; polish’s `±0.2` probes are
  initially half-grid points.
- Taper `×/÷1.22` and geometric-midpoint probes are generally off the
  original log-taper grid.
- The curve endpoints themselves may already have interpolated
  robust/taper values.
- Later rounds refine around earlier off-grid measurements, so values can
  become still finer.

Thus this is local off-lattice/sub-grid probing around discontinuities in
the optimal envelope—not a systematic grid subdivision. Candidates are
prioritized severity-first and round-robin across jumps so one bad feature
does not consume the entire budget.

## What moved from `$SCRATCH` to `$WORK`

Only the simulated measurement sets—the `ms*` directories—were migrated.
The docs record a one-time approximately 8.7 GB `rsync`, followed by
checksum verification of 16/16 MSes. The old scratch copies were
intentionally left in place for the purge system to remove eventually. The
exact `rsync` command was not preserved in the repository.

Conceptually, the copy was:

```text
$SCRATCH/ngvla_curvegen/ms*
        → $WORK/ngvla_curvegen/ms*
```

The persistent destinations are:

```text
$WORK/ngvla_curvegen/ms
$WORK/ngvla_curvegen/ms-revF_snapshot
$WORK/ngvla_curvegen/ms-revD_track
$WORK/ngvla_curvegen/ms-revD_snapshot
```

The routing now works as follows:

- Default Rev-F/track uses `curvegen/ms`, whose current symlink points to
  `/work2/10240/bmason72/stampede3/ngvla_curvegen/ms`.
- Non-default campaigns export
  `NGVLA_MS_BASE=$WORK/ngvla_curvegen`, and `config.py` adds the appropriate
  `ms-<rev>_<mode>` suffix.
- `NGVLA_SCRATCH=$SCRATCH/ngvla_curvegen` continues to supply `work*`
  directories for disposable tclean outputs.

Nothing automatically gets copied from scratch to work after each campaign
now. New or missing MSes are created directly in `$WORK`; `make_ms()` reuses
them if present. The regeneration job is therefore not a copy job—it
re-simulates missing MSes directly into the persistent store.

Meanwhile:

- Tclean work directories remain under `$SCRATCH/ngvla_curvegen/work*`.
- Slurm process working directories are pinned to
  `$SCRATCH/ngvla_curvegen/run_<jobid>_<task>` because CASA also emits large
  `TempLattice*` files into the process CWD.
- Results CSVs and PSF profiles live in the repository, not scratch.
- Old scratch MS copies are currently still present alongside the `$WORK`
  copies.

## Primary references

- `docs/ops/RUN_CAMPAIGNS.md`
- `docs/plans/PLAN.md`
- `docs/ops/casaLocation.md`
- `curvegen/refine.py`
- `curvegen/config.py`
- `curvegen/make_report.py`
- `curvegen/submit_campaign.sh`
- `curvegen/campaign_sweep.sbatch`
- `curvegen/regen_ms.sbatch`
- `curvegen/simulate.py`

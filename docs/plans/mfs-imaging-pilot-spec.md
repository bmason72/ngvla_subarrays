# Spec: MFS Band-4 imaging pilot launcher (MFS-3, imaging half)

Written 5 Sep 2026 by the orchestrating agent for a sonnet_worker.  Read
`CLAUDE.md`, `docs/plans/MFS_CAMPAIGN_PLAN.md` (Pilots section), and
`docs/ops/RUN_CAMPAIGNS.md` (first section) before starting.  Do NOT submit any
Slurm job (`sbatch`) -- bmason launches jobs.  Do NOT run tclean.  Do not edit
`docs/plans/*` (the orchestrator updates plans).  Run tests with
`/work2/10240/bmason72/stampede3/casaenv/bin/casapy -m unittest discover -s tests -t .`
from the repo root; all 362 must stay green.

## Context (verified 5 Sep)

* Simulation half of the pilot is DONE: Slurm job 3470012 created four MSes in
  ~15 s each, MaxRSS 236-327 MB:
  `/scratch/10240/bmason72/ngvla_curvegen/ms-revF_snapshot_band4_pilot-nchan{027,054}-equal/{core,main}.ms`
  (env: `NGVLA_REV=revF NGVLA_SIM_MODE=snapshot NGVLA_BAND=band4
  NGVLA_NOISE_POLICY=equal NGVLA_NCHAN=<27|54>
  NGVLA_CAMPAIGN_VARIANT=pilot-nchan0NN-equal NGVLA_MS_BASE=$SCRATCH/ngvla_curvegen
  NGVLA_SCRATCH=$SCRATCH/ngvla_curvegen`).  Manifests exist in
  `curvegen/results-revF_snapshot_band4_pilot-nchan0NN-equal/campaign_manifest.json`.
* `curvegen/sweep.py` already supports MFS (pins specmode=mfs etc.), and has
  `--seeds-only` (natural + briggs r=-2, taper 0) and `--points-file` (JSON list
  of `[weighting, robust, taper_mas]`; `run_points(..., allow_skipped=True)`).
  Verified: `sweep.py core --seeds-only --dry-run` works under the pilot env
  (prints "seed pending").  `Sweep.__init__` auto-creates a missing MS via
  `simulate.make_ms`, and validates the campaign manifest for MFS combos.
* Per-point tclean times from the mono campaigns (imsize core 4096 / main
  15000): snapshot core median 12 s, main 116 s; track core 20 s, main 149 s
  (p90 170 s, max 1045 s).  Expect MFS to be slower (nchan x gridding).
* Results CSV columns: subarray,weighting,robust,taper_mas,imsize,cell_arcsec,
  bmaj_arcsec,bmin_arcsec,bpa_deg,res_geo_arcsec,sigma_dirty,skirt,status,error,
  elapsed_s.  eta = sigma_dirty / sigma_dirty(natural, taper 0) within the same
  results table.  NB: absolute sigma_dirty is NOT comparable across nchan
  (equal 1-Jy per-channel noise -> more channels = lower absolute noise); only
  eta ratios, beams, skirt are comparable.
* Existing launcher pattern to mirror: `curvegen/mfs_snapshot_sim_pilot.sbatch`
  + `curvegen/submit_mfs_snapshot_sim_pilot.sh` (env plumbing, per-run logs
  under `/work2/10240/bmason72/stampede3/`, `/usr/bin/time -v`, variant
  isolation, parallel subshells with MAX_PROCS).

## Deliverables

1. `curvegen/mfs_pilot_points.py` (runs under casapy; CASA-free logic).
   CLI: `mfs_pilot_points.py <subarray> --out points.json` under the pilot env
   of the REFERENCE variant (the first nchan in the list, i.e. nchan027).
   Reads that variant's results CSV (`config.RESULTS_DIR`), requires both seeds
   present with status ok, computes `res_fine`, `res_nat` (mas, from
   res_geo_arcsec of briggs r=-2 t=0 and natural t=0), then
   `tapers = config.taper_list_mas(res_fine, res_nat)` (the canonical 14-level
   grid) and picks `mid = tapers[6]`, `coarse = tapers[8]`.  Emits the 11
   non-seed pilot points:
   natural x {mid, coarse}; briggs r in {-2.0, -0.4, 1.2} x {0, mid, coarse}
   minus the (-2.0, 0) seed.  Round robust to 2 dp, taper to 3 dp (match
   `adaptive.canon_rt`).  The SAME file is used for every nchan variant of that
   subarray so point keys match exactly across variants.  Fail loudly if seeds
   are missing.
2. `curvegen/mfs_pilot_compare.py` (CASA-free; plain python3 or casapy).
   CLI: `--ref <results dir A> --other <results dir B> [--subarrays core main]
   [--out report.md]`.  Joins ok rows on (weighting, robust, taper_mas) after
   the same rounding.  Per matched point: eta_A, eta_B, d_eta = |eta_B-eta_A|/eta_A,
   d_res = |res_B-res_A|/res_A (res_geo), d_bmaj, d_bmin (relative), d_skirt
   (absolute), elapsed_A, elapsed_B.  Criteria (from MFS_CAMPAIGN_PLAN):
   every point d_eta < 0.005 and d_res < 0.01; endpoints (the two seeds) d_res
   < 0.01 and d_skirt < 0.02; report p95 and max of d_eta over the matched
   set (pass thresholds 0.01 / 0.02).  Print a markdown table per subarray,
   a timing table (median/max elapsed per subarray per variant, plus imsize
   and the nchan from each dir's manifest), unmatched/failed points, and a
   final `PASS`/`FAIL` line with the failing criteria.  Exit 0 on pass, 3 on
   fail, 2 on usage/missing data.  If `--other` is omitted print only the
   timing table for `--ref` (cost-benchmark mode).
3. `curvegen/mfs_imaging_pilot.sbatch` + `curvegen/submit_mfs_imaging_pilot.sh`.
   Submit-script options: `--sim-mode snapshot|track` (default snapshot),
   `--nchan-list 27:54` (default), `--time` (default 04:00:00 snapshot,
   08:00:00 track), `--max-procs` (default 4), `--subarrays core:main`.
   Same env plumbing as the sim launcher (variant per nchan, scratch-first
   MS base, `NGVLA_NOISE_POLICY=equal`, band4, revF, preflight import check).
   sbatch phases, all under `/usr/bin/time -v`, per-run logs
   `/work2/10240/bmason72/stampede3/mfs_imaging_pilot_<jobid>_<variant>_<sa>_<phase>.log`:
   0. `build_configs.py` once (as the sim launcher does).
   1. For every variant x subarray in parallel (<= MAX_PROCS, OMP_NUM_THREADS
      = 80 / MAX_PROCS): `sweep.py <sa> --seeds-only` (creates the MS if
      missing, so this launcher also works for `--sim-mode track`).
      Any failure -> stop with non-zero exit.
   2. For each subarray, under the FIRST variant's env:
      `mfs_pilot_points.py <sa> --out $NGVLA_SCRATCH/mfs_imaging_pilot/points_<sa>.json`.
   3. For every variant x subarray in parallel: `sweep.py <sa> --points-file
      <that json>`.
   4. If >= 2 variants: `mfs_pilot_compare.py --ref <dir of first variant>
      --other <dir of each later variant> --out <other dir>/nchan_convergence_vs_<first variant>.md`
      and echo the report into the job log.  Single variant: timing-only mode
      to `<ref dir>/timing_<sim_mode>.md`.  Compare failures must not mask
      sweep failures (report both; job exit non-zero on any sweep failure;
      exit 3 if only the convergence criteria failed).
   CASA cwd for every sweep = a per-run scratch dir (as the sim launcher).
4. Tests (`tests/test_mfs_pilot.py`, CASA-free): points generator on a
   synthetic results CSV (correct 11 points, rounding, exact taper indices,
   failure when seeds absent); compare on two synthetic CSVs (pass case, an
   eta-fail case, endpoint-fail case, timing-only mode, unmatched handling).
   Use tmp dirs; monkeypatch/inject rather than touching real results dirs.
   Never call tclean or simulate in tests (a placeholder test once appended
   real rows to results/core.csv -- see PLAN gotchas).
5. Shell check: `bash -n` both scripts; run the submit script with a
   `--dry-run` flag you add that prints the sbatch command instead of
   running it (and `SBATCH_DRY_RUN` style is fine).  Confirm the preflight
   works for both sim modes (`NGVLA_SIM_MODE=track` band4 registry row exists).
6. Add a short "MFS imaging pilot" subsection to the top section of
   `docs/ops/RUN_CAMPAIGNS.md` with the two copy-paste commands (snapshot
   27:54 convergence; track 27 cost benchmark) and the QA grep lines.

## Report back

State what you built, test count/result, the dry-run output of both submit
commands, any assumption you had to make about sweep.py behaviour (e.g. beam
caps for main, allow_skipped semantics), and anything in the plan you could
not satisfy.

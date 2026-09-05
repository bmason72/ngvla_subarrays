# Campaign proposal: Rev D subarrays + snapshot sims (features 5 & 6)

For bmason to review; nothing here runs until you approve and submit the
sbatch from a login node.  Prereq is tranche 1 component D (the (rev,
sim_mode) axis) and component C (profile capture — new sweeps then collect
PSF profiles for free, feeding feature 3).  10 Jul 2026.

## What I propose to run, in order

**Campaign 1 — Rev F / snapshot** (feature 6 first: it validates the new
sim_mode axis against arrays we already know well).
- Same 14 offered subarrays, same (robust, taper) grid machinery; sims are
  one 60 s integration instead of the 4 h track.
- Per-point tclean is ~3-5x faster (tiny MS); expect the GROUPED node to
  finish in well under a day; request 24 h.
- Known physics risks (QA gates below): instantaneous uv coverage is sparse
  and elongated -> beams strongly elliptical (res_geo hides axis ratio; we
  record bmaj/bmin so it is inspectable), curves noisier, refine matters
  more; skirt-at-1-FWHM on an elongated beam is a rougher metric.

**Campaign 2 — Rev D / track** (feature 5).
- Component .cfgs exist: ngvla-configurations/"Rev D"/CASA Files/
  ngvla-revD.{core,spiral,mid,lba,sba,...}.cfg.
-RevD subarrays to include: mirror the Rev F structure where components exist — core,
  spiral, mid, core+spiral, spiral+mid, main,main+long,long,mid+long
- Full sweep cost comparable to the original Rev F campaign; request 48 h.

**Rev D / snapshot**: only if you want it after seeing 1 + 2 (one more
registry row + rerun; no new code).

**Piggyback — feature 3 backfill (Rev F / track profiles).** A short,
resumable re-imaging pass over ONLY the envelope-anchor lattice points
(the ringed heatmap cells, a few tens per subarray) to capture radial
profiles for the CURRENT data; a few node-hours total, can ride either
allocation or the vnc node. New campaigns collect profiles automatically.

## Mechanics (mostly existing machinery)

1. Prep (I do, code side): build_configs.py generalized per rev; generate
   subarrays_revD.csv (n_ant/b_min/b_max from the .cfgs, las_coeff 0.8 as
   for Rev F, calc_name mapping — NB the memo-96 pkl is used as-is, so
   Rev D sensitivity anchors carry the known pkl-vintage caveats already
   logged in PLAN §13); add registry rows (revF,snapshot / revD,track);
   beam caps are filled from the measured coarsest-component natural seeds
   (two-step: seeds first, then caps into the registry metadata, then the
   full grids — same as Rev F did).
2. Job topology per your standing rule (subarray with baselines > ~2600 km
   -> own node): long/lba-containing subarrays get their own array tasks;
   everything else shares one node. Slurm job array + a collect/report
   post-job with --dependency=afterok. Because each (rev, mode) writes to
   FRESH results-<rev>_<mode>/ dirs, the prep-idempotency wrinkle that
   deferred the multi-node recompute (PLAN §"Recompute campaign") does not
   arise here — arrays start empty.
3. QA gates before the full grid burns hours: per subarray, seeds +
   `--limit 4` pilot; eyeball seed beams (snapshot: check axis ratio and
   that imsize/cell from im.advise stay sane); only then the full sweep.
   Refine + collect + make_report --rev/--sim-mode close each campaign.
4. Deliverables per campaign: results-<rev>_<mode>/ CSVs + profiles,
   registry-routed curves CSV, its own HTML report, PLAN/handoff notes.

## What I need from you

1. The Rev D offered-subarray list (mark up the default above).
   -> DONE
2. Snapshot convention: single 60 s integration at transit (HA = 0) with
   the same dec +24 — confirm, or specify HA/dec.
   -> a single 60s integration
3. Approval to stage the sbatch scripts; you submit from a login node.
   -> yes just write them. i will submit


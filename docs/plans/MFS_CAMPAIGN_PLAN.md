# MFS broadband continuum campaigns — plan summary (16 Jul 2026)

Standalone summary for resuming this workstream.  The authoritative, fuller
version lives in `docs/plans/PLAN.md` § "MFS broadband continuum campaigns"; the codex
gpt-5.6-sol design consult (question + full critique) is in
`tmp/mfs_campaign_consult.md` / `tmp/mfs_campaign_consult_out.md`.
**Status: IMPLEMENTATION IN PROGRESS (4 Sep 2026) — MFS-2a's Ka-band routing,
required-nchan checks, immutable manifest, multi-channel simulation setup, and
pinned MFS tclean setup are implemented. MFS-2b is substantially hardened;
the MFS-2c leaf/segmented-edge foundation and band-native collect/report routing
are built and CASA-free tested. Nothing has been launched. A simulation-only,
snapshot nchan/RSS pilot launcher is now ready; full limiting envelopes,
MFS-2d replay, imaging convergence/noise pilots, and the production wave runner
remain.**

## What is being built

A new campaign kind for `curvegen/`: per-band broad-band **MFS continuum**
taperability curves — **point-source curves only** initially — for both sim
modes (4 h track and snapshot, 60 s dumps as now), one simulation set per
(subarray, band).  Results feed the same registry/collect/report machinery
as the existing mono-30 GHz campaigns, as new (rev, sim_mode, **band**)
combos.

## Scope decisions (bmason, 16 Jul 2026)

1. **revF only; subarrays = homogeneous + main** (7 SAs: core-inner, core,
   spiral, mid, core+spiral, spiral+mid, main).  core+mid stays excluded;
   LONG combos and revD deferred to a later wave.
2. **Bands 1–6 defined by the ngECT calculator** (`receiver_data.pkl`):
   each band = `freq_center` ± `max_bw`/2 → 2.4±1.15, 8±4.4, 16±4.1,
   27±6.75, 41±10, 93±10 GHz.  Band 6 uses the 20 GHz max instantaneous
   bandwidth, NOT its 70–116 GHz RF span.  Fractional bandwidths:
   0.96, 1.10, 0.51, 0.50, 0.49, 0.215.
3. **Channel count via a convergence pilot** (analytic floor first, min 16;
   details below).  The pilot is the tractability gate.
4. **Lattice = complete coarse tensor product** (~68–84 pts, ~40% of full):
   robust {−2,−1.2,−0.4,0.4,1.2,2} × (taper 0 + every 2nd canonical log
   taper), PLUS the full natural+taper row and all 11 robusts at taper 0.
   Resumable — interior fills in later if/when imaging curves are wanted.
   **SUPERSEDED 21 Jul 2026:** the fixed reduced lattice becomes the SEED
   of a goal-oriented adaptive (quadtree/AMR) sampler — bmason-approved
   design in `docs/features/MFS2_ADAPTIVE_SAMPLER_SPEC.md` (tolerances, loss, cliff
   localization, V1 replay gate).  MFS-2 in the task table below is
   replaced by that spec's MFS-2a..2e breakdown.

## Key assumptions (and how each is protected)

- **A1 — the measured quantities converge at modest nchan.**  eta is a
  global functional of the gridded weights (dominated by well-filled inner
  uv cells) and beam/skirt/profile use ≤3 FWHM, so they converge far below
  the intractable "no grating artifacts anywhere in the image" criterion
  (nchan ≈ f_bw·imsize/OVERSAMPLE ≈ 900–3300 for band 2).  *Protected by:*
  the convergence pilot with strict criteria; explicit reconvene-with-bmason
  gate if the fine end (robust −2, sparse outer uv, comb effect largest)
  stalls.
- **A2 — the protected field of view is a stated convention, not the whole
  image.**  The sim does not model intra-channel (finite-width) smearing at
  all, so we declare: PSF faithful to **3 synthesized-beam FWHM at ≤1%
  sinc loss** → analytic floor nchan ≥ 38.5·f_bw → {64, 64, 32, 32, 32, 16}
  for bands 1–6.  We must NOT describe the full 4096–15000-px image as
  smearing-safe.  Production nchan = max(floor, pilot result), scaled per
  band ∝ f_bw (pow2-rounded), bands 1+6 validated as endpoints.
- **A3 — the reduced lattice preserves the ptsrc envelope.**  Hybrid
  robust+taper solutions can form a lower-eta interior branch (memo 76),
  and refine.py can only chase jumps in the envelope it already sees —
  hence a *complete* coarse tensor product (not axes-only), so 2-D bilinear
  cells stay complete.  *Protected by:* retrospective validation BEFORE any
  build: replay the four existing mono campaigns' full lattices through the
  reduced mask and compare reduced-vs-full ptsrc envelopes (pure
  `sa_select/envelope` replay, no CASA).  Acceptance: p95 |Δeta|/eta < 2%
  in-band; worse → densify.
- **A4 — MFS curves are fixed-window native curves.**  They are NOT ∝1/f
  self-similar and must not be written into `*_30ghz` schema fields or
  auto-scaled.  Band 6 (tunable 20 GHz within 70–116) would need its own
  tuning axis later.  v1 deliverable = per-combo curve CSVs + reports. The
  report's fixed-window calculator is band-aware; exposure through the public
  Python `CurveLibrary.for_config` API remains out of scope.
- **A5 — noise convention (OPEN DECISION).**  v1 default = equal 1-Jy
  per-channel noise (pure *geometric* uv-filling convention, explicitly
  labeled).  The pilot A/Bs this against per-channel inverse-variance
  weighting from `receiver_data.pkl` (receiver Tsys varies strongly across
  bands 1–2); **bmason decides after seeing the A/B numbers.**
- **A6 — cost/storage stay bounded.**  With pilot-scale nchan: whole track
  wave ~150–400 node-h (snapshot wave ~free); RR-LL MSes ~50–200 GB.
  *Protected by:* a FITTED cost model (per-point T = A(imsize) +
  B·N_bl·N_dump·N_chan·N_corr, benchmarked at nchan 1/16/64/prod ×
  imsize 4096/15000 × mode) before sizing the wave; sm.corrupt MaxRSS
  benchmarked at 64/128 chans before any 512-chan sim.
- **A7 — the 8-queued-jobs cap is the binding constraint.**  Solution: one
  multi-node allocation per wave = **1 queue slot** (vs ~8–10 for the
  current 3-job chain + array).

## Design summary

- **Config axis:** `NGVLA_BAND` env ("" = legacy mono; "band1".."band6");
  path suffix `-<rev>_<mode>_<band>`; `config_registry.csv` gains band,
  ref_freq_ghz, freq_lo/hi_ghz, nchan, curve_types, noise_policy.  ALL
  lookups become (rev, sim_mode, band); the combined report's payload keys
  must include band (today `rev_mode` only — bands would overwrite).
- **simulate.py:** nchan channels spanning [freq_lo, freq_hi]; NB
  `sm.setspwindow(freq=)` takes the FIRST CHANNEL CENTER (f_lo + Δf/2), not
  the band center; stokes **"RR LL"** (cross-hands cannot contribute to a
  noise-only Stokes-I sim — halves MS size); post-sim asserts on CHAN_FREQ
  edges + dump count.
- **sweep.py:** pin `specmode="mfs", reffreq=<center>, nterms=1,
  deconvolver="hogbom", stokes="I", parallel=False`; cell sized at the
  TOP-of-band frequency, seed-checked bmin ≥ 5 px; eta referenced to the
  same-combo MFS natural seed; per-band beam caps via the existing
  fill_beam_caps two-step (main is the only capped SA in the v1 set).
- **Campaign manifest** (per-combo JSON in its results dir): band edges,
  nchan, correlations, noise policy, cell policy, lattice version, CASA
  version; `make_ms()`/`run_point()` validate before reusing an MS or
  appending to a results CSV (extends the "resumable sweeps preserve stale
  conventions" gotcha protection to the new axis).
- **refine.py:** new `--curves {both,ptsrc}` mode.  **fill_grid.py must NOT
  run** on reduced-lattice combos (it would refill the full canonical
  lattice); wave runner omits it + manifest guard inside fill_grid.
- **Parallelism:** one 8–16-node icx allocation per wave running TACC
  **PyLauncher** (fallback: simple srun --exact farm) over full-node
  (band, SA) work units; in-job phases: prep (cfgs + sims/seeds) →
  barrier: fill_beam_caps + verify → dynamic sweep units (sweep_parallel +
  refine --curves ptsrc) → completeness check → in-allocation collect +
  reports.  Node failure loses only in-flight points (resumable shards).
  `sweep_parallel.phase0` refactor: stop serializing the full natural row
  (its convergence prune is gone) — seeds only, then all rows in parallel.
  Node packing from a benchmark (6×12 / 8×10 / 10×8 procs×omp), not
  assumed.
- **Storage:** MFS MSes to $SCRATCH first; after a wave's collect
  validates, selectively retain only expensive main-class track MSes on
  $WORK ($1 TB quota, ~10 GB used).  Results CSVs + manifests are the
  durable asset.  REJECTED: simulating few frequencies and replicating
  channels (loses the intended uv coordinates).

## Pilots (gate production; ~1–2 queue slots, few node-hours)

1. **Cost/packing benchmark:** fit the cost model; pick node packing;
   sm.corrupt MaxRSS check.
2. **nchan convergence:** core + main, Band 4 snapshot first, using
   nchan ∈ {27,54} (0.5 and 0.25 GHz channels), 10–12 lattice points (natural ×
   {0, mid, coarse taper}; robust {−2, 0, +1.2} × {0, mid, coarse}).
   Adopt 27 if 27→54 gives |Δeta|/eta < 0.5%, |Δb|/b < 1%, envelope
   p95 |Δeta|/eta < 1% (max 2%), and endpoints stable to 1%. Expand the
   trial set only if this focused comparison fails.
3. **Noise A/B** (equal vs receiver-weighted channels) at band 2.
   → **bmason checkpoint** on nchan rule + noise policy before the wave.

The first, simulation-only half of items 1–2 is launchable without pinning the
production manifest:

```bash
bash curvegen/submit_mfs_snapshot_sim_pilot.sh
```

It uses one Slurm queue slot and runs core/main snapshot MS creation for
`nchan=27,54`, recording `/usr/bin/time -v` in per-run logs. Every
nchan is isolated by `NGVLA_CAMPAIGN_VARIANT`, so the runs cannot collide with
one another or with production artifacts. This launcher does not run tclean or determine
convergence; the imaging half of the pilot and the bmason checkpoint still
gate production.

## Task breakdown & sequencing

| # | Task | Who/effort |
|---|------|------------|
| MFS-1 | Retrospective reduced-lattice validation (envelope replay, no CASA) | Sonnet 5 / GPT-5, medium |
| MFS-2 | Band axis: config/simulate/sweep + manifest + schema/registry | Fable 5 spec, codex gpt-5.6-sol build, high |
| MFS-3 | Benchmarks + pilots + analysis (bmason checkpoint after); isolated snapshot simulation/RSS launcher built 4 Sep | Sonnet driver, Fable analysis, med/high |
| MFS-4 | PyLauncher wave runner (in-job prep→caps→sweep→collect) | Fable spec, codex build, high |
| MFS-5 | collect/report/registry band routing + combined-report keys | initial native point-source path built 4 Sep; review/QA remains |
| MFS-6 | Docs (RUN_CAMPAIGNS wave sheet, README, memo) + QA | small model, low |

Order: MFS-1 ∥ MFS-2 → MFS-3 (checkpoint) → MFS-4/5 → wave 1 (track) →
wave 2 (snapshot) → MFS-6.

**Interplay:** the revF/track POLISH campaign (mono; still unlaunched,
queue currently empty) needs ~8 queue slots by itself — launch it FIRST;
MFS code work proceeds concurrently and the pilots take slots once its
array drains.

## Open items / risks

- Noise-weighting policy (A5) — bmason decides post-pilot.
- Fine-end (negative-robust) nchan convergence may stall — bounded outs:
  finer second MS for those rows only / cap+flag the MFS fine end /
  document as convention; reconvene if hit.
- PyLauncher availability/behaviour on Stampede3 — verify module at build
  time; srun-farm fallback designed.
- imsize-15000 (main) is the cost/convergence risk concentration; band 2
  (f_bw 1.10) is the physics stress case — both are pilot targets.
- Later waves (explicitly deferred): LONG combos, revD, imaging curves
  (lattice interior fill + skirt constraint), band-6 tuning axis,
  selector-facing band API.

---
split_from: docs/plans/PLAN.md (lines 1083-1324 at commit 7f0a63f)
history: git log --follow docs/plans/PLAN.md
---
### MFS broadband continuum campaigns (16 Jul 2026 — IMPLEMENTATION IN PROGRESS)

*The MFS-3 pilot definition below is superseded by `docs/plans/MFS_CAMPAIGN_PLAN.md`
(Band 4 snapshot, core+main, nchan 27 vs 54); rolling status is in
`docs/worklog/mfs-campaigns.md`. Band 4 only, nchan 32 pinned 6 Sep 2026 (D1),
other bands scaled from Band 4.*

**4 Sep 2026 status:** Ka/band4 routing, channelized RR/LL simulation and MS
validation, immutable manifests, pinned MFS tclean settings, fresh adaptive
sampler foundations, native-schema collect/report routing, and CASA-free tests
are built. A one-slot, simulation-only snapshot nchan/RSS pilot launcher is
ready (`curvegen/submit_mfs_snapshot_sim_pilot.sh`); its per-nchan campaign
variants keep pilot artifacts separate from production. Production remains
gated on the full V1 replay/limiting-envelope checks, tclean convergence and
noise-policy pilots, bmason's nchan/noise checkpoint, and the MFS-4 adaptive
wave runner. The legacy `submit_campaign.sh` is not an MFS launch path.

New campaign kind: per-BAND broad-band MFS continuum taperability curves
(bmason directive).  Design consulted with codex gpt-5.6-sol xhigh
(`tmp/mfs_campaign_consult{,_out}.md`); its findings are adjudicated inline
below (all accepted except where noted).

**Scope decisions (bmason, AskUserQuestion 16 Jul):** *(reconfirmed as D6,
6 Sep 2026, in `docs/worklog/mfs-campaigns.md`; that is the current source
of truth if this list ever drifts from it.)*
1. revF only, subarray set = homogeneous + main (7 SAs: core-inner, core,
   spiral, mid, core+spiral, spiral+mid, main; core+mid stays excluded, LONG
   combos + revD deferred to a later wave).
2. Bands 1-6, each = ngECT `receiver_data.pkl` `freq_center` ± `max_bw`/2:
   2.4±1.15, 8±4.4, 16±4.1, 27±6.75, 41±10, 93±10 GHz.  Band 6 uses the
   20 GHz instantaneous bw, NOT its 70-116 RF span.  Fractional bandwidths
   f_bw = 0.96, 1.10, 0.51, 0.50, 0.49, 0.215.
   [Deferred 6 Sep 2026: Band 4 only; see the italic note above]
3. **Point-source curves only** initially; both sim modes (track 4 h /
   snapshot, 60 s dumps as now).  nchan set by a convergence PILOT (below),
   analytic floor first, minimum 16.
4. Lattice per (SA, band, mode): **complete coarse tensor product** (codex
   correction of my axes+token-interior idea — refine can't discover a
   smooth interior branch BELOW the envelope it sees): robust
   {-2,-1.2,-0.4,0.4,1.2,2} × (taper 0 + every 2nd canonical log taper),
   PLUS the full natural+taper row and all 11 robusts at taper 0
   (~68-84 pts vs 180-228 full).  Complete cells preserve bilinear
   interpolation; resumable fill-in later for imaging curves.

**Channel-count criterion (the tractability question, settled):** the
analytic "no grating artifacts anywhere in the image" criterion
(nchan ≈ f_bw·imsize/OVERSAMPLE ≈ 900-3300 for band 2)
[Deferred 6 Sep 2026: Band 4 only; see the italic note above] is the WRONG
yardstick — eta is a global weights functional dominated by well-filled
inner uv cells, the beam/skirt/profile use ≤3 FWHM, and even the real
correlator is discrete.  The sim also does NOT model intra-channel
(finite-width) smearing, so the protected FOV must be stated explicitly:
convention = **3 synthesized-beam FWHM at ≤1% sinc loss** → analytic floor
nchan ≥ 38.5·f_bw → {64, 64, 32, 32, 32, 16} for bands 1-6 (pow2-rounded).
Production nchan = pilot result: core + main, band 2, BOTH modes,
nchan ∈ {16..512}, 10-12 lattice points (natural×{0,mid,coarse taper},
robust {-2,0,+1.2}×{0,mid,coarse}), pass = TWO consecutive doublings with
|Δeta|/eta<0.5%, |Δb|/b<1%, envelope p95 |Δeta|/eta<1% (max 2%), endpoints
stable to 1%; then N_b = max(16, pow2ceil(N_B2·f_bw,b/1.10)), validate
bands 1+6 as endpoints.  Known risk to watch: negative-robust rows lean on
sparse outer uv cells (comb effect largest) — if convergence stalls there,
options are a finer second MS for those rows only / cap+flag the MFS fine
end / document; reconvene with bmason.

**Noise-weighting decision (NEW, codex):** equal 1-Jy-per-channel noise
isolates geometric uv filling but ignores receiver Tsys/eta_A variation
across wide bands (worst: bands 1-2).
[Deferred 6 Sep 2026: Band 4 only; see the italic note above]  Pilot A/Bs equal-weight vs
per-channel inverse-variance (from receiver_data.pkl) at band 2; bmason
decides after.  v1 default = equal-weight, explicitly labeled in schema +
report ("geometric uv-filling convention").

**Config/schema design:**
- `NGVLA_BAND` env ("" = legacy mono 30 GHz; "band1".."band6"); suffix
  "-<rev>_<mode>_<band>"; registry `config_registry.csv` gains columns
  band, ref_freq_ghz, freq_lo_ghz, freq_hi_ghz, nchan, curve_types,
  noise_policy (empty for the 4 legacy rows); ALL lookups become
  (rev, sim_mode, band) — collect, CurveLibrary.for_config, make_report,
  campaign_tasks; the combined report's payload keys must include band
  (today rev_mode only — six bands would overwrite each other).
- Curve CSVs carry NATIVE band-center resolutions in NEW columns —
  band-native data must NOT be written into `*_30ghz` fields, and MFS
  curves are NOT ∝1/f scalable (fixed receiver windows are not
  self-similar; band 6 tuning would need its own axis later).  Selector
  exposure beyond `for_config` is out of scope for v1 (report + CSVs are
  the deliverable).
- simulate.py: nchan channels spanning [freq_lo, freq_hi];
  **`sm.setspwindow(freq=)` takes the FIRST CHANNEL CENTER** (f_lo+Δf/2),
  not the band center (codex catch); stokes **"RR LL"** (cross-hands can't
  contribute to a noise-only Stokes-I sim; halves MS size); post-sim
  assert on CHAN_FREQ edges + dump count.
- sweep.py: pin `specmode="mfs", reffreq=<center>, nterms=1,
  deconvolver="hogbom", stokes="I", parallel=False`; **cell sized at the
  TOP-of-band frequency** (highest channel), seed-checked bmin ≥ 5 px;
  eta referenced to the same-combo MFS natural seed (per-band caps via the
  existing fill_beam_caps two-step — main is the one capped SA in set).
- **Campaign manifest** (per-combo JSON in its results dir): band edges,
  nchan, correlations, noise policy, cell policy, lattice version, CASA
  version; make_ms()/run_point() validate before reusing an MS or
  appending to a results CSV (guards the "resumable sweeps preserve stale
  conventions" gotcha class for the new axis).
- refine.py gains `--curves {both,ptsrc}` (CURVE_SPECS currently always
  builds both); **fill_grid.py must NOT run** for reduced-lattice combos
  (it would refill the full canonical lattice) — campaign wave runner
  omits it, and fill_grid itself gets a manifest guard.
- Lattice reduction validated RETROSPECTIVELY before anything is built:
  replay the four existing mono campaigns' full lattices through the
  reduced-lattice mask and compare reduced vs full ptsrc envelopes for all
  SAs/modes (pure sa_select/envelope replay, no CASA).  Acceptance: p95
  |Δeta|/eta < 2% in-band; worse → densify the interior.

**Parallelism (8-queued-jobs cap):** ONE multi-node allocation per wave
(queue cost 1 slot) instead of the 3-job chain × array elements: 8-16 icx
nodes, **TACC PyLauncher** (supported dynamic task farm; fallback = the
simple srun --exact farm if pylauncher misbehaves — verify module at build
time) over full-node work units = (band, SA); in-job phases: prep (cfgs +
sims/seeds, dynamic) → barrier: fill_beam_caps + verify per band →
dynamic sweep units (sweep_parallel + refine --curves ptsrc; NO fill_grid)
→ completeness check → in-allocation collect + reports for complete
combos.  Node failure = lose in-flight points only (resumable shards);
resubmit continues.  sweep_parallel.phase0 refactor: stop serializing the
full natural row (the convergence prune it fed is gone) — seeds only, then
natural + Briggs rows launch together (wall ≈ longest row).  Node packing
set by a benchmark (6×12 / 8×10 / 10×8 procs×omp on main at production
nchan; record wall, MaxRSS, scratch high-water) — do not assume 10×8.

**Storage (1 TB $WORK quota, ~10 GB used):** 7-SA set ≈ 12.5M track rows;
RR LL DATA ≈ 48 GB at Σ240 chans (~1.2-1.5× with FLAG/overhead) — fine.
Policy: MFS MSes to **$SCRATCH first**; after a wave's collect validates,
selectively retain only the expensive main-class track MSes on $WORK
(NGVLA_MS_BASE routing unchanged); results CSVs + manifest are the durable
asset; regen sbatch covers purges.  sm.corrupt MaxRSS benchmarked at
64/128 chans before any 512-chan sim (no documented streaming guarantee).
REJECTED (codex raised, agreed rejected): replicating a few simulated
frequencies into many channels — loses the intended uv coordinates.

**Cost model:** per-point T = A(imsize) + B·N_bl·N_dump·N_chan·N_corr,
FITTED from a 4-point benchmark (nchan 1/16/64/prod × imsize 4096/15000 ×
mode) — not the hand-waved gridding-fraction model (codex corrected my
arithmetic).  Wall per (SA, band) ≈ longest row × per-point time given
row-parallelism (~2.5-6 node-h at 10-20 min/pt).  Whole track wave
plausibly 150-400 node-h IF points stay 10-20 min; snapshot wave ~free.
Dominant risks: imsize-15000 Briggs convergence forcing big nchan;
I/O-bound gridding; receiver-weighting changing the pilot result; memory
capping concurrency; coarse lattice missing a hybrid branch; long
allocation hitting walltime/node failure.

**Task breakdown (model/effort per CLAUDE.md convention):**
| # | Task | Anthropic | OpenAI | Effort |
|---|------|-----------|--------|--------|
| MFS-1 | Retrospective reduced-lattice validation (envelope replay) | Sonnet 5 | GPT-5 | medium |
| MFS-2 | config/simulate/sweep band axis + manifest + schema/registry | Fable 5 spec, codex build | gpt-5.6-sol | high |
| MFS-3 | Benchmarks+pilots (cost 4-pt, packing, sm.corrupt RSS; nchan convergence; noise A/B) — 1-2 queue slots | Sonnet 5 driver, Fable 5 analysis | GPT-5 | medium/high |
| MFS-4 | PyLauncher wave runner (in-job prep→caps→sweep→collect) | Fable 5 spec, codex build | gpt-5.6-sol | high |
| MFS-5 | collect/report/registry band routing + combined-report keys | codex build, Claude review | GPT-5 | medium |
| MFS-6 | Docs (RUN_CAMPAIGNS wave sheet, README, memo section) + QA | Sonnet 5 | GPT-5-mini | low |

Sequencing: MFS-1 (cheap, gates the lattice) ∥ MFS-2 → MFS-3 (pilot gates
production nchan + noise policy — bmason checkpoint) → MFS-4/5 → wave 1
(track) → wave 2 (snapshot) → MFS-6.  Interplay: revF/track POLISH campaign
(still to launch, queue empty) uses ~8 slots by itself — launch it first;
MFS code work proceeds concurrently; pilots submit once its array drains.

**Where things stand.** 14 offered subarrays now: the homogeneous set
(core-inner, core, spiral, mid, core+spiral, spiral+mid, main) PLUS the
memo-121 long+outer-core campaign (long, mid+long, spiral+mid+long, main+long,
spiral+core-outer, mid+spiral+core-outer, long+mid+spiral+core-outer). Curves
come from the shared engine (`sa_select/envelope.py`): row+column edge
interpolation PLUS **bilinear cell interiors** (7 Jul 2026), eta–skirt 1:1
trade about skirt 0.10 up to +0.15 span. Report:
`curvegen/reports/revf-curves.html` (dense engine curves, in-page subarray
calculator card). core+mid measured but DROPPED from the offered set (bmason).
62 tests green (`casapy -m unittest discover -s tests -t .`). The homogeneous
set is refined/smooth; the campaign set is coarser (see item 1 caveats).

**In flight / open items (owner: next agent):**
1. **memo-121 campaign: DONE + ADDED TO THE REPORT (7 Jul 2026, Opus).**
   Campaign finished (all 4 heavy long-combos, 0 failed). All 7 new subarrays
   (long, mid+long, spiral+mid+long, main+long, spiral+core-outer,
   mid+spiral+core-outer, long+mid+spiral+core-outer) added to
   `sa_select/data/subarrays.csv` (n_ant/b_min/b_max from the combined
   `.cfg`s; las_coeff 0.8; calc_name blank→donor-rescaled where the pkl lacks
   them, all already in `sensitivity._DONOR_N_ANT`) and to `make_report.ORDER`
   (+7 color slots in `report_template.html`, dataviz-checked for
   normal-vision separation; 14 categorical colors exceed CVD-distinctness so
   the report leans on its existing secondary encoding — labels, legend,
   per-subarray small multiples, data table, interactive highlight).
   `collect.py` → 3206 samples; report regenerated with the bilinear engine.
   **bmason authorized adding them (7 Jul); Long b_min is RAW (spurious ~37 m
   shorts NOT filtered — bmason: "probably not a substantial impact"), so
   Long-family LAS (~45″) is overstated — flagged in the subarrays.csv note;
   apply a ~150 m cut if LAS ever binds.** DATA CAVEATS for the new sweeps
   (they are coarser than the refined homogeneous set, NOT engine issues):
   Long-family imaging curves are steppy at the fine end (main+long worst
   adjacent eta step 0.91, spiral+mid+long 0.50 — relaxation↔trade-cap
   regime transitions with few samples); `long` has ~14 points with eta<1
   (min 0.965, single-noise-realization scatter). Run `refine.py` on the
   long-family to smooth them when compute is available.
2. **Bilinear cell interior: IMPLEMENTED + VALIDATED (7 Jul 2026, Opus).**
   `sa_select/envelope.py` now adds a 2-D bilinear interpolant over four
   lattice-adjacent (robust, taper) corner points (`Cell`, `build_cells`,
   `_cell_candidates`, wired into `_candidates` + `solve`). log(res),
   log(eta), skirt are bilinear in normalized cell coords (s,u); at a target
   resolution the constrained optimum's critical points along the res-locus
   are enumerated analytically (eta-stationary + skirt-stationary +
   skirt=level crossings = closed-form quadratics; penalized eta+skirt
   stationary via deterministic scan + golden refine). Cells form ONLY where
   all four edges are free of intervening measured points, so a cell edge
   coincides exactly with a row/column segment and can never undercut a more
   accurate 1-D fit. Design pre-consulted with codex (gpt-5.5 xhigh:
   confirmed the quadratic reductions; its guards folded in — singularity
   split, skirt-stationary for relaxation, non-unimodal penalized scan).
   **Validation:** brute-force 2-D locus-scan oracle on all 7 Rev F
   subarrays × 161 resolutions → engine J − oracle J = 0.000 (pinned,
   `TestBilinearRealData`); held-out recovery (drop the probe rows → bilinear
   reproduces the admissible interior, median interp error 0.18–2.7% eta,
   ~0.001 skirt in the operating range eta≤3); 58 tests green under casapy
   (+6 new, `TestBilinearCells`). **Current-data impact is small** because
   the probe rows are already measured; the value is generalizing the probe
   (no need to measure every intermediate row) and removing the edge-only
   deficiency for future/coarser sweeps. **main's residual ~9.5-mas step
   (0.255) is NOT interpolation error** — the oracle confirms no admissible
   skirt≤0.25 interior point exists there; it is a genuine trade_max=0.25
   hard-cap frontier feature (a J-lower point sits at skirt 0.253, excluded
   by the cap). Smoothing it needs a trade-policy change (bmason) or a
   targeted measurement, not an engine change.
3. **Calculator verification: DONE — JS VERIFIED (7 Jul 2026, Opus).**
   Replicated the report JS numerically against `sa_select` + the memo-96
   calculator on the report's own embedded DATA (30 GHz, 0.01", imaging,
   1000 MHz, 10 uJy/beam). Three-way agreement:
   | SA | sa_select engine | report JS | old handoff ref |
   |----|----|----|----|
   | main | eta 1.800 | eta 1.808 | eta 1.891 (STALE) |
   | spiral+mid | eta 1.237 | eta 1.242 | eta 1.237 ✓ |
   | mid | eta 1.618 | eta 1.640 | eta 1.618 ✓ |
   - eta selection: JS matches the envelope engine to ≤1.5% (residual =
     report's 0.01-dex dense-grid + the JS's own ±5% window re-min; not a
     logic fork).
   - σ_nat: JS log-log interpolation at 30 GHz matches
     `sensitivity.natural_rms` to <0.05% (main 20.42, spiral+mid 43.80,
     mid 95.79 uJy/beam @ 1h/1MHz).
   - t/ant-hr formula tHours=(eta·σ/S)²/bw, antHr=tHours·N reproduced.
   - **The one mismatch (main 1.891) is a STALE reference number**, not a
     calculator bug: it predates the latest main re-sweep (main.csv
     13:44 Jul 7). Current authoritative main eta @10 mas ≈ 1.80, which the
     JS reproduces. spiral+mid & mid refs match the engine exactly.
4. **Memo**: `memo/ngvla_sa_selection.tex` compiles (8 pp); needs bmason
   read + real figures (placeholders marked).
5. **COMMITTED: v4 (f1a02da)** — bilinear engine + 14-subarray report; and
   the refine sbatch (c8a4bdc). Working tree clean except untracked
   `docs/plans/NEXT_AGENT.md` / `docs/_needs-triage/futureDev.md`. 62 tests green.


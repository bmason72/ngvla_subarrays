---
split_from: PLAN.md (lines 989-1082 at commit 7f0a63f)
history: git log --follow docs/plans/PLAN.md
---
### PSF inspector plan (15 Jul 2026 — designed; P3+P4 BUILT 16 Jul; P1+P2 BUILT 21 Jul)

**Status 16 Jul 2026:** P3 (`curvegen/export_psf_data.py` + collect-stage
wiring + `tests/test_export_psf.py`) and P4 (the report's "PSF inspector"
card) are BUILT — implemented by codex (gpt-5.6-sol, build mode — its TACC
sandbox works again; probe before relying on it) to Claude's specs, then
Claude-reviewed line-by-line + subagent-QA'd + esprima-gated.  31 payload
files (~5.3 MB) exported for the three combos with profiles; revF/track
correctly skips until its profiles exist (polish refine points + P2
backfill).  Entry points wired: subarray dropdown, heatmap-cell click,
small-multiple-mark click, calculator per-row "PSF" button
(nearest-measured-key resolution).  P1 (axis-cut capture) and P2 (anchor
backfill) were BUILT 21 Jul — see the 21 Jul part-2 delta; backfill runs
ride the 21 Jul campaign wave (RUN_CAMPAIGNS.md).

bmason's decisions (AskUserQuestion, 15 Jul): **(1)** azimuthal profiles AND
major/minor-axis cuts (cuts need a capture extension; they expose the
snapshot elongation the azimuthal average hides); **(2)** display scope =
FULL lattice, lazy-loaded (report no longer one self-contained file — the
`reports/psf/` payload dir travels with the HTML); **(3)** anchors-only
backfill; **(4)** polish campaigns launch now, PSF work proceeds in
parallel.

**Data situation:** results-{revF_snapshot,revD_track,revD_snapshot}/
profiles/*.jsonl already hold an azimuthal radial profile for EVERY measured
point (~7.2k profiles; capture feature v11).  revF/track has NONE (its
points predate v11).  Axis cuts exist nowhere yet.

**Sequencing constraint (important):** the polish campaigns MOVE the
envelope anchors, so the anchor backfill (P2) must run AFTER polish lands.
Polish refine points get azimuthal profiles automatically (CAPTURE_PROFILES
is on everywhere — this also starts populating revF/track's empty
profiles/); the post-polish backfill then adds cuts at the settled anchors.
If P1 happens to land before bmason submits polish, polish points carry
cuts natively — a bonus, not a dependency.

**P1 — capture extension** (`curvegen/measure.py`, `sweep.capture_profile`).
New pure-numpy `psf_axis_cuts(cutout, center, cell_arcsec, bpa_deg, r_max,
n=81)`: bilinear-sample the PSF along the fitted-beam major & minor axes,
signed radius ±r_max (= 3 x res_geo, matching the radial profile).  JSONL
line gains `bmaj_arcsec, bmin_arcsec, bpa_deg, cut_r_arcsec, cut_maj,
cut_min`; old lines stay valid (missing cut fields => "azimuthal only").
CASA-free unit test alongside tests/test_measure_profile.py.
[Sonnet 5 / GPT-5, medium]

**P2 — anchor backfill** (`curvegen/backfill_psf.py` + `backfill_psf.sbatch`,
job array over the 4 combos; run AFTER polish).  Anchor set per subarray =
env_keys of the s0=0.10 imaging curve + the ptsrc curve (build_curve over
collected samples, exactly like refine) + the natural point.  For each
anchor lacking a cut-bearing JSONL line: re-image with the EXACT recorded
convention (weighting/robust/taper; imsize; **cell from the results row's
cell_arcsec**, NOT recomputed; uvrange from config) with results-CSV
recording DISABLED — backfill must never touch curve data — then append the
profile+cuts line (loader: last line per key wins).  Resumable by skipping
cut-bearing keys.  Covers revF/track profiles+cuts and the other three
combos' anchor cuts in one pass; a few node-hours.
[Opus 4.8 / GPT-5, high — the convention-reuse details are where bugs live]

**P3 — payload export** (`curvegen/export_psf_data.py`).  profiles JSONL ->
`curvegen/reports/psf/<rev>_<mode>/<sa>.js` script files:
`window.PSF_REGISTER("<combo>/<sa>", {key: {...}})` — script-tag JSONP, NOT
fetch(), because Chrome blocks fetch() on file:// and these reports open as
local files.  ~0.2-0.5 MB per (combo, subarray).  Wire into
campaign_collect.sbatch (per-combo) and the --combined build (all combos).
[Sonnet 5 / GPT-5-mini, medium]

**P4 — report UI panel** (`report_template.html` + make_report).  New "PSF
inspector" card: subarray dropdown + point selection three ways — (a) a
"show PSF" affordance on each calculator result row (its chosen operating
point, nearest measured anchor), (b) CLICK any heatmap cell or
small-multiple mark, (c) default = natural point.  Plot: azimuthal profile
+ both cut arms (major/minor) vs radius; annotate r=1 FWHM vertical, the s0
threshold horizontal, the measured skirt dot; text line with bmaj x bmin @
bpa, axis ratio, eta, skirt.  The current plot uses an in-SVG legend at upper
right and a continuous piecewise-linear radius scale: 0--3 FWHM occupies the
left half and 3--10 FWHM the right half.  Only the robust core Gaussian is
overlaid; the incorrect 2x-measured-FWHM Gaussian was removed.  Lazy-load via
injected <script> per
(combo, subarray), cached; graceful states: "cuts pending backfill"
(azimuthal-only line) and "no PSF captured for this point" (revF/track
non-anchors until backfill/full pass).  Re-render-safe like every other
panel (renderAll clears it; pending loads guarded against stale combo).
[Fable/Opus 4.8 / GPT-5, high — fiddly SVG/JS, follow the renderAll rules]

**P5 — docs + QA.**  README/RUN_CAMPAIGNS notes (psf/ dir must travel with
the HTML), PLAN update, spot-check elongated snapshot beams (mid+long) and
a relaxed imaging point.  [any small model, low]

Build-time defaults (flag if changed): cut length 3 x geometric-FWHM, 81
samples/arm; positive-r overlay with both arms drawn light; heatmap click
also switches the panel's subarray.  Optional follow-on if anchor coverage
feels sparse on revF/track: full-lattice backfill for that combo only
(~3.2k tcleans, hours on one node).


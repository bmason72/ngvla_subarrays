# Design: curves as the durable product (curveRefactor)

Status: design note, 7 Sep 2026. Written per bmason's wishlist item
"curveRefactor" (`docs/plans/wishlist.md`), after the architecture consult
in `docs/worklog/wishlist-consult-2026-09-07.md`. bmason approved writing
this note now; implementation is a separate, later task. No code changes
here.

## Problem

Today the durable artifact is the raw sweep sample table
(`sa_select/data/*_curves.csv`). Every consumer re-derives curve values
from it at load time:

- The selector (`sa_select/curves.py::CurveLibrary.envelope`) builds a
  `sa_select.envelope.Envelope` from the samples CSV and runs its
  row/column/bilinear-cell interpolation (`sa_select/envelope.py`, ~950
  lines) on every process that imports it.
- The report builder (`curvegen/make_report.py::build_curve`) builds the
  same kind of `Envelope`, then re-evaluates it on a fixed log-resolution
  grid (`GRID_DEX = 0.01`, `make_report.py:54`), once per skirt setpoint
  (`SKIRT_SETPOINTS = [0.05, 0.10, 0.15, 0.20]`, `make_report.py:56`) plus
  once for point-source. This dense grid, not the analytic envelope, is
  what ships to the browser.
- The calculator JS (`curvegen/report_template.html::lookupCurvePoint`)
  does not run the engine's algebra at all: it filters the baked grid to
  the requested beam-margin window and picks the min-eta (or
  min-eta-under-skirt) point in it. This is a simpler algorithm than
  `Envelope.solve`/`solve_interval` (no cell-interior search, no exact
  threshold-crossing interpolation, resolution snapped to the 0.01-dex
  grid). The comment says it "mirrors" the engine's policy; it mirrors the
  policy, not the evaluation.

Measured costs (commands used are noted inline; all read-only):

- Raw sample counts: `wc -l sa_select/data/*curves*.csv` gives 199 to 6,971
  lines per combo (`bootstrap_curves.csv` 199; `revd_snapshot_curves.csv`
  2,436; `revc_track_curves.csv` 3,856; `revf_snapshot_curves.csv` 3,993;
  `revd_track_curves.csv` 5,411; `revf_curves.csv` 6,971). Within one combo,
  per-subarray sample counts run 116 to 494 rows (revF track, from the
  built report below).
- Re-densification inflates the shipped product. In
  `curvegen/reports/revf-curves.html`, the embedded `INJECTED` JSON blob
  (extracted with a Python `json.loads` on the `const INJECTED = ...;`
  slice) is 2,801,822 bytes. Its raw `samples` section holds 3,159 points
  across 14 subarrays. Its baked curves hold 4 skirt setpoints x 14
  subarrays x ~245 grid points each (~13,720 points) plus a point-source
  set of 14 x 245 = 3,430 points -- ~17,150 evaluated points from 3,159 raw
  ones, a 5.4x expansion, for one combo, before PSF data. The four
  setpoint curves are near-duplicates wherever the skirt constraint does
  not bind.
- PSF payloads dominate report size. `du -sh curvegen/reports/psf` is 104
  MB total (revC_track 31 MB, revD_track 29 MB, revF_track 28 MB,
  revF_snapshot 14 MB). One file,
  `curvegen/reports/psf/revF_track/main.js`, is 3,163,966 bytes for 403
  anchors (parsed with `json.loads` after stripping the
  `window.PSF_REGISTER(...)` wrapper), ~7.9 KB/anchor. Each anchor carries
  an axis-cut pair (`cut_maj`/`cut_min`, 271 floats each) and a radial
  profile pair (`r_arcsec`/`psf`, 134 floats each, per
  `docs/architecture/PSF_DIAGNOSTICS.md`'s `CAPTURE_RMAX_FWHM=10`) plus
  ~18 scalar metrics. No full 2-D PSF image is stored anywhere today.
- Report file sizes (`ls -la` / `du -h`): the lazy-PSF combined report
  `curvegen/reports/ngvla-curves.html` is 14 MB (13,980,050 bytes); the
  release build that inlines gzip+base64 PSF payloads is 45 MB
  (`ngvla-curves-release.html`, 46,954,540 bytes; an earlier snapshot,
  `ngvla-curves-release-24aug26.html`, is 28 MB). `report_template.html`
  alone is 106 KB.
- Two independent implementations of "operating point near resolution
  theta" exist (Python's exact engine, JS's grid-snap-and-filter), aligned
  only by comments and review, not a shared contract. This has already
  bitten once: `docs/architecture/PSF_DIAGNOSTICS.md` documents the
  PSF-nearest-anchor lookup drifting from the curve's weighting family,
  caught only by a dedicated replay test
  (`tests/test_psf_lookup_replay.py`).
- Any envelope-algorithm change (gating constants, a new curve-limits
  gate per `docs/plans/curve-limits-spec.md`) forces a full re-run of
  `collect.py` and `make_report.py` over every combo to regenerate grids
  and re-embed PSF, even when the underlying samples are unchanged.

## Proposed durable product

One versioned JSON "curve product" per (rev, sim_mode, band, subarray,
curve type), curve type being `ptsrc` or `imaging`. This is the evaluated
envelope itself, not a re-sampling of it.

**Identity**: `rev`, `sim_mode`, `band` (blank for mono combos),
`subarray`, `curve` -- the same key `config_registry.csv` and the proposed
`curve_limits.csv` (`docs/plans/curve-limits-spec.md`) already use, so all
three thread through without translation.

**Vertices plus connectivity**: the hygienic `Point` list (res, eta,
skirt, weighting, robust, taper, capped flag -- small, 116 to 494 per
subarray as measured above); the row and column segment edge lists
`build_segments` computes (which adjacent point pairs actually connect,
after taper/resolution/robust-gap gating); the bilinear cells `Cell`
builds, by corner point indices. Serialize the *result* of gating, not a
rule for re-deriving it -- re-deriving connectivity from constants at
evaluator time is the duplicated-logic problem being removed. The
algorithm version and its parameters travel as provenance (below) so
edges can be regenerated and diffed when the algorithm changes.

For the imaging curve, replace the fixed `GRID_DEX` grid with the exact
breakpoints the engine already computes in closed form: segment/cell
boundaries and skirt-threshold crossings (`Segment.skirt_crossings`, the
`Cell` critical-point solver). The piecewise log-linear/bilinear
interpolants are fully determined by their breakpoint values, so this
removes grid aliasing and the spacing-constant dependency, and is
typically far fewer points than a 0.01-dex grid (bounded by the vertex
count, not by grid density).

**Units, interpolation, support**: resolution units/reference (arcsec at
30 GHz mono, or at the MFS band's `ref_freq_ghz`); the interpolation
rules already in `sa_select/envelope.py`'s docstring (log(eta) and
log(taper) linear in log-resolution along a row/column; skirt linear in
log-resolution; bilinear in (robust, taper) inside a cell); the coverage
interval(s) including interior gaps (never bridged); a hook for
`curve-limits-spec.md`'s manual interval, kept separate from computed
support, intersected once by the shared evaluator (below).

**Provenance**: an envelope algorithm version bumped on any semantic
change to `build_segments`/`derive_robust_gap_limit`/`Cell`, plus the
gating parameters in force; a checksum of the consumed samples rows; the
archive path of the source samples CSV; a pointer from
`campaign_manifest.json` to the product version last exported from it.

## PSF attachments

Today's per-anchor export already offers the two candidate
representations side by side (see measurements above): axis cuts (542
floats) and a radial profile (268 floats), ~7.9 KB/anchor total. A modest
128x128 float32 2-D cutout would be ~64 KB/anchor, ~8x today's payload,
before any azimuthal sampling needed to see the skirt off-axis.

The radial profile supports everything the report currently does with
PSF data -- half-power width, the skirt/shoulder metric, first-null and
confusion integrals, the PSF-inspector plot -- all azimuthally-averaged or
single-radius quantities. The axis cuts add beam ellipticity/asymmetry
near the major/minor axes at a known, already-paid cost.

**Recommendation**: attach the radial profile plus axis cuts by stable
anchor ID (matching today's `"{weighting}_{robust}_{taper_mas}"` keys), and
do not add full 2-D PSF storage to the routine per-lattice-point export.
`docs/architecture/PSF_DIAGNOSTICS.md`'s own "reduced final-point
campaign" section already reserves full 2-D products for a small,
deliberately reduced set of final operating points, not the exploratory
lattice; this note adopts that plan rather than a competing one. Do not
retain full 2-D PSFs until that campaign's downstream analysis need is
stated.

## Consumers and the single evaluation contract

Three consumers must read one product the same way: the Python selector
(`Envelope.solve`/`solve_interval`, the reference implementation), the
report builder (already calls the same engine; only its *output shape*
changes, from a dense grid to exact breakpoints), and the calculator JS
(currently an independent, simpler re-implementation -- the actual drift
risk).

Do not reimplement the full engine in JavaScript. Instead, make the
product's breakpoint representation rich enough that a small, identical
evaluator (linear/log-linear interpolation between adjacent breakpoints,
with an explicit "outside support" outcome) suffices in both languages,
and is the *only* thing either language does; the row/column/cell algebra
stays a Python-only *builder* step. Maintain a shared JSON test-vector set
(inputs: subarray, curve type, resolution, skirt threshold, beam margin;
expected outputs: res/eta/skirt/weighting/robust/taper/anchors) covering
interior points, exact breakpoints, segment ends, cell interiors,
skirt-relaxed cases, and support boundaries. Run it from both a Python
test (extend `tests/test_envelope.py::TestBilinearCells`) and a small
JS/headless harness against `report_template.html`'s evaluator, so drift
fails CI instead of waiting for a replay audit like the PSF-lookup one.

## Migration

Additive; never delete samples; keep the old path live until parity is shown.

1. **Export alongside.** New exporter reads the existing samples CSV and
   `Envelope`, writes the JSON product next to the current files. No
   consumer changes.
2. **Parity tests.** Compare the new product's evaluation against
   `Envelope.solve`/`solve_interval` and against the current baked grid,
   for every combo/subarray, at representative resolutions plus every
   exact breakpoint and support boundary. Zero-diff (within float
   tolerance) gates any consumer switch.
3. **Switch one consumer at a time**, lowest risk first: report rendering,
   then calculator JS (behind the shared test vectors), then the selector
   last (it feeds real observing-time decisions), only after the first two
   run in production without a discrepancy.
4. **Keep samples as compressed archival input indefinitely** -- they
   remain ground truth for re-deriving a product at a new algorithm
   version. Record the compressed archive path in each product's
   provenance.
5. **Retire the `GRID_DEX` baking step** in `make_report.py::build_curve`
   only after step 3 completes for the report consumer.

## Risks

- **Freezing an incomplete representation** (the consult's stated
  principal risk): a schema that misses a case the bilinear-cell solver
  produces would silently drop those operating points. Mitigate by
  building the exporter directly from `Envelope`'s actual built segments
  and cells, not a hand-specified subset.
- **Python/JS semantic drift** -- addressed by the shared test-vector set;
  real without it, since this refactor targets removing the *current* form
  of the same risk.
- **Provenance/version skew**: a stale product used after the algorithm
  advances must fail loudly at load, mirroring the fail-closed pattern in
  `curvegen/collect.py::check_cell_convention`.
- **Schedule collision**: implementation must happen in a separate
  worktree and merge only after the running campaign's collect stage is
  checked, per this session's constraint; coordinate branches with the
  parallel curve-limits work, since both touch `sa_select/envelope.py` and
  `curvegen/make_report.py`.
- **PSF scope creep**: "keep a small 2-D cutout just in case" reintroduces
  the bloat this refactor removes. Hold the line at radial profile plus
  axis cuts until the reduced final-point campaign states a concrete need.

## Open questions for bmason

1. One breakpoint set per fixed skirt setpoint (today's four), or a
   setpoint-free skirt-vs-resolution representation letting the calculator
   offer an arbitrary `s0`? The latter is more general but needs
   query-time crossing search rather than baked crossings.
2. Where should products live: `sa_select/data/`, a new
   `sa_select/data/products/`, or under `curvegen/`?
3. For parity testing, every subarray x combo, or a curated representative
   subset (one single-scale array, one multi-scale array, LONG for its
   baseline filter, one skirt-relaxed combo)?
4. Archive the compressed samples in git, under `$WORK/ngvla_curvegen`
   alongside the MS stores, or both?
5. Is a JS-side test harness (headless browser or a Node shim) workable
   given the CASA-only test invocation (`casapy -m unittest discover`), or
   does the parity check need to run outside that path?

## Effort estimate per phase

| Phase | Work | Effort | Anthropic | OpenAI |
| --- | --- | --- | --- | --- |
| 0 | Resolve open questions 1-2; freeze the JSON schema | small | Claude Opus 5 (or Fable 5.1 spec/review) | gpt-6-astra (consult) + gpt-5.6-sol (build, high) |
| 1 | Exporter: serialize built segments/cells/points per combo | medium | Claude Sonnet 5 | gpt-5.6-sol (high) |
| 2 | Provenance: version/params, checksum, archive path, fail-closed load check | small-medium | Claude Sonnet 5 | gpt-5.6-terra (medium) |
| 3 | Parity tests: engine vs. product, all combos, breakpoints + boundaries | medium-large | Claude Opus 5 (or Fable 5.1 spec/review) | gpt-6-astra (consult) + gpt-5.6-sol (build, high) |
| 4 | Shared JS/Python test-vector harness | medium | Claude Sonnet 5 | gpt-5.6-terra (medium) |
| 5 | Switch report consumer | medium | Claude Sonnet 5 | gpt-5.6-terra (medium) |
| 6 | Switch calculator JS | medium | Claude Sonnet 5 | gpt-5.6-terra (medium) |
| 7 | Switch selector (highest stakes, last) | medium | Claude Opus 5 (or Fable 5.1 spec/review) | gpt-6-astra (consult) + gpt-5.6-sol (build, high) |
| 8 | Archive/compress samples; retire grid baking; docs update | small | Claude Sonnet 5 | gpt-5.6-terra (medium) |

PSF attachments (radial profile plus axis cuts by stable anchor ID) ride
along with phase 1 at the same effort tier; no 2-D-PSF work is scoped
pending open question resolution and a stated analysis need.

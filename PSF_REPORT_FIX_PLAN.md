# PSF_REPORT_FIX_PLAN.md — agreed plan (bmason + Claude, 4 Sep 2026)

> Standalone hand-off for a fresh session. Supersedes §3 of `PSF_PLOT_FIX_HANDOFF.md`. Read that file §1–2 for the evidence and the uncommitted worktree state, then implement this.


## Context

Codex's uncommitted worktree (see `PSF_PLOT_FIX_HANDOFF.md`) removed the flawed
"robust core Gaussian" fit but replaced it with a Gaussian at the measured radial
half-power width and added capture-range preference/warning logic. bmason decided
(4 Sep):

- Profiles that stop at r≈3 FWHM are pre-18-Aug captures; the chart already shows
  them honestly. **No range-classification code, no legacy warnings, no lattice
  backfill campaign.** Revert that part of codex's template work.
- The Gaussian reference becomes the **tclean restoring beam** (elliptical volume
  Ω_G = π·bmaj·bmin/(4 ln 2)), which is a genuine 2-D fit CASA already produced. Keep
  the two existing consumers unchanged in form: ΩPSF/Ω_G (∫B dΩ to first null over
  Ω_G) and confusion ∝ sqrt(∫B² dΩ / (Ω_G/2)) (Condon γ=3). Records without
  bmaj/bmin (1,757 Rev D track exploratory points) get no ratio; report "—" and warn.
- MFS `nchan=27,54` edits in the same worktree are separate; second commit.
- Future intent (do not design out): a small sim campaign over a subspace of the
  grid sampling the optimum curves, retaining PSFs and possibly MSs. Codex's
  follow-on paragraph in PSF_DIAGNOSTICS.md already describes this; keep it.

## Changes

### `curvegen/export_psf_data.py::derive_psf_metrics`
- Drop `reference_gaussian_fwhm_arcsec`. Add `restoring_bmaj_arcsec`,
  `restoring_bmin_arcsec` (passthrough from the record when finite and > 0),
  `restoring_fwhm_geo_arcsec` = sqrt(bmaj·bmin), and `gaussian_volume_sr` =
  π·bmaj·bmin/(4 ln 2) in sr. When the beam is absent: omit `gaussian_volume_sr`,
  `psf_to_gaussian_volume_ratio`, `psf_to_gaussian_squared_volume_ratio`.
- Keep `hwhm_arcsec`, `measured_fwhm_arcsec`, first-null logic, `∫B`, `∫B²`,
  `confusion_beam_sqrt_sr` unchanged.
- Docstring: Ω_G is the tclean restoring-beam volume; azimuthal averaging conserves
  ∫B so the volume ratio is exact; ∫B² of the azimuthal average slightly
  underestimates the 2-D value for elongated beams.

### `curvegen/make_report.py::build_psf_metric_summary`
- Compact schema index 2 → `restoring_fwhm_geo_arcsec`; require it (so points
  without a beam are skipped, giving the calculator no metric → "—"). Remove codex's
  index 6 (`cut_rmax_fwhm`). Update the schema comment.

### `curvegen/report_template.html`
- Revert codex's range logic: delete `psfCaptureRangeFwhm`, the `legacy` field in
  `nearestPsfKey` (restore committed ranking), the `row[6]` read, and both
  "legacy capture ends at r≈3 FWHM" branches (restore `axis cuts pending backfill`
  only). `git diff` against `7fd2eaa` for those hunks is the reference.
- `psfMetricForPoint`: expose `restoring_fwhm_geo_arcsec` instead of
  `reference_gaussian_fwhm_arcsec`; `confusionForMetric` uses it as θ.
- Chart: draw one overlay, the circular Gaussian at `restoring_fwhm_geo_arcsec`,
  dashed ink, legend row "restoring beam (geo-mean FWHM)", only when present.
  Legend lists drawn curves only; keep `r=1 FWHM` label and x-title.
- `renderPsfParams`: "restoring beam bmaj × bmin" and its FWHM; when absent, append
  "no restoring beam recorded; Ω ratios unavailable".
- Calculator table tooltip, inspector text, and QA footnote: Ω_Gaussian = tclean
  restoring-beam volume; confusion scaling = sqrt(∫B²/∫G²), Condon γ=3.
- Rows with no metric already print "—"; MFS path already flags "confusion
  unavailable". No new fallback.

### Tests
- `tests/test_export_psf.py`: synthetic Gaussian record with bmaj=bmin=1″ →
  `gaussian_volume_sr` = π/(4 ln 2) arcsec² in sr, ratio ≈ 1 to first null; elliptical
  bmaj≠bmin uses the product; record without beam → no ratio fields; no
  `gaussian_fit_fwhm_arcsec` / `reference_gaussian_fwhm_arcsec`.
- `tests/test_psf_report_metrics.py`: compact row length 6, index 2 = geo-mean beam
  FWHM; template contains `restoring_fwhm_geo_arcsec`, "restoring beam", not
  `drawGaussian(Number(entry.gaussian_fit`, not "robust core Gaussian", not "legacy
  capture ends"; remove codex's `candidate.legacy` test.
- `tests/test_report_calculator.py`: swap the reference-FWHM assertions for the
  restoring-beam wording.

### Docs
- `PSF_DIAGNOSTICS.md`: rewrite to the decisions above (short captures are
  pre-upgrade data, left as is; Ω_G now restoring beam; Rev D exploratory
  points lack beams). Keep the follow-on reduced-final-point paragraph,
  adding bmason's note about sampling optimum curves and retaining PSFs/MSs.
- `PLAN.md`: 4-Sep delta (three lines).
- `PSF_PLOT_FIX_HANDOFF.md`: replace §3 with a short "superseded 4 Sep by bmason
  decision" note pointing at RUN_CAMPAIGNS; keep §1 evidence.

### Regenerate and commit
```bash
cd curvegen
casapy export_psf_data.py --all
casapy make_report.py --combined reports/ngvla-curves.html
casapy make_report.py --combined --release
```
Verify the release payload has no `gaussian_fit` / `reference_gaussian` / "robust
core" strings and that `gaussian_volume_sr` is present wherever bmaj is.

Commits (tracked files only; leave AGENTS.toml, files.txt, launch.txt, memo build
artifacts, revDsnapshotIssue.txt, tmp/ alone):
1. `Use the tclean restoring beam as the PSF Gaussian reference` — exporter,
   make_report, template, PSF tests, RUN_CAMPAIGNS PSF section, PLAN, handoff doc.
2. `Use 0.5 GHz channels for the focused MFS snapshot pilot` — MFS launcher, MFS
   test, MFS_CAMPAIGN_PLAN, README, RUN_CAMPAIGNS MFS lines.

The 3-anchor Rev F backfill (`sbatch --array=0 curvegen/backfill_psf.sbatch`) stays
bmason's call and is independent of this change; export + reports rerun after it.

## Verification
```bash
/work2/10240/bmason72/stampede3/casaenv/bin/casapy -m unittest discover -s tests -t .
git diff --check
```
Plus the regeneration above and a grep of the release HTML for the removed strings.

# PSF diagnostics in the curve reports

This file is the reference for how the curve reports measure and present PSF
quality: half-power width, first-null volumes, the restoring-beam Gaussian
reference, confusion scaling, and how the calculator picks a captured PSF to
display. `docs/ops/RUN_CAMPAIGNS.md` holds only the commands for running the backfill
and regeneration jobs; look there for the Slurm run sheet, and here for what
the numbers mean.

## Profile captures and legacy 3-FWHM data

Radial PSF profiles are captured during `curvegen/sweep.py` imaging and
appended to `results*/profiles/*.jsonl`. `measure.CAPTURE_RMAX_FWHM` changed
from 3 to 10 on 18 Aug 2026; profiles captured before that date retain only
about 3 FWHM of radial data, and the exporter uses the last valid record for
each lattice key, so it cannot synthesize the missing 3-10 FWHM samples for
those points. These pre-18-Aug captures are left as is: the chart already
shows them honestly (a profile that stops partway across the fixed 0-10 FWHM
domain), and no range-classification or legacy-warning logic is added to the
report.

Beam coverage varies by store. Essentially all Rev F and Rev C track points
(the release tracks) carry a tclean restoring beam. About 1,750 Rev D track
exploratory points, and most snapshot-campaign points (Rev F ~2,470 of 3,830,
Rev D ~1,560 of 2,380), lack one and get no ΩPSF/ΩG or confusion ratio; the
report marks these "—" ("no restoring beam recorded").

## Where exported PSF payloads live

`curvegen/export_psf_data.py::export_active` writes each combo's per-subarray
JS payloads under `curvegen/reports/psf/<combo_key>/`, where `<combo_key>` is
`config.combo_key(rev, sim_mode, band)`: `"<rev>_<sim_mode>"` for the legacy
mono combos (e.g. `revF_track`) and `"<rev>_<sim_mode>_<band>"` once a band is
given (e.g. `revF_snapshot_band4`). `make_report.py` builds the same key
(`combo_entry`) so the report's lazy PSF loader always looks in the directory
the exporter actually wrote. `combo_key` is shared by both modules
specifically so they cannot drift apart. Before 8 Sep 2026 the exporter built
its key from `(rev, sim_mode)` only, ignoring the band: the band4 collect job
wrote its PSF payloads into the mono `revF_snapshot/` directory, clobbering
the 7 mono files, and the band4 report showed no PSF panels. Fixed by
threading `--band` (default `$NGVLA_BAND`) through the exporter CLI and all
sbatch callers; see the `docs/plans/PLAN.md` gotchas log and the
`docs/worklog/mfs-campaigns.md` 8 Sep entry.

## Gaussian reference: the tclean restoring beam

ΩGaussian is the **tclean restoring-beam volume**,

    Ω_G = π · bmaj · bmin / (4 ln 2),

using the elliptical Gaussian fit CASA already produces during imaging
(`bmaj`, `bmin` from the tclean restoring beam), not a fit to the radial
profile. An earlier version used a fixed-intercept "robust core Gaussian" fit
to the measured profile; it was visibly and quantitatively poor for
multi-scale composite arrays (see "Restoring beam versus core half-power
width" below) and is removed.

Because azimuthal averaging conserves flux, the ∫B dΩ (to first null) over
Ω_G ratio is exact for the restoring-beam reference. The ∫B² term used for
confusion is a mild approximation: the azimuthal average of B² slightly
underestimates the true 2-D ∫B² for an elongated beam, since averaging over
position angle before squaring loses some of the elongation. This caveat
applies wherever `psf_to_gaussian_squared_volume_ratio` (and the confusion
estimate built from it) is used.

`curvegen/export_psf_data.py::derive_psf_metrics` computes these fields per
record: `restoring_bmaj_arcsec`, `restoring_bmin_arcsec`,
`restoring_fwhm_geo_arcsec` (= sqrt(bmaj·bmin)), `gaussian_volume_sr`, and the
first-null ∫B and ∫B² ratios; records without a finite, positive restoring
beam omit `gaussian_volume_sr` and both ratios.
`curvegen/make_report.py::build_psf_metric_summary` packs the per-point
compact summary row for the report, requiring `restoring_fwhm_geo_arcsec` so
that points without a beam are skipped (the calculator then shows "—").

## Restoring beam versus core half-power width

For two-scale PSFs — composite subarrays such as core+spiral, main,
main+long, spiral+mid+long, mostly at Briggs+taper points — the tclean
restoring beam is systematically wider than the radial profile's measured
half-power width, by up to 1.25-1.6x.

Mechanism: tclean's beam fit uses every pixel above `psfcutoff=0.35` in a
41x41 box, and a two-scale PSF's shoulder stays above 0.35 out to roughly
0.75 FWHM, so shoulder pixels broaden the Gaussian fit. The single tclean
call, `run_tclean` in `curvegen/sweep.py`, passes no `psfcutoff`, so CASA's
default of 0.35 applies.

Measured Rev F track ratios by subarray: single-scale arrays (core,
core_inner, mid, spiral) have a median ratio of about 1.00 and a max of 1.07,
none above 1.10; core_spiral has 25 of 276 points above 1.10 (max 1.29); main
70/403 (max 1.42); long 128/354 (max 1.57); spiral_mid_long 115/315 (max
1.59); main_long 99/359 (max 1.50).

The report exposes this rather than hiding it: `derive_psf_metrics` adds
`restoring_to_halfpower_ratio` (restoring FWHM over measured half-power FWHM)
alongside the existing beam metrics, `build_psf_metric_summary`'s compact row
carries it as index 6, and the PSF inspector, its chart legend/x-axis title,
and the QA table's "beam/core" column all surface it.

Because `res_geo` throughout the pipeline is the restoring beam (never the
core half-power width), the reported resolution at an affected point is
coarser than the true core — readers should treat `res_geo` as the
restoring-beam figure it always was, not as an independent core measurement.

The confusion estimate is insensitive to which width defines the reference.
For Condon's γ=3 the model confusion evaluated at θ scales as θ
(σ_c ∝ Ω^{1/(γ−1)} = Ω^{1/2}), while the correction factor
sqrt(∫B²/∫G²) scales as 1/θ, so the choice of θ cancels to first order. The
ΩPSF/Ω_G ratio does depend on it; with Ω_G the restoring beam that ratio is
the Jorsater & van Moorsel flux-scale factor.

## Which captured PSF the calculator shows

`nearestPsfKey` in `curvegen/report_template.html` — used by the calculator's
ΩPSF/ΩGaussian and confusion columns, the PSF inspector, and the per-row
"PSF" inline expander — picks the captured lattice PSF nearest to a
curve/calculator point. It previously ranked candidates by resolution alone
(weighting/robust were only exact-tie breaks). Curve points are interpolated
(e.g. Briggs robust -0.221, taper 40.2 mas), so the resolution-nearest
capture frequently came from a different weighting family entirely: for MAIN
at 87 mas the curve point is Briggs -0.22 (skirt 10%), but the old lookup
returned `natural_2.00_7.245` (skirt 45%). Replayed over all MAIN curve
points, the displayed PSF's skirt exceeded the curve point's skirt by median
+0.05, p90 +0.16, max +0.38.

Fixed by ranking candidates first by weighting family (natural and Briggs
robust ≥ 1.99 count as the same family; same-family candidates always beat
the other family, which is used only when no same-family capture exists),
then within a family by normalized robust/taper distance, with resolution as
the final tie-break. Same MAIN replay after the fix: skirt excess
0.00/+0.01/+0.04 (median/p90/max) — at the cost of a median 7%, p90 17%
resolution offset between the displayed PSF and the curve point, now stated
explicitly in the inspector text and calculator tooltips.

The all-subarray replay confirms the fix generalizes: over 1,899 Rev F
imaging curve points, the displayed-PSF skirt now matches the curve skirt to
median 0.000 / p90 +0.007 / max +0.08, versus median +0.05 / p90 +0.16 / max
+0.38 before. The resolution offset between the displayed PSF and the curve
point runs 2-8% by subarray (median), worst case 23%.

See `tests/test_psf_lookup_replay.py` for a standalone Python mirror of the
ranking and its regression cases.

## Follow-on: reduced final-point campaign

For a future reduced final-point campaign, retain a 2-D PSF (compressed FITS
or an equivalent float array) for every curve anchor, plus the derived radial
and axis profiles, weighted uv-radius histogram/moments, effective
frequency, weight/noise totals, MS/config hash, imaging parameters, and CASA
version. Full 2-D products need only be retained for this small final set;
exploratory lattice points can continue using compact profiles.

bmason's intent: this follow-on campaign samples a subspace of the grid along
the optimum curves (not the full exploratory lattice) and retains PSFs, and
possibly MSs, for that reduced set.

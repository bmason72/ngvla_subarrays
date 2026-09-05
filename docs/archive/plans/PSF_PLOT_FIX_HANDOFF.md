# PSF plot repair: handoff and completion specification

Date: 2026-09-04  
Repository: `/home1/10240/bmason72/Code/ngvla_subarrays`  
Checkpoint commit before the work below: `7fd2eaa Prepare MFS snapshot pilots and refine calculator output`

This document is standalone. It records the observed failures, the evidence,
the exact state of the unfinished repair, and a strict specification for
finishing it without relying on chat history.

## 1. Problem summary

### 1.1 Many profiles visibly stop at r approximately 3 FWHM

This is real missing source data, not a stale-browser or SVG clipping bug.
`measure.CAPTURE_RMAX_FWHM` changed from 3 to 10 on 2026-08-18. The profile
JSONL files are append-only, and records captured before that change retain
only about 3 FWHM of radial data. The exporter correctly uses the last valid
record for each lattice key; it cannot synthesize the missing 3--10 FWHM
samples.

The release HTML was regenerated at 2026-09-04 15:54 and did contain the then
current exported payloads. The following counts were measured directly from
the payload JS files:

| campaign | legacy ~3 FWHM | current ~10 FWHM | total |
|---|---:|---:|---:|
| Rev F track (release default) | 1,766 | 2,099 | 3,865 |
| Rev D track | 3,384 | 2,026 | 5,410 |
| Rev C track | 1,349 | 2,506 | 3,855 |
| Rev F snapshot | 3,120 | 873 | 3,993 |
| Rev D snapshot | 2,434 | 0 | 2,434 |

The August range-refresh Slurm jobs did complete successfully:

- `3418623_0`, Rev F track: completed, exit 0
- `3418624_2`, Rev D track: completed, exit 0
- `3421939_4`, Rev C track: completed, exit 0

Those jobs refreshed displayed-curve anchors, not every exploratory lattice
point in the heatmaps. A fresh Rev F track dry-run on 2026-09-04 found three
anchors introduced or moved since that work:

- `mid+spiral+core-outer`: 1 anchor still needs imaging
- `long+mid+spiral+core-outer`: 2 anchors still need imaging

All other Rev F track curve anchors were current at that check.

The report regression is amplified by the new fixed 0--10 FWHM horizontal
domain: 0--3 uses the left half and 3--10 uses the right half, as requested.
A legacy profile therefore visibly ends at the midpoint. The earlier dynamic
domain stretched a 3-FWHM profile across the full chart and concealed the
missing outer data.

### 1.2 The “robust central PSF fit” is not a defensible PSF model

The concern is confirmed quantitatively. The former exporter fit
`log(PSF) = slope * r^2` inside the measured HWHM, fixed the intercept at zero,
and used median-centered Huber weights. That algorithm can be resistant to an
individual bad bin while still being systematically wrong for a structured,
multi-scale PSF.

The largest failures occur for `main`, `main+long`, and composites containing
mid/long baselines. In current Rev F track payloads the fitted Gaussian is
above the measured radial profile in roughly two thirds of inner-core samples
for these families. Typical median fit-to-measured FWHM ratios are about 0.85
to 0.93 for the worst composites. A free-intercept diagnostic gives a median
central amplitude around 0.86--0.87 for the worst families rather than 1.0,
which is direct evidence that a unit-peak single Gaussian is structurally
inadequate there.

Sampling is not the primary cause. The 3-FWHM profiles used 40 bins and the
10-FWHM profiles use 134 bins, preserving approximately the same radial sample
density. Representative problematic rows also have tens of image pixels per
beam. The mismatch is primarily the non-Gaussian, multi-scale PSF combined
with an inappropriate one-component fitting objective.

### 1.3 Recoverability and retained artifacts

The normal sweep deliberately deletes CASA `.psf`, `.image`, `.residual`,
`.pb`, `.sumwt`, `.model`, `.mask`, and `.weight` products after measurement.
The durable profile records contain radial profiles, beam metadata, and newer
major/minor cuts, but not the 2-D pixel array.

There are two meaningful accidentally retained full PSFs under scratch, but
they cover only isolated points and are not a general recovery source. The
measurement sets are retained under the `$WORK` `ngvla_curvegen/ms*` stores,
so selected points can be re-imaged without repeating `simobserve`.

## 2. Work completed but not yet committed

The worktree contains an unfinished repair. Do not assume the checkpoint
commit contains these changes.

### 2.1 PSF metric and report changes presently in the worktree

- `curvegen/export_psf_data.py`
  - Deleted `_robust_gaussian_fwhm` and all fitted-width production.
  - Added `reference_gaussian_fwhm_arcsec`, equal to the directly measured
    radial half-power FWHM.
  - Retained Gaussian-volume ratios only as normalization against a unit-peak
    Gaussian with that direct half-power width.
- `curvegen/make_report.py`
  - Changed the compact PSF-metric schema to use the reference width.
  - Added capture-range metadata at positional element 6.
- `curvegen/report_template.html`
  - Removed the Gaussian curve from the chart and legend.
  - Removed all “robust core Gaussian” wording.
  - Described `Omega_Gaussian` as a normalization, not a fit.
  - Added logic intended to prefer 10-FWHM captures when the calculator needs
    a nearby measured PSF.
  - Added an explicit legacy-capture warning.
- Tests were updated for the new contract.

Important: this is not yet a complete solution to the range problem. The
current helper trusts declared `cut_rmax_fwhm` before measuring the achieved
radius, and the nearest-point function still falls back to legacy data when no
current capture exists. Both behaviors must be corrected under the strict
specification below.

### 2.2 MFS nchan changes in the same uncommitted worktree

The simulation-only Band-4 snapshot pilot default was narrowed from the large
powers-of-two ladder to `nchan=27,54`. Across the 13.5-GHz Band-4 window these
are 0.5- and 0.25-GHz channels. The purpose of the second trial is one focused
convergence check of beam/skirt/eta and memory, not an assumption that hundreds
of channels are needed. README, runbook, MFS plan, launcher, and its test were
updated accordingly.

These MFS edits are logically separate from the PSF repair and should be
committed separately unless the maintainer explicitly wants one combined
commit.

### 2.3 Verification and generated-artifact state

- Focused tests: 46 passed.
- Full suite under the CASA environment: 353 passed, 1 skipped.
- `git diff --check`: passed.
- `export_psf_data.py --all`: completed successfully after the code changes;
  payload JS timestamps are approximately 2026-09-04 16:25.
- The release HTML has **not** been regenerated after these unfinished code
  changes. Its timestamp remains 2026-09-04 15:54. It therefore still embeds
  the prior payload/schema and robust-fit presentation.
- No PSF backfill or MFS Slurm job was submitted during this repair.
- No commit was made after `7fd2eaa`.

The repository also contains unrelated untracked user files, including
`AGENTS.toml`, `files.txt`, `launch.txt`, memo build artifacts,
`revDsnapshotIssue.txt`, and `tmp/`. Preserve them and do not include them in
the repair commit.

## 3. Superseded 4 Sep 2026 by bmason decision

Sections 3 and 4 (the strict range-classification/legacy-warning
specification and its commit split) are superseded 4 Sep 2026 by bmason's
decision recorded in `docs/archive/plans/PSF_REPORT_FIX_PLAN.md`: legacy ~3-FWHM captures are
pre-18-Aug data and are left as is (no range-classification code, no legacy
warnings, no lattice backfill campaign), and the Gaussian reference becomes
the tclean restoring beam rather than a fitted or direct-half-power width. See
`docs/archive/plans/PSF_REPORT_FIX_PLAN.md` for what was actually implemented and
`docs/architecture/PSF_DIAGNOSTICS.md` for the resulting state.

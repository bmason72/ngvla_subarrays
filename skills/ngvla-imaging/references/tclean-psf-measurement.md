# Measuring PSF-based quantities with tclean at niter=0

## Why niter=0

For taperability/sculpting work you are not deconvolving a source — you want
the **dirty image and PSF** for one (weighting, robust, taper) combination,
so `tclean(..., niter=0)` produces exactly that (a `.residual` = the dirty
image, plus a `.psf`) without spending time on cleaning and without any
deconvolution-model dependence. Two quantities get measured from this:

- **eta (inefficiency factor):** dirty-image rms at this weighting, divided
  by the rms of the **natural-weighting, untapered** dirty image made from
  the *same* MS (natural weighting is the sensitivity optimum, eta = 1 by
  definition there). Everything else (Briggs robust, any taper) trades
  resolution against sensitivity, i.e. eta >= 1 in general (occasionally
  numerically ~1 within noise at the natural point itself).
- **Resolution:** taken from the CASA-fitted **restoring beam**
  (`bmaj`/`bmin` returned from the tclean call/psf fit), not a custom fit —
  see "restoring beam vs. half-power width" below for why this matters and
  where it's imperfect.
- **Skirt (shoulder):** the PSF's azimuthally-averaged value at a radius of
  **one restoring-beam FWHM** from the peak. This is the memo-65/121
  "sculpting" quantity — see `curves-and-sculpting.md`.

## Weighting and taper conventions

- **Natural weighting** is the sensitivity-optimal, coarsest-resolution
  point on the curve (no taper). Adding a **UV (outer) taper** to natural
  weighting moves resolution *coarser* than native.
- **Briggs weighting** (the `robust` parameter, conventionally spanning about
  -2 to +2) moves resolution *finer* than natural and also improves PSF
  quality (lower sidelobes/skirt) relative to naive uniform weighting;
  combining Briggs with a taper can reach intermediate points. In other
  words: natural+taper reaches *coarser* than native resolution, Briggs
  (optionally with its own taper) reaches *finer* resolutions and better PSF
  shapes — see memo 76 for the full picture and CLAUDE.md's "Key domain
  concepts."
- `uvtaper` in CASA is specified as an angular scale pair plus PA (e.g.
  `["<taper>marcsec", "<taper>marcsec", "0deg"]` for a circular taper); taper
  = 0 means no taper (pass an empty list, not a zero-valued taper, to avoid
  CASA choking on a zero taper value).
- A minimum-`uvrange` selection (e.g. `">150m"`) is how you exclude spurious
  short baselines (see `configurations.md`, the LONG peculiarity) — apply it
  as a `tclean` kwarg (or an MS selection) uniformly across every weighting
  point measured for that subarray, including the natural reference point.

## Cell size and image size

- **Cell size** should be chosen so the **synthesized beam is well-sampled**
  — a common convention (used in the `ngvla_subarrays` repo, exposed as
  `OVERSAMPLE`) is **5 pixels per beam FWHM**, derived per-point from
  `im.advise` or an equivalent beam estimate, since the beam size changes
  with weighting/taper. Cell size therefore is **not fixed** across a sweep
  of (robust, taper) points — it follows the taper.
- **Image size (`imsize`)**, by contrast, is typically **fixed per
  subarray** across the whole (robust, taper) grid, sized to comfortably
  contain the primary beam / field of view at the coarsest taper you'll
  reach for that subarray (composite/heterogeneous subarrays with a wide
  dynamic range of scales need much larger `imsize`, e.g. tens of thousands
  of pixels, and correspondingly more disk/memory).
- **Field-of-view caveat for Briggs weighting:** the Briggs weighting-density
  grid is computed over the imaged field of view, so if you change `imsize
  x cell` between points you can inadvertently change the weighting itself,
  not just the pixel sampling — for a controlled taperability sweep, prefer
  holding **imsize fixed** (angular extent may still drift slightly with
  cell, which is a known, documented approximation, not a bug to "fix"
  silently) rather than fixing cell and letting the FOV wander freely; if
  going the fixed-imsize route, treat cases where cell changes a lot (deep
  in a taper) as a caveat on both the weighting behavior and on antenna-hours
  bookkeeping, and say so in write-ups rather than treating it as invisible.

## MFS-specific pins

For multi-frequency-synthesis (broadband continuum) dirty imaging at
niter=0, a consulted CASA expert's guidance (see
`docs/worklog/mfs-tclean-consult-2026-09-07.md` in the `ngvla_subarrays`
repo) settled on:

- `specmode="mfs"`, `deconvolver="hogbom"`, **`nterms=1`**. With Hogbom,
  `nterms` has no effect — this is fine, but it means you are measuring the
  ordinary broadband dirty image/PSF, not a full multi-term (MT-MFS) fit.
  **Caution:** if you ever switch to `deconvolver="mtmfs"` (nterms>1), the
  restored Taylor-coefficient image (`.image.tt0`) is *not* guaranteed to
  have the ordinary dirty-image rms even at `niter=0` — CASA's MT-MFS
  restoration operates in Taylor-coefficient space. Don't assume all
  deconvolvers are interchangeable at zero iterations; measure `.residual`
  and `.psf` directly with Hogbom for a clean, well-understood dirty image.
- `reffreq="<band centre> GHz"` — labels the MFS reference frequency; it
  does **not** change which visibilities/channels get gridded (that's set by
  the MS's actual channels), and does not need to equal the simulation's
  first-channel centre (see `simulation.md`).
- `perchanweightdensity` is **irrelevant for `specmode="mfs"`** — CASA
  documents this parameter as meaningful only for cube (`specmode="cube"`)
  imaging; for MFS the weighting always uses the combined, frequency-pooled
  uv coverage regardless of this flag's setting. Leave it unset; don't spend
  a sweep testing True vs. False for MFS — there is no expected difference
  beyond numerical noise (verify once in your installed CASA build if in
  doubt, rather than running a whole duplicate campaign).
- Broadband (u,v) filling genuinely *can* change how eta responds to
  robust/taper relative to a monochromatic curve — that's a real physical
  effect of combining many frequencies' uv coverage, not something to
  "correct away"; it's why MFS curves need their own campaigns rather than
  being inferred by scaling a mono curve (see `curves-and-sculpting.md`).
- Other tclean housekeeping for a clean niter=0 comparison: `stokes="I"`,
  `savemodel="none"`, fresh output image names each run (no starting model
  carried over), `pbcor=False`, and a small negative `pblimit` (e.g. -0.02)
  to suppress the attached primary-beam mask while keeping its magnitude as
  the normalization cutoff.

## `psfcutoff` and the restoring beam vs. half-power width

- CASA's beam fit (used for `bmaj`/`bmin`, hence "resolution") by default
  fits a Gaussian to pixels above `psfcutoff` (CASA default **0.35**) within
  a fixed box (e.g. 41x41 pixels) around the PSF peak. This is a **fit to
  the core**, not a direct measurement of the half-power width, and the two
  disagree once the PSF has a significant near-in shoulder.
- For **composite/heterogeneous subarrays** (two or more length scales
  mixed, e.g. core+spiral, main, main+long — especially at Briggs+taper
  points), the PSF shoulder can stay above `psfcutoff` out to roughly 0.75
  FWHM, which **broadens the fitted Gaussian** relative to the profile's
  true half-power width — measured in one campaign, the fitted restoring
  beam ran up to **1.25-1.6x** wider than the measured half-power width for
  such subarrays (worst cases up to ~1.6x; single-scale subarrays like core,
  mid, spiral alone stayed within ~1.07x). **Whichever width you report as
  "resolution," say explicitly which one it is** — a restoring-beam-based
  resolution is measurably coarser than the true angular resolving power for
  these composite cases, and readers should not treat it as an independent
  measurement of the profile core.
- Pin and record `psfcutoff` explicitly for any campaign (don't rely on the
  CASA default going unmentioned), and validate beam fits on extreme
  (strongly tapered, most heterogeneous) cases specifically, since that's
  where the fit is most likely to be misleading.
- If you need the true angular resolving power independent of this fit
  artifact, measure it directly from the radial PSF profile (half-power
  radius of the azimuthally-averaged profile), not from the restoring beam.

## Cleanup

Dirty-image tclean products at niter=0 (`.residual`, `.psf`, `.pb`,
`.sumwt`, `.model`) are disk-hungry and disposable once the needed scalar
measurements (beam, rms, skirt, optionally a saved radial profile) are
extracted — delete them promptly after each point, and make each point's
work resumable/idempotent (record what's been measured so a killed sweep can
restart without re-imaging already-measured points).

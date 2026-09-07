# Taperability curves, beam sculpting, and LAS

## eta and the taperability curve

For one subarray at one reference frequency, sweeping (Briggs robust, UV
taper) and measuring (resolution, eta, PSF skirt) at each point (see
`tclean-psf-measurement.md`) produces a 2-D lattice. From that lattice, two
**1-D curves** of eta vs. resolution are derived:

- **Point-source curve:** at each resolution, the **minimum eta** achievable
  by any (robust, taper) combination, ignoring PSF quality entirely. This is
  the right curve for pure detection/point-source-sensitivity goals, where a
  messy PSF (large near-in sidelobes) is acceptable.
- **Imaging curve (sculpted curve):** at each resolution, the minimum eta
  achievable **subject to** the PSF skirt being below a threshold. This is
  strictly worse than or equal to the point-source curve at every
  resolution (the imaging curve pays an eta penalty to buy PSF quality). If
  no (robust, taper) combination at a given resolution meets the skirt
  threshold, that resolution should be reported as **imaging-infeasible**
  for the subarray rather than silently omitted — some subarray/resolution
  combinations genuinely cannot sculpt down to the target (memo 121 notes
  cases bottoming out around ~16% skirt when the target was 10%).

## Beam sculpting (the skirt)

"Sculpting" means choosing (robust, taper) not just to hit a target
resolution, but to also suppress the PSF's **near-in sidelobe** — the
"skirt" or "shoulder" — which otherwise corrupts extended/imaging science
even when the formal resolution and sensitivity look fine. The skirt is
measured as the (azimuthally averaged) PSF value at **one restoring-beam
FWHM radius** from the peak. A natural-weighting PSF typically has a large
skirt (tens of percent); Briggs weighting sculpts it down, at an eta cost.
A commonly used **default threshold is 10%** (memo 121's own phrasing:
sculpting "to a level of 10% at a radius of one FWHM") — treat this as a
sensible default motivated by the memos, not an immutable constant; make it
an adjustable parameter in any implementation.

Measuring the skirt requires a **radial PSF profile** (azimuthally averaged
cut through the dirty-image PSF at niter=0), not just the fitted restoring
beam — capture this alongside the beam fit at every sweep point (or at least
at the curve-defining "anchor" points) so the skirt-vs-threshold search has
data to work with. Keep in mind the restoring-beam-vs-half-power caveat from
`tclean-psf-measurement.md`: since the skirt radius is defined in units of
the (possibly overestimated, for composite subarrays) restoring beam, a
biased beam estimate biases where "one FWHM" is measured.

## Frequency scaling

A curve tabulated at one **reference frequency** (a common choice being
~30 GHz, i.e. Ka-band-adjacent) can, for a **monochromatic** curve, be
rescaled to another frequency by scaling the resolution (and LAS) axis by
`freq_ref / freq_target` (resolution and LAS both scale with wavelength,
i.e. inversely with frequency) — **eta itself is assumed invariant** under
this rescaling (the curve's shape vs. resolution-in-beams doesn't change).
This assumption should be spot-checked, not taken purely on faith, and is
more questionable for wide fractional-bandwidth continuum work.

**Multi-frequency-synthesis (MFS/broadband) curves do NOT scale this way.**
A curve measured with a wide simulated bandwidth already bakes in that
bandwidth's own (u,v) filling and per-channel weighting behavior at its
particular band; simply sliding the resolution axis to a different
frequency does not reproduce what a *different* band's own broadband uv
coverage would do. If you need an MFS curve at a different band, simulate
and measure it directly for that band — do not attempt to frequency-scale a
mono curve as a stand-in for MFS, or scale one MFS band's curve to
represent another band.

## LAS (largest angular scale, memo 67)

LAS is the largest angular scale of structure a subarray's uv coverage can
recover — set primarily by the **shortest** baselines (`b_min`), roughly
`LAS ~ 0.6 * lambda / b_min` for a short-baseline-array-like configuration
up to `~0.85 * lambda / b_min` for a dense core, calibrated against memo 67's
disk-simulation measurements (not a pure geometric formula — trust the
memo's measured coefficients over a naive analytic guess). LAS:

- scales with wavelength (`\propto 1/frequency`), the same direction as
  resolution;
- is **assumed independent of robust/taper** for selection purposes (an
  assumption worth spot-checking, not re-deriving from scratch, if it
  matters to your task);
- must be computed from the **filtered** b_min (see `configurations.md`'s
  LONG-peculiarity discussion) — an unfiltered b_min dominated by spurious
  short baselines will give a badly wrong (too-small) LAS.

## Where the memos matter most here

- **Memo 67** — the LAS coefficients and how they were measured (disk
  simulations of core/SBA/spiral-derived arrays).
- **Memos 65 and 121** — the sculpting concept, its threshold, and worked
  per-subarray robust/taper grids and skirt/eta trade-offs; the closest
  existing worked examples of "pick weighting X to hit resolution Y with
  skirt <= Z."
- **Memos 55, 72, 76** — the eta/taperability-curve concept itself, and the
  natural-taper-vs-Briggs-robust framing (memo 76 specifically works out
  which knob to turn on which side of native resolution).

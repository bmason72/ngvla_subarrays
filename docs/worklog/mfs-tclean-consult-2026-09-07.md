# Consult: tclean settings for MFS taperability curves (astra_seer / gpt-6-astra, 7 Sep 2026)

Question file: the four questions in `tmp/codex/astra_tclean_consult.md` (nterms at niter=0, MT-MFS tt0 penalty, perchanweightdensity, other settings). Reply verbatim below.

Your basic experiment is sound, but **two premises need correcting: MT-MFS restoration can matter even at `niter=0`, and `perchanweightdensity` does not control MFS weighting.**

1. **`nterms=1`, Hogbom: appropriate, but not the only meaningful choice.**

   With Hogbom, `nterms` is inactive. Your `.residual` is the ordinary broadband dirty image.

   Switching to MT-MFS generates additional Taylor-weighted PSFs and residuals. Its zeroth-order PSF and **pre-restoration** dirty residual should match ordinary MFS for identical visibility weights; the beam fitted to that PSF should also match. However, MT-MFS restoration converts residuals into Taylor-coefficient space—even with `niter=0`. Consequently, `.image.tt0` need not have the ordinary dirty-image rms. CASA explicitly documents this distinction. [CASA synthesis imaging](https://casadocs.readthedocs.io/en/latest/notebooks/synthesis_imaging.html)

   Keep Hogbom for production and measure `.residual` and `.psf`. Do not describe all deconvolver choices as interchangeable at zero iterations.

2. **There is no universal sensitivity penalty associated with 50% bandwidth and two terms.**

   For an ideal inverse-variance-weighted fit of intensity plus a linear spectral term, elementary weighted regression gives
   \[
   \frac{\sigma_{\mathrm{intercept}}}{\sigma_{\mathrm{constant}}}
   =\sqrt{1+\frac{(\bar\nu_w-\nu_0)^2}{s_{\nu,w}^2}},
   \]
   where \(\bar\nu_w\) and \(s_{\nu,w}\) are the weighted frequency mean and standard deviation.

   Your symmetric, equally weighted channels have \(\bar\nu_w=27\) GHz: **the ideal intensity penalty is zero**, despite fitting a slope. With a frequency spread near 4 GHz, displacing the weighted mean by 1 or 2 GHz would give approximately 3% or 12% penalties. These are illustrative regression results, not predicted CASA penalties.

   Briggs and taper weights are not generally inverse-noise-variance weights. Their exact noise propagation requires the covariance containing **squared imaging weights**; frequency-dependent spatial sampling also couples spectral and spatial reconstruction. Thus neither the penalty nor its effect on relative eta follows from fractional bandwidth alone.

   **Document and measure a representative subset:** natural, a few robust values, and weak/strong tapers using MT-MFS with two terms and zero iterations. Compare restored `.image.tt0` rms, normalizing by its own natural-weighted counterpart. This tests the restoration/noise effect; source-containing tests would be needed to assess actual deconvolution performance.

3. **The proposed `perchanweightdensity` distinction is incorrect for `specmode="mfs"`.**

   CASA explicitly states that this parameter has no meaning for MFS. Continuum weighting uses the combined frequency-dependent uv coverage; the True/False distinction applies to cubes. [CASA tclean reference](https://casadocs.readthedocs.io/en/latest/api/tt/casatasks.imaging.tclean.html)

   **Leave it unset.** Setting False would not select a different continuum convention. Expected eta difference between True and False in MFS: zero, apart from numerical differences or a bug. A single paired check in your installed 6.7.5 build is sufficient; no second production sweep is needed.

   Broadband uv filling can certainly change eta versus robust relative to monochromatic imaging. Its magnitude depends on the array, sampling, and density grid—not bandwidth alone.

4. **Additional production controls worth addressing:**

   - **Fix angular image extent as well as cell size.** The Briggs density grid depends on image field of view. Changing `imsize × cell` between taper points can change the weighting itself. [CASA weighting equations](https://casadocs.readthedocs.io/en/latest/notebooks/synthesis_imaging.html)
   - **Check channel/time sampling convergence.** Thirty-two channel centers and one timestamp represent discrete geometric samples. Repeat a few cases with finer frequency sampling—and time sampling if representing a genuinely averaged 60 s observation. This matters especially for snapshot skirts.
   - **Audit visibility weights and noise independence.** Equal injected noise should have equal corresponding statistical weights, including `WEIGHT_SPECTRUM` if present. Independent, equally noisy RR and LL give \(I=(RR+LL)/2\), reducing rms by \(\sqrt2\) relative to either hand. That factor cancels in eta.
   - **Use untapered natural weighting of the same broadband dataset as the denominator.** Measure rms over a consistent central region containing many noise correlation areas; estimate realization uncertainty for heavily tapered cases.
   - **Validate beam fits independently.** Pin/document `psfcutoff`; CASA’s Gaussian fit is not identical to a direct half-power width for a core-plus-skirt PSF. Strong taper can also make the beam very large in pixels. Inspect extreme cases and define the skirt annulus explicitly. [CASA beam-fitting documentation](https://casadocs.readthedocs.io/en/latest/api/tt/casatasks.imaging.tclean.html)
   - **Other listed settings are reasonable.** The 27 GHz reference labels ordinary MFS; it does not replace channel frequencies in uv sampling. Top-of-band cell selection is appropriate. Standard gridding suits a central geometric PSF experiment; wide-field sky fidelity is a separate issue. Explicitly retain `pbcor=False`. Negative `pblimit` suppresses the attached PB mask, but its absolute value remains a normalization cutoff. Use fresh output names and no starting model. [CASA parameter reference](https://casadocs.readthedocs.io/en/latest/api/tt/casatasks.imaging.tclean.html)

**Verdict**

- **OK as is:** MFS/Hogbom, zero iterations, RR+LL Stokes I, 27 GHz reference, top-band cell.
- **Change:** enforce fixed angular field of view, clean output state, and explicit measurement products.
- **Document:** geometric noise convention, beam/skirt definitions, sampling convergence, and limited transfer to deconvolved science images.
- **Measure:** a small MT-MFS comparison subset; no duplicate `perchanweightdensity` campaign.
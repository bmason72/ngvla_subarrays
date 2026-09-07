# Glossary

One-line definitions of terms used repeatedly across the docs, each with a
pointer to where the term is defined or discussed in depth. Define each term
once, at the pointed-to location; this file is the index, not a second
definition.

- **eta (η):** image rms at a given resolution divided by the natural-
  weighting rms (natural = 1.0). See `CLAUDE.md` "Key domain concepts".
- **point-source curve:** the min-eta path to each resolution, ignoring PSF
  skirt. See `docs/architecture/selection-tool-design.md`.
- **imaging curve (sculpted curve):** the min-eta path to each resolution
  subject to PSF skirt <= threshold. See
  `docs/architecture/selection-tool-design.md`.
- **skirt (shoulder):** the PSF value at radius = 1 clean-beam FWHM from the
  peak, azimuthally averaged; sculpting default threshold 10%. See
  `CLAUDE.md` "Key domain concepts" and `docs/plans/PLAN.md`.
- **taperability:** the property/curve of how eta trades against resolution
  as UV taper and Briggs robust are varied. See `CLAUDE.md` "Key domain
  concepts".
- **LAS (largest angular scale):** the largest scale structure a subarray
  can image, ~0.6 lambda/b_min (SBA) to ~0.85 lambda/b_min (core), scaling
  with wavelength. See `CLAUDE.md` "Key domain concepts".
- **map (adaptive-sampler sense):** one subarray's, one campaign combo's
  (robust, taper) -> (eta, beam, skirt) surface, as certified or filled by
  the adaptive sampler. See `docs/features/MFS2_ADAPTIVE_SAMPLER_SPEC.md`
  (parked 6 Sep 2026, but still the defining reference for this sense of
  "map").
- **sample / curve / envelope:** a sample is one measured
  (robust, taper) -> (eta, beam, skirt) grid point; a curve is the derived
  eta(resolution) function built from samples; the envelope is the min-eta
  curve across all samples for a subarray/curve-type, i.e. what gets
  rendered and queried. See `sa_select/README.md` and
  `docs/ops/RUN_CAMPAIGNS.md`.
- **combo:** a `(rev, sim_mode, band)` registry key identifying one
  campaign's data/report/config namespace; an empty band is a legacy mono
  (30 GHz single-channel) campaign. See `README.md` Layout table. The
  PSF-backfill array-index table in `docs/ops/RUN_CAMPAIGNS.md` predates the
  band axis and keys "combo" there as `(rev, sim_mode)` only; that table is
  labeled accordingly.
- **band4 (internal key) / "MFS snapshot" (user-facing name):** the
  registry's internal tag for the Ka-band multi-frequency-synthesis
  broadband campaign; never shown to the user, who instead sees "MFS
  snapshot" (or "Rev F - MFS snapshot"). See D7 in
  `docs/worklog/mfs-campaigns.md`.
- **fixed field of view (memo-121 convention):** image size held fixed in
  pixels; cell size grows with taper beyond the native beam, so this
  convention is exact at the fine end and for natural weighting, and only
  approximate at coarse-taper Briggs points (effect on eta not yet
  quantified). See D9 in `docs/worklog/mfs-campaigns.md` and `CLAUDE.md`
  "Broader context".
- **anchor:** a curve point that is actually rendered/displayed on a
  campaign's report envelope, as opposed to any measured lattice sample;
  PSF backfill targets anchors specifically because those are what the
  report shows. See `docs/ops/RUN_CAMPAIGNS.md` and
  `docs/architecture/PSF_DIAGNOSTICS.md`.
- **canonical taper(s) / lattice:** the fixed 14-level logarithmic taper
  grid (plus taper 0) used as the standard sampling axis across mono and
  MFS campaigns. See `docs/worklog/mfs-campaigns.md` ("Current status"
  section).
- **snapshot vs. track (sim_mode):** track = 4 h synthesis; snapshot = a
  single ~60 s correlator dump. See `README.md` Layout table.

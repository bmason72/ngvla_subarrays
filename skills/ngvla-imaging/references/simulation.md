# Simulating noise-only measurement sets with the CASA simulator (`sm`)

This describes the pattern used for **noise-only** (no source, no sky model)
simulated MeasurementSets for taperability/PSF work — you are simulating
*sampling and thermal noise*, not astrophysical signal, so there is no
`sm.predict`/component-list step, just `sm.setnoise` + `sm.corrupt`.

## Core call sequence

1. `simutil().readantenna(cfg)` to read an ngVLA `.cfg` file into arrays of
   X/Y/Z/diam/name (+ telescope metadata). **Gotcha:** across CASA versions
   `readantenna` returns either 7 or 8 items — unpack defensively (the
   `ngvla_subarrays` repo's `curvegen/simulate.py` hit a hard C++ abort from
   assuming a fixed tuple length).
2. `sm.open(ms_path)`, then `sm.setconfig(...)` with those antenna positions.
3. `sm.setspwindow(spwname=..., freq=<FIRST CHANNEL CENTRE>, deltafreq=<channel
   width>, freqresolution=..., nchannels=N, stokes="RR LL")` (or `"RR RL LR
   LL"` for a full-polarization single-channel legacy setup).
4. `sm.setfield(...)` with a source direction; source declination is a
   deliberate, fixed convention (the `ngvla_subarrays` repo uses **dec +24**
   uniformly) — not physically meaningful, just needs to be held fixed across
   a whole campaign so PSFs/eta stay comparable.
5. `sm.setauto(autocorrwt=0.0)` — zero out the autocorrelation weight (no
   autocorrelations wanted in an interferometric imaging simulation).
6. `sm.settimes(integrationtime=<dump>, usehourangle=True, ...)`, then
   `sm.observe(..., starttime=..., stoptime=...)` with the HA window.
7. `sm.setnoise(mode="simplenoise", simplenoise="1Jy")` then `sm.corrupt()` —
   this is what actually writes Gaussian noise into the visibilities; there
   is no signal to corrupt, so the resulting MS is pure noise with the
   requested per-visibility rms.

## Snapshot vs. track

Two observing-window presets recur:

- **4-hour track**: hour angle **-2h to +2h**, i.e. transit-centered synthesis
  with real (u,v) rotation — this is what taperability curves have
  historically been built from (comparable to the legacy `ngvla-taperability-
  pipeline`).
- **Snapshot**: a **single dump** (e.g. 60 s) centered on transit (HA=0),
  e.g. window `(-30s, +30s)` around HA=0 so exactly one integration lands at
  the midpoint. Verify that exactly one integration actually lands (dump time
  and window must be consistent) — an off-by-one window can silently produce
  0 or 2 dumps.

Dump/integration time itself (e.g. 60 s) is a separate knob from the
track/snapshot window choice and should be picked deliberately and recorded,
since it affects effective (u,v) smearing for the track case.

## Single-channel vs. multi-channel (MFS) setup

For monochromatic (single-channel) work: one channel, historically 1 MHz
wide, centered at the reference frequency (e.g. 30 GHz) — this is the "mono"
convention and needs no special spectral-window care since there's only one
channel.

For **multi-frequency-synthesis (MFS)** / broadband continuum work, several
things must be gotten right together:

- **First-channel-centre pitfall:** `sm.setspwindow(freq=...)` wants the
  **centre frequency of the FIRST channel**, not the centre of the whole
  band. If you instead pass the band's overall centre frequency (e.g. the
  arithmetic mean of the band edges) as `freq`, the simulated channels are
  silently offset from the intended band — every channel centre is shifted
  by half the band. Compute `first_channel_centre = freq_lo + channel_width/2`
  explicitly and pass that.
- Corresponding, `tclean`'s `reffreq` for MFS restoration is typically the
  **band-centre** frequency (not the first-channel centre) — these are two
  different frequencies used in two different places; don't conflate them.
- **Correlations:** MFS/broadband work commonly narrows correlations to
  `"RR LL"` (parallel-hand only) rather than the legacy single-channel
  `"RR RL LR LL"` (full polarization) — a smaller product set that's
  sufficient for Stokes I continuum imaging and cheaper to simulate/image.
  `stokes="I"` at imaging time then averages RR/LL.
- **Equal per-channel noise convention:** for a clean apples-to-apples
  broadband taperability comparison, inject the **same** per-visibility
  noise (`simplenoise`) in every channel, rather than a value that varies
  with channel to mimic real receiver Tsys(freq) — this isolates the effect
  of broadband (u,v) coverage/weighting on eta from any frequency-dependent
  sensitivity variation. Document this as a simplification (a real receiver
  is not flat in Tsys across a wide fractional bandwidth), and note if/when a
  non-equal noise policy is later implemented.
- After creating (or reusing) an MS, **validate** the channelization:
  check the actual channel-centre frequencies and correlation codes recorded
  in the MS's spectral-window/polarization tables against what you intended,
  and fail loudly on mismatch rather than silently imaging the wrong band —
  a reused MS from an earlier, differently-configured run is a real failure
  mode when MSes are cached/reused across changes to a config file.

## Reuse and cost

Simulated MSes are expensive to (re)create (especially at 4 h track with many
antennas) and are pure noise, so a well-behaved simulator entry point should
**detect and reuse** an existing, validated MS rather than re-simulating
every run — but must validate it first (see above) so stale reuse doesn't
silently corrupt results.

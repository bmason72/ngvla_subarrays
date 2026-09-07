---
name: ngvla-imaging
description: "Do ngVLA (next-generation VLA) imaging-simulation work: read ngVLA .cfg antenna configurations and pick/compose subarrays (Core/Spiral/Mid/Main/Long/SBA, Rev C.01/D/E/F), simulate noise-only measurement sets with the CASA simulator, measure PSF/beam/eta/skirt quantities with tclean at niter=0, build and use taperability + beam-sculpting curves, and use the ngVLA sensitivity calculator. Use when asked to simulate ngVLA observations, generate or query taperability/sculptability curves, choose a subarray + robust/taper for a target resolution or sensitivity, or otherwise work with ngVLA antenna configs and CASA imaging simulations in any repo."
---

# ngVLA imaging-simulation work

Drafted 7 Sep 2026 against the `ngvla_subarrays` repo (a live implementation
of this exact workflow — its selection tool, curve-generation pipeline, and
docs are the primary evidence base here). Repo-specific numbers below are
labeled as such; treat them as **worked examples from one implementation**,
not universal constants — re-derive or re-measure them in a new repo rather
than hardcoding them across.

ngVLA imaging-simulation work moves through distinct layers, and most agent
mistakes come from skipping one or blurring two together:

> **Antenna config ≠ subarray. Native resolution ≠ requested resolution.
> Fitted restoring beam ≠ true half-power width. eta = 1 only at natural
> weighting. Point-source curve ≠ imaging (sculpted) curve. A mono
> (single-channel) curve does not scale to represent an MFS (broadband)
> curve. `$HOME` ≠ scratch. A queued Slurm campaign ≠ a safe time to edit
> the working tree it will `import`.**

## The layer stack (memorize this)

```
Antenna configuration (.cfg: X Y Z diam name per line)
  -> Component (Core / Spiral / Mid / Long / SBA)
    -> Subarray (a component, or a concatenation of components)
      -> Simulated MS (noise-only: sm.setnoise + sm.corrupt, no sky model)
        -> Dirty image + PSF (tclean, niter=0, one (weighting,robust,taper) point)
          -> Per-point measurements (eta, resolution/beam, PSF skirt)
            -> Taperability curve (eta vs. resolution): point-source & imaging (sculpted)
              -> Subarray selection (given target resolution/freq/sensitivity/LAS)
                -> Integration time / antenna-hours (sensitivity calculator)
```

Read `references/*.md` (below) for the layer you're touching; this file is
the map, not the full detail.

## 1. Antenna configurations and subarrays

ngVLA has design revisions **C.01, D, E, F** (F is current). Each revision's
antennas are grouped into disjoint **components** — nominally Core, Spiral,
Mid, Long (long-baseline), SBA (short-baseline array, smaller dishes) — read
from CASA-format `.cfg` files (`X Y Z diam name` per line, ITRF meters).
Composite **subarrays** (Core+Spiral, Main = Core+Spiral+Mid, Main+Long,
etc.) are formed by concatenating component `.cfg` files, since components
are antenna-disjoint. Station names carry a revision-specific prefix
(e.g. Rev F: `cor`, `spa`-`spe`, `mda`-`mde`, VLBA-style site codes for Long,
`sba` for the 6 m short-baseline array) — verify prefixes in whatever repo
you're in rather than assuming Rev F's.

**The Long/LBA array has a short-baseline peculiarity**: small (~3-antenna)
site clusters with baselines of only tens to ~200 m, alongside baselines of
tens to thousands of km. Those short intra-site baselines are real but
irrelevant to imaging and **must be filtered** (minimum uv-range cut) before
computing b_min, LAS, or any native-resolution quantity for Long or any
composite that includes it.

-> Full detail, the Rev F component/filename/prefix table, and the
LONG-filter cutoff derivation: `references/configurations.md`.

## 2. Simulating noise-only measurement sets (CASA `sm` tool)

Build a measurement set with `sm.setconfig` (from a `.cfg`'s antenna
positions) + `sm.setspwindow` + `sm.setfield` + `sm.settimes`/`sm.observe`,
then `sm.setnoise(mode="simplenoise", ...)` + `sm.corrupt()` — noise only, no
sky model or `sm.predict`. Two observing windows recur: a **4-hour transit
track** (real synthesis rotation) and a **single-dump snapshot**. A fixed
declination convention is used throughout a campaign (not physically
meaningful, just held constant for comparability).

For **multi-frequency-synthesis (MFS)** / broadband setups, get two things
right or the whole campaign is silently wrong: `sm.setspwindow`'s `freq`
wants the **first channel's** centre frequency, not the band's overall
centre (a common, easy-to-make error); and correlations are often narrowed
to `"RR LL"` for continuum work (vs. full `"RR RL LR LL"` for single-channel
legacy setups). A sound convention is to inject **equal** per-channel noise
across the band (isolating uv-coverage/weighting effects from any
frequency-dependent sensitivity model) — document this as a simplification.
Always **validate** a reused MS's actual channelization/correlations against
what the current run intends before trusting it.

-> Full detail: `references/simulation.md`.

## 3. Measuring PSF quantities with tclean (niter=0)

At each (weighting, robust, taper) grid point, run `tclean(..., niter=0)` to
get a dirty image + PSF, then measure:

- **eta**: this point's dirty-image rms / the natural-weighting untapered
  dirty-image rms from the same MS (eta = 1 by definition at natural).
- **resolution**: from CASA's fitted **restoring beam** — be aware this fit
  (Gaussian to pixels above `psfcutoff`, default 0.35) runs systematically
  *wider* than the true half-power width for composite/heterogeneous
  subarrays (measured up to ~1.3-1.6x in one campaign) — say explicitly
  which width you're reporting.
- **PSF skirt/shoulder**: azimuthally-averaged PSF value at one restoring-
  beam FWHM radius — the sculpting-relevant quantity (see §4).

Cell size should track the beam (a common rule: **5 pixels per beam FWHM**,
so cell shrinks as taper tightens); `imsize` is normally **fixed per
subarray** across a (robust, taper) sweep, since Briggs weighting's density
grid depends on the imaged field of view — changing `imsize x cell` between
points can silently change the weighting itself, not just the pixel grid.
For MFS: `specmode="mfs"`, `nterms=1` with `deconvolver="hogbom"` (not
MT-MFS, whose restoration is not rms-neutral even at niter=0), and note
`perchanweightdensity` **has no effect for MFS** (cube-only parameter) —
don't spend a sweep testing it.

-> Full detail, the psfcutoff/restoring-beam caveat with numbers, and the
consulted-expert MFS tclean guidance: `references/tclean-psf-measurement.md`.

## 4. Taperability curves and beam sculpting

Sweeping (robust, taper) and measuring (resolution, eta, skirt) at each
point produces, per subarray, two derived curves of eta vs. resolution:

- **point-source curve**: min-eta path to each resolution, skirt ignored —
  fine for detection work, where a messy PSF is acceptable.
- **imaging curve (sculpted)**: min-eta path to each resolution **subject
  to** skirt <= a threshold (a commonly used default: **10%** at one FWHM
  radius, per memo 121's phrasing — make it adjustable, not hardcoded).
  Where no combination meets the threshold, report that resolution as
  imaging-infeasible for the subarray rather than dropping it silently.

A curve tabulated at one reference frequency scales to another frequency by
scaling the resolution (and LAS) axis by the wavelength ratio, **assuming
eta is frequency-invariant** — a real assumption, spot-check it. **This
scaling does not apply to MFS/broadband curves**: a wide-bandwidth curve
already bakes in that band's own uv-filling behavior, so a different band
needs its own simulated/measured curve, not a rescale.

**LAS (largest angular scale, memo 67)** sets the largest recoverable
structure, roughly `0.6-0.85 * lambda / b_min` depending on array density
(memo 67's measured coefficients, not a pure geometric guess), scales with
wavelength, and must use the **filtered** b_min (see §1's Long peculiarity).

-> Full detail: `references/curves-and-sculpting.md`.

## 5. The ngVLA sensitivity calculator

`ngVLA_sensitivity_calculator.py` (memo 96) computes sensitivity/integration
time for a subarray:

```
./ngVLA_sensitivity_calculator.py <subarray> <frequency_GHz> <theta_arcsec> \
    [--t_obs HOURS] [--delta_v M_PER_S] [-v] [--calc_minmax_theta]
```

`subarray` is one of a fixed, calculator-internal name set (verify against
`-h` output or the pickled subarray-data table in whatever install you're
using — it will not necessarily include every subarray your own selection
tool defines; a repo-specific composite like `core+mid` was found **missing**
from one delivered data table and had to be added locally). `theta=-1`
computes the native (natural, untapered) resolution instead of using a
supplied one. **SBA uses 6 m dishes** and is commonly treated as not
supporting UV tapering — check this explicitly if SBA is in scope. Needs
`scipy >= 1.0`; runs under CASA 6 / Python 3 (not CASA 5). A robust
integration pattern: call the calculator only for the **natural-weighting**
point-source rms at a subarray's native resolution (where its internal eta
model is exactly 1 by construction), then apply your **own** measured eta
from your taperability curves — this decouples your results from the
calculator's own (possibly differently-vintaged) eta spline.

## 6. Operational hygiene on HPC

- **Never run CASA (or any tclean/TempLattice-producing task) with cwd under
  `$HOME`** — home quotas are small and CASA writes large scratch lattices
  to the process's *current working directory*, not a configurable temp
  path.
- Tier storage: durable MS/results on persistent storage, tclean scratch on
  purge-eligible scratch, nothing on `$HOME`.
- Make sweeps **resumable**: record every measured/skipped/failed point keyed by
  its grid coordinates, skip what's already recorded, never let one bad
  tclean call abort a whole campaign.
- **Do not edit a working tree while a Slurm campaign's stages are queued or
  running against it** — later stages typically `import` project code fresh
  from disk at start time, so an in-flight edit can silently corrupt or
  invalidate the run. Use a separate checkout for concurrent code work.
- Respect shared-queue etiquette (a soft cap on outstanding queued jobs is
  common). **Agents should prepare exact command lines and let the human
  operator submit them**, unless explicitly delegated to launch jobs
  directly — treat this as the default, not the exception.

-> Full detail: `references/hpc-operations.md`.

## 7. Common mistakes

- Computing b_min/LAS from unfiltered Long-array baselines (spurious ~100 m
  clusters dominate and give a badly wrong, too-small LAS).
- Passing the band-centre frequency to `sm.setspwindow`'s `freq` for an MFS
  setup instead of the first-channel centre.
- Reporting the tclean restoring beam as "the resolution" for a composite
  subarray without noting it can run 1.3-1.6x wider than the true half-power
  width.
- Treating the point-source curve and the imaging (sculpted) curve as
  interchangeable — they diverge exactly where PSF quality matters, i.e.
  precisely the cases an imaging project cares about.
- Frequency-scaling an MFS/broadband curve as if it were a mono curve.
- Assuming a sensitivity calculator's built-in subarray list and eta model
  cover every subarray/vintage your own tool defines — verify, don't assume.
- Running any tclean/CASA process with cwd on `$HOME`, or editing a working
  tree mid-Slurm-campaign.
- Launching Slurm jobs on the operator's behalf without being asked to.

## Where to read more

- **Memos** (numbers only — locate the actual PDF/txt in whatever repo
  you're in): **67** (LAS), **65** and **121** (beam sculpting, skirt
  threshold, worked robust/taper-vs-skirt/eta grids), **76** (natural-taper
  vs. Briggs-robust framing, subarray-selection LUT), **72** and **55**
  (taperability-curve concept/history), **96** (sensitivity calculator /
  Tsys).
- **This skill's references**: `references/configurations.md`,
  `references/simulation.md`, `references/tclean-psf-measurement.md`,
  `references/curves-and-sculpting.md`, `references/hpc-operations.md`.
- **The `ngvla_subarrays` repo** (worked example this skill was drafted
  from): its `CLAUDE.md` (task statement + domain concepts), `README.md`
  (layout/commands), `docs/GLOSSARY.md`, `docs/architecture/
  selection-tool-design.md`, `docs/architecture/PSF_DIAGNOSTICS.md`,
  `docs/ops/casaLocation.md`, `docs/ops/RUN_CAMPAIGNS.md`, and its
  `curvegen/` package (`config.py`, `simulate.py`, `sweep.py`) for a live,
  evolving implementation of every layer above.

# ngVLA configuration files and subarray composition

## Revisions

`ngvla-configurations/` (as laid out in the `ngvla_subarrays` repo) carries
antenna-position `.cfg` files for four design revisions: **C.01**, **D**,
**E**, and **F**. **Rev F is current** (as of this writing, Sep 2026) and is
what new work should target unless a task specifically calls for an older
revision (e.g. reproducing an older memo's numbers). Rev F files live under
`Rev F/CASA Files/`.

## The CASA `.cfg` format

Each line is one antenna, whitespace-separated:

```
X Y Z diam name
```

`X Y Z` are ITRF geocentric coordinates in meters, `diam` is the dish
diameter in meters, `name` is the station/antenna name. Lines starting with
`#` are comments (usually provenance: who generated the file, when, from
what source). This is the format `casatasks.private.simutil.simutil.readantenna`
reads directly, and the format all antenna-position math (baseline lengths,
b_min/b_max) should be done in.

## Rev F components (repo example: `ngvla_subarrays/ngvla-configurations/Rev F/CASA Files/`)

| Component | File | N_ant | Station prefix(es) | Diameter |
|---|---|---|---|---|
| Core | `RevF_Core_2025_01_27_xyz.cfg` | 114 | `cor` | 18 m |
| Spiral | `RevF_Spiral_2025_01_16_xyz.cfg` | 54 | `spa`..`spe` | 18 m |
| Mid (MidSitesPreferred) | `RevF_MidSitesPreferred_2025_01_16_xyz.cfg` | 46 | `mda`..`mde` | 18 m |
| Long | `RevF_Long_2025_01_16_xyz.cfg` | 30 | VLBA-style site codes (`br`, `gb`, `hi`, `hn`, `hp`, `im`, `ku`, `nl`, `ov`, `pr`), ~3 antennas per site | 18 m |
| SBA (short-baseline array) | `RevF_SBA_2025_01_16_xyz.cfg` | 19 | `sba` | **6 m** |
| Main | `RevF_Main_xyz.cfg` | 214 | (union of `cor`/`spa-e`/`mda-e`) | 18 m |

Core + Spiral + Mid are **disjoint** and sum to 114+54+46 = 214 = Main; `Main`
is a separate delivered file but is antenna-for-antenna identical to
concatenating Core+Spiral+Mid. Long and SBA are separate arrays entirely (not
subsets of Main).

Earlier revisions mirror this component structure with different filenames
and antenna counts (e.g. Rev D/C.01 core/spiral/mid/lba; Rev D's "long" file
is actually named `lba` — long-baseline array). Always resolve names through
whatever the current repo's config layer does (e.g. `curvegen/config.py`'s
`_COMPONENT_CFGS`), not by guessing filenames — component filenames and
antenna counts have changed between revisions and even between deliveries of
the same revision.

## Composite subarrays

Because the components are disjoint, forming a composite subarray (e.g.
Core+Spiral, Main+Long) is literally concatenating the relevant `.cfg` files
(after stripping `#` headers from all but the first). No coordinate
transformation or antenna renaming is required — station names across
components don't collide.

A repo will typically also want **named station subsets** of a component,
not just whole components — e.g. memo 121's `core-inner`/`core-outer` split
(innermost/outermost N antennas of the Core by radius from the core
centroid). These require picking specific antenna names/rows out of a
component file, not just concatenation; verify subset membership against
whatever the "official" delivered subset config is before trusting your own
radius cut.

## The LONG short-baseline peculiarity (verify this exists in any repo you work in)

The Long/LBA configuration mixes VLBA-style **site clusters**: within one
site there are ~2-4 antennas separated by tens to a couple hundred meters,
while between sites the baselines jump to tens or thousands of kilometers.
In the `ngvla_subarrays` repo (Rev F Long, measured): internal site
baselines run **37-176 m**, then there is a **~2900x gap** up to the first
inter-site baseline. These short intra-site baselines are physically real
(kept in any simulated MS) but are **irrelevant to imaging resolution/LAS**
and must be excluded when computing b_min, LAS, or any per-subarray
"native resolution" quantity — otherwise b_min is dominated by meaningless
100 m spacings and both LAS and the coarse end of the taperability curve
come out wrong.

- Filter by **minimum uv-range** (in the simulated MS, an image-time
  `uvrange=">Nm"` selection; on raw antenna coordinates, a baseline-length
  cut), not by antenna exclusion — the antennas themselves are legitimate,
  only their mutual short baselines are excluded.
- The exact cutoff is revision- and combination-specific: it must sit inside
  the gap between the spurious cluster and the first real long baseline, and
  must not accidentally remove real short baselines contributed by another
  component in a heterogeneous combination (e.g. Main+Long is usually **not**
  filtered because Core's own legitimate baselines are shorter than the Long
  cluster cut would be). A rev with a different Long/LBA layout will have a
  different gap and cutoff — measure the gap from your own baseline-length
  histogram before picking a cut, don't reuse another repo's or revision's
  number unchanged.
- Apply the cut **uniformly**, including to the natural-weighting reference
  point, so that ratios like eta (rms relative to natural) stay
  self-consistent.
- `artifacts/saUtil.py::filter_spurious_shorts(sa_list, sa_filt_list,
  bfilt=150.0)` in the `ngvla_subarrays` repo is a minimal reference
  implementation (drop baselines below `bfilt` meters) — read it as a
  sketch of the idea, not a vetted default; its default 150 m does not match
  every revision's measured gap (Rev F Long production work landed on 178 m
  after measuring the actual gap, per that repo's `curvegen/config.py`).

## SBA specifics

SBA uses 6 m dishes (vs. 18 m for everything else), which changes its
primary beam / field of view and its sensitivity scaling. Any sensitivity or
FOV calculation must branch on this. SBA is also commonly treated as
**not supporting UV tapering** in ngVLA sensitivity tooling (verify against
whatever calculator/tool you're using — see `sensitivity-calculator.md`).

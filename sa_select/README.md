# `sa_select` — standalone NGVLA subarray selector

Given an observing request (resolution, frequency, sensitivity, LAS, …) this
returns a **ranked list of NGVLA subarrays** with the `tclean` parameters
(Briggs `robust` + UV `taper`) to reach the beam, the sensitivity-loss factor
`eta`, the PSF skirt, the LAS, and — using an explicit or fiducial goal — the
**integration time** and **antenna-hours**. It reads pre-tabulated curve data;
it also estimates raw data volume as the number of visibilities in the
observation. **It does not need CASA** and runs anywhere with Python + numpy +
scipy.

**Campaigns** (routed via `data/config_registry.csv`; select with
`--rev/--sim-mode` or `CurveLibrary.for_config`): Rev F track is the default;
Rev D track and the snapshot tables exist; Rev C.01 track is registered and
fills in when its campaign runs. Release scope (Aug 2026): Rev F track
point-source+imaging; Rev D and Rev C.01 track point-source only — an
imaging query against those prints a warning.

The same registry now also carries the in-progress Rev F Ka-band MFS campaign
rows. They are fixed-window native products and are intentionally filtered out
of `CurveLibrary.for_config` until the band-aware selector/report consumer is
implemented; this prevents the legacy 30/f scaling from being applied to MFS.

## Install or run from a checkout

The calculator is a normal Python package. Its curve tables and Memo-96
sensitivity backing data are package resources; it does not require TACC,
CASA, pickle files, or a sibling calculator checkout.

```bash
git clone <repo-url> ngvla && cd ngvla
python3 -m pip install .
sa-select --help
```

For development, `python3 -m sa_select ...` works directly from the repository
root. `sa-select --data-info` reports all registered campaigns, the backing
data schema, provenance, and source checksums. Before publishing a wheel beyond
the collaboration, confirm the redistribution terms noted by that command.

## Use it

**CLI:**
```bash
python3 -m sa_select --resolution 0.01 --frequency 30 --sensitivity 1e-5 \
                     --las 0.5 --imaging --optimize antenna_hours
# Omit --sensitivity to rank against the natural, untapered MAIN sensitivity
# in one minute. --point-source ignores skirts; --unit K selects a K goal;
# --delta-v <m/s> for a spectral-line rms; --rows for CSV output;
# --beam-margin 0 requests exact matching; --skirt-threshold is arbitrary;
# --mixed-skirt-ranking opts out of strict-first imaging ranking.

python3 -m sa_select --batch cases.csv --top 3   # EOP-style case list -> CSV
# columns: case,resolution,frequency,sensitivity,sensitivity_unit,las,
#          imaging,beam_margin,skirt_threshold,strict_first,optimize,delta_v
# (empty cells fall back to the command-line flags)

python3 -m sa_select --stroh subarray_data.json --resolution 0.1 \
                     --frequency 30 --point-source
# query M. Stroh's curve delivery directly (sa_select/stroh.py: converts his
# sqrt(2) beam convention; point-source only; taper values are placeholders)
```

**Python:**
```python
from sa_select import ObservingRequest, select_subarrays

req = ObservingRequest(resolution=0.01, frequency=30.0,   # arcsec, GHz
                       sensitivity=1e-5,                   # Jy/beam (or K, see unit)
                       las=0.5, imaging=True,
                       optimize="antenna_hours")           # or "integration_time"
result = select_subarrays(req)

print(result.table())          # readable summary + why each SA was excluded
best = result.best             # cheapest feasible Candidate (or None)
rows = result.to_rows()        # list[dict], drops into a DataFrame
summary = result.to_summary()  # structured warnings/ranking status
```

Each `Candidate` carries: `subarray`, `n_ant`, `eta`, `weighting/robust/taper`,
`skirt`, `las`, `integration_time_hr`, `antenna_hours`, `feasible`, `reasons`
(why excluded), `warnings`, structured skirt status, cost status, goal origin,
and `n_visibilities`. The visibility estimate is
`n_ant * (n_ant - 1) / 2 * integration_time / 5 s`; it assumes one channel and
no autocorrelations. The human-readable table reports SI units such as MVis and
GVis. `to_rows()` also returns the dump time and channel-count assumptions. For
imaging, skirt-met candidates rank ahead of relaxed candidates;
each group is ordered by the requested cost metric. A structured
`NO_SUBARRAY_MEETS_SKIRT` warning is returned if the strict group is empty.

## How sensitivity is computed

The integration time uses the natural-weighting kernel and receiver/subarray
tables from the Memo-96 ngVLA sensitivity calculator, packaged as inert JSON,
scaled by our curve-derived `eta` and the radiometer equation. When no explicit
goal is supplied, the common goal is natural, untapered MAIN in one minute at
the requested frequency and spectral setup. Note the calculator's anchor is
N_ant-based and does not model the spurious-short-baseline filter, so the
absolute sensitivity for `long` alone is ~3.6 % optimistic (negligible for the
combinations); imaging-quality (`eta`, skirt) is unaffected.

The backing rms already contains the radiometer factor `N(N-1)`. The optional
`n_ant_actual` correction replaces a stale nominal revision count, or completes
a MAIN-donor rescale for a subarray missing from the backing calculator. It is
unity when nominal and actual counts agree. Multiplying final time by the
actual count to obtain antenna-hours is resource accounting, not a second
sensitivity factor.

## Data

- `data/subarrays.csv` — per-subarray N_ant, baselines, LAS coefficient,
  calculator key.
- `data/revf_curves.csv` — the authoritative Rev F (resolution, eta, skirt,
  robust, taper) samples from `curvegen/` (the default).
- `data/bootstrap_curves.csv` — the older memo-121 stand-in; pass
  `CurveLibrary(samples=…)` to use it.
- `data/sensitivity_data.json` — portable Memo-96 receiver/subarray tables and
  source-count data. Maintainers can regenerate and round-trip-check it with
  `data/export_sensitivity_data.py` from trusted upstream files.

## Scope / caveats (v1)

Fixed-FOV single-pointing convention (memo 121); no mosaics or varying FOV;
continuum vs spectral-line fractional-bandwidth uv-filling not modelled. The
imaging policy is threshold-relax: meet skirt ≤ s₀ (default 0.10) with the
cheapest beam where achievable, else report the best achievable skirt (flagged).

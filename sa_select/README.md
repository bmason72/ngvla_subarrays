# `sa_select` — standalone NGVLA subarray selector

Given an observing request (resolution, frequency, sensitivity, LAS, …) this
returns a **ranked list of Rev F subarrays** with the `tclean` parameters
(Briggs `robust` + UV `taper`) to reach the beam, the sensitivity-loss factor
`eta`, the PSF skirt, the LAS, and — when a sensitivity goal is given — the
**integration time** and **antenna-hours**. It reads pre-tabulated curve data;
**it does not need CASA** and runs anywhere with Python + numpy + scipy.

## Minimal checkout (run it on any machine)

You only need two sibling directories from the repo plus this package's data:

```
<repo>/
├── sa_select/                     # this package (+ sa_select/data/*.csv)
└── ngvla-sensitivity-calculator/  # the memo-96 / ngECT calculator + its .pkl
```

`sa_select/sensitivity.py` locates the calculator at `../ngvla-sensitivity-calculator`,
so keep that relative layout. A git sparse checkout gets exactly this:

```bash
git clone --no-checkout <repo-url> ngvla && cd ngvla
git sparse-checkout init --cone
git sparse-checkout set sa_select ngvla-sensitivity-calculator
git checkout
python3 -m pip install numpy scipy        # the only dependencies; no CASA
```

## Use it

**CLI:**
```bash
python3 -m sa_select --resolution 0.01 --frequency 30 --sensitivity 1e-5 \
                     --las 0.5 --imaging --optimize antenna_hours
# --point-source for detection projects; --unit K for a brightness-temp goal;
# --delta-v <m/s> for a spectral-line rms; --rows for CSV output; --help for all.
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
```

Each `Candidate` carries: `subarray`, `n_ant`, `eta`, `weighting/robust/taper`,
`skirt`, `las`, `integration_time_hr`, `antenna_hours`, `feasible`, `reasons`
(why excluded) and `warnings` (e.g. a relaxed skirt criterion).

## How sensitivity is computed

The integration time comes from a **live call** to the memo-96 ngVLA sensitivity
calculator (`ngvla-sensitivity-calculator/`) for the natural-weighting rms,
scaled by our curve-derived `eta` and the radiometer equation — *not* a
pre-baked table (the HTML report does pre-tabulate, for a no-Python page; this
package calls the calculator directly). Note the calculator's anchor is
N_ant-based and does not model the spurious-short-baseline filter, so the
absolute sensitivity for `long` alone is ~3.6 % optimistic (negligible for the
combinations); imaging-quality (`eta`, skirt) is unaffected.

## Data

- `data/subarrays.csv` — per-subarray N_ant, baselines, LAS coefficient,
  calculator key.
- `data/revf_curves.csv` — the authoritative Rev F (resolution, eta, skirt,
  robust, taper) samples from `curvegen/` (the default).
- `data/bootstrap_curves.csv` — the older memo-121 stand-in; pass
  `CurveLibrary(samples=…)` to use it.

## Scope / caveats (v1)

Fixed-FOV single-pointing convention (memo 121); no mosaics or varying FOV;
continuum vs spectral-line fractional-bandwidth uv-filling not modelled. The
imaging policy is threshold-relax: meet skirt ≤ s₀ (default 0.10) with the
cheapest beam where achievable, else report the best achievable skirt (flagged).

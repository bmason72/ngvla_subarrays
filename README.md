# NGVLA subarray selection

A stand-alone Python tool that, given a desired resolution, frequency, sensitivity,
and largest angular scale (LAS), returns a ranked list of NGVLA Rev F subarrays with
the `tclean` weighting parameters (Briggs robust / uv taper) that achieve the
requested beam — minimizing integration time or antenna-hours — plus the CASA
pipeline that generates the underlying taperability/sculptability curves.

**Start here:** `PLAN.md` is the living status document (task table §10, decisions,
gotchas §13). `CLAUDE.md` is the task statement and repo map for coding agents.

## Layout

| Path | What it is |
|------|-----------|
| `sa_select/` | The selection tool (pure Python + numpy at query time, no CASA). `schema.py` documents units and data-table columns in its docstring. |
| `sa_select/data/` | Curve tables: `bootstrap_curves.csv` (memo-121 stand-in, the current default), `revf_curves.csv` (Rev F simulated curves, homogeneous subarrays), `subarrays.csv` (per-subarray facts), `build_bootstrap_data.py` (regenerates the first and third). |
| `curvegen/` | Rev F curve generation under CASA: `config.py` (grids — the only file to tweak), `build_configs.py`, `simulate.py`, `sweep.py` (resumable lattice sweep), `refine.py` (adaptive refinement), `collect.py` (→ `revf_curves.csv`), `make_report.py` + `report_template.html` (local HTML report). `results/*.csv` are the measured points (tracked); `ms/`, `work/`, `reports/` are regenerable (ignored). |
| `tests/` | 28 stdlib-unittest tests incl. memo-121 replay validation. |
| `ngvla-configurations/`, `ngvla-sensitivity-calculator/`, `ngvla-taperability-pipeline/`, `memos/`, `memo*/`, `artifacts/` | Upstream raw materials (see CLAUDE.md). |

## Environment

Everything runs under **any CASA 6.5+ Python** (needs `casatools`, `casatasks`,
`numpy`, `scipy`). Nothing imports a hard-coded CASA path; on macOS we used
`/Applications/CASA.app/Contents/MacOS/python3`, on Linux either monolithic CASA's
`python3` or a modular install:

```bash
python3 -m venv casaenv && . casaenv/bin/activate
pip install casatools casatasks numpy scipy      # modular CASA (Linux/macOS)
```

Only `curvegen/` needs CASA. `sa_select/` needs just numpy + scipy (scipy only for
the sensitivity calculator underneath).

## Commands (run from the repo root unless noted)

```bash
# selection tool
python3 -m sa_select --resolution 0.005 --frequency 80 --sensitivity 1e-6 --imaging
python3 -m unittest discover -s tests -t .          # test suite

# curve generation (from curvegen/) — all resumable, safe to re-run
python3 build_configs.py            # subarray .cfg files
python3 sweep.py core               # simulate + sweep one subarray
python3 refine.py core              # adaptive refinement where the curve jumps
python3 collect.py                  # results/*.csv -> sa_select/data/revf_curves.csv
python3 make_report.py reports/revf-curves.html     # local HTML report (open in browser)
```

## Picking up on a new machine

1. Clone/copy this repo (it is plain git; `curvegen/ms|work|reports` are ignored and
   regenerable — everything needed is tracked).
2. Install a CASA 6 Python as above; run the test suite to confirm the tool works.
3. Re-simulate + sweep whatever you need: MSes are *not* in git, but
   `sweep.py <subarray>` recreates them and skips all recorded lattice points, so a
   fresh machine reaches the current state by re-simulating only (minutes for the
   4096-pixel subarrays). With more compute, the deferred heavyweights (core+mid,
   main; imsize 15000) and denser lattices are the next targets — see PLAN.md
   "Still open" and the v2/v2.1 sections for exactly where work stopped and why.

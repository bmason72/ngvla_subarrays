# NGVLA subarray selection

A stand-alone Python tool that, given a desired resolution, frequency, sensitivity,
and largest angular scale (LAS), returns a ranked list of NGVLA subarrays with
the `tclean` weighting parameters (Briggs robust / uv taper) that achieve the
requested beam — minimizing integration time or antenna-hours — plus the CASA
pipeline that generates the underlying taperability/sculptability curves. The
ranked results also estimate the number of raw visibilities for one channel and
a 5 s correlator dump time.

**Release scope (Aug 2026, see `WRAPUP.md` + `RELEASE_PLAN.md`):** the released
products are the web page (`make_report.py --combined --release`) and the
`sa_select` Python calculator for **Rev F 4-h track** (point-source and
imaging), **Rev D 4-h track** (point-source), and **Rev C.01 4-h track**
(point-source). Snapshot campaigns exist but are internal.

**Start here:** `RELEASE_PLAN.md` (current plan) → `PLAN.md` (history, decisions,
gotchas §13) → `RUN_CAMPAIGNS.md` (Slurm run sheet). `CLAUDE.md` is the task
statement and repo map for coding agents; the memo (`memo/ngvla_sa_selection.tex`)
documents the method, the runbook, and the Python interface. `PSF_DIAGNOSTICS.md`
covers how the reports measure and present PSF quality (half-power width,
restoring beam, confusion, nearest-PSF lookup).

## Layout

| Path | What it is |
|------|-----------|
| `sa_select/` | The selection tool (pure Python + numpy at query time, no CASA). `schema.py` documents units and data-table columns. `stroh.py` reads M. Stroh's delivery formats (.cfg subarrays + subarray_data.json curves). |
| `sa_select/data/` | Per-campaign curve + metadata tables, routed by `config_registry.csv` on `(rev, sim_mode, band)`; an empty band is a legacy mono campaign and `band4` is the in-progress Ka MFS campaign. |
| `curvegen/` | Curve generation under CASA: `config.py` (grids + campaign axes), `simulate.py` (mono/MFS MS creation and validation), `campaign_manifest.py` (immutable MFS provenance), `sweep.py` (resumable imaging), `refine.py` and `adaptive.py` (refinement/sampling), plus collect/report tooling. `results*/` CSVs are tracked; `ms/`, `work/`, `reports/` are regenerable. |
| `tests/` | Stdlib-unittest regression suite, including memo-121 replay and CASA-free MFS contracts. |
| `memo/` | The LaTeX memo (`make pdf`). |
| `ngvla-configurations/`, `ngvla-sensitivity-calculator/`, `ngvla-taperability-pipeline/`, `memos/`, `memo*/`, `artifacts/` | Upstream raw materials (see CLAUDE.md). |

## Environment

Everything runs under **any CASA 6.5+ Python** (needs `casatools`, `casatasks`,
`numpy`, `scipy`). On TACC Stampede3 use the `casapy` wrapper
(`/work2/10240/bmason72/stampede3/casaenv/bin/casapy`; see `casaLocation.md`).
Only `curvegen/` needs CASA. `sa_select/` needs just numpy (+ scipy for the
sensitivity calculator and Stroh splines).

```bash
python3 -m venv casaenv && . casaenv/bin/activate
pip install casatools casatasks numpy scipy      # modular CASA (Linux/macOS)
```

## Commands (run from the repo root unless noted)

```bash
# selection tool
python3 -m sa_select --resolution 0.005 --frequency 80 --sensitivity 1e-6 --imaging
python3 -m sa_select --resolution 0.005 --frequency 30 --rev revD --point-source
python3 -m sa_select --batch cases.csv --top 3       # EOP-style case list
python3 -m sa_select --stroh mstroh/subarray_data.json --resolution 0.1 \
        --frequency 30 --point-source                # query Stroh's curves
python3 -m unittest discover -s tests -t .           # test suite

# curve generation (from curvegen/) — all resumable, safe to re-run
python3 build_configs.py            # subarray .cfg files
python3 sweep.py core               # simulate + sweep one subarray
python3 refine.py core              # escalating refinement where curves jump
python3 collect.py                  # results/*.csv -> registered mono or native-MFS curves CSV
python3 make_report.py reports/revf-curves.html               # one campaign
python3 make_report.py --combined reports/ngvla-curves.html   # ALL campaigns
python3 make_report.py --combined --release \
        reports/ngvla-curves-release.html            # the RELEASED page

# campaigns on TACC (Slurm; see RUN_CAMPAIGNS.md for the full sheet)
bash curvegen/submit_campaign.sh revC track --time 47:00:00
sbatch --array=0,2 curvegen/adaptive_retrofit.sbatch  # retrofit tracks
# isolated, simulation-only Ka snapshot nchan/RSS pilot (one queue slot)
bash curvegen/submit_mfs_snapshot_sim_pilot.sh
```

The MFS snapshot pilot creates only the core/main measurement sets for
`nchan=27,54` (0.5 and 0.25 GHz across Band 4), with an isolated manifest and
scratch path per channel count. It is safe to launch before production nchan
is chosen. The 54-channel run is a focused convergence check, not the start of
a large powers-of-two ladder. It does **not**
authorize or run the production adaptive snapshot campaign; inspect its memory
logs, finish the imaging convergence/replay gates, and record the nchan/noise
decision first (see `RUN_CAMPAIGNS.md` and `MFS_CAMPAIGN_PLAN.md`).

## Picking up on a new machine

1. Clone/copy this repo (plain git; `curvegen/ms|work|reports` are ignored and
   regenerable — everything needed is tracked).
2. Install a CASA 6 Python as above; run the test suite to confirm the tool works.
3. Re-simulate + sweep whatever you need: MSes are *not* in git, but
   `sweep.py <subarray>` recreates them and skips all recorded lattice points,
   so a fresh machine reaches the current state by re-simulating only.

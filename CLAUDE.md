# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Freshness (17 Aug 2026; task statement only — see git log for edit history of the
> rest of this file):** the task statement, domain concepts, and raw-materials map
> below remain authoritative.  The *built* system now lives in `sa_select/` (selection
> engine) + `curvegen/` (CASA curve generation + campaigns + HTML reports) — see
> `docs/plans/WRAPUP.md` for bmason's current release scope, `docs/plans/RELEASE_PLAN.md` for the live plan,
> `README.md` for layout/commands, `docs/plans/PLAN.md` for status/decisions/gotchas,
> `docs/plans/NEXT_AGENT.md` for the hand-off, `docs/ops/RUN_CAMPAIGNS.md` for the Slurm run sheet,
> and `docs/architecture/PSF_DIAGNOSTICS.md` for how the reports measure and present PSF quality.
> Where this file and those disagree (environment especially), trust them.
> Session deltas now append to `docs/plans/PLAN-session-log.md`; `docs/INDEX.md` lists every doc.
> bmason launches all Slurm jobs himself — agents prepare command lines only.

## Project goal (the task)

Produce a stand-alone Python routine that takes as input a desired resolution, frequency,
sensitivity, and largest angular scale (LAS), and uses that to select an NGVLA (nominally
RevF) subarray from a set list of subarrays, along with `tclean` parameters that will
achieve the requested beam within some tolerance, while minimizing either a) actual
integration time or b) antenna hours used.

- Sensitivity parameters are nominally a Briggs `robust` value and/or a UV (outer) `taper`.
- Another input is "is this an imaging project" (vs point-source detection). Imaging
  projects are subject to further PSF-quality constraints; point-source detection projects
  can use a messy PSF provided they meet the desired beam size.
- The beam-size margin defaults to 5% but must be specifiable.

**Approach:** Pre-tabulate resolution vs. sensitivity-loss (relative to natural weighting)
curves for each subarray at a central reference frequency (~30 GHz), then scale to the
requested frequency (scaling both resolution and LAS). Each subarray has an associated LAS
computed per NGVLA memo 67. Assume LAS is independent of taper and robust (optionally
verify). There are **two curves per subarray**: a *point-source* curve and an *imaging*
curve. The imaging curve adds the memo-65/121 criterion that the beam is "sculpted" so the
near-in sidelobe (the "skirt"/"shoulder") of the PSF is below an adjustable threshold — use
a sensible default motivated by the recent memos.

The function returns a ranked list of subarrays that meet the request, with their imaging
parameters, sensitivity-loss values, antenna hours, and other metadata — easily accessed and
manipulated in Python. **The code should be readable by an astronomer.**

`ngvla-taperability-pipeline/` implements the taperability-curve part of this, but **not** the
sculpting part. Bonus points if the code interfaces with the sensitivity calculator to also
return an integration time for the selected array + imaging parameters.

## Key domain concepts

See `docs/GLOSSARY.md` for one-line definitions of terms used across the docs
(eta, combo, anchor, canonical taper, and the rest), each pointing to the
document that defines it in depth. The subsections below give the fuller
domain-concept explanations for the core terms.

- **eta (inefficiency factor):** image rms at a given resolution divided by the natural-weight
  rms (natural = 1.0, the sensitivity-optimal point). Taperability curves plot eta vs.
  resolution. See memos 55, 72, 76.
- **Two ways to change resolution:** natural weighting + UV taper (moves toward *coarser*
  resolution, right of native) vs. Briggs robust weighting +/- taper (moves toward *finer*
  resolution and improves beam quality). See memo 76.
- **LAS (memo 67):** ~0.6 λ/b_min for the SBA and up to ~0.85 λ/b_min for the core; measured
  from disk simulations. Scales with frequency (∝ λ).
- **Beam sculpting (memos 65, 121):** choosing robust/taper so the PSF near-in sidelobe
  ("skirt"/"shoulder") stays below a threshold — the extra constraint distinguishing the
  imaging curve from the point-source curve.
- **LONG subarray peculiarity:** it has small groups of ~3 antennas with very short (~100 m)
  baselines plus multi-thousand-km baselines. The short baselines are irrelevant to imaging
  and must be filtered out (see `filter_spurious_shorts` in `artifacts/saUtil.py`, default
  cut ~150 m).
- **Frequency scaling:** the `plot_csv_data*` helpers scale resolution columns by
  `freq/30.0` from the 30 GHz reference; time-based y-axes use `(214/N_ant * eta)**2` (time)
  or `(214 * eta)**2 / N_ant` (antenna-time), where 214 is the full main-array antenna count.

## Repository layout

- `ngvla-configurations/` — antenna position `.cfg` files (CASA XYZ format: X Y Z diam name)
  for Rev C.01, D, E, and **F** (the target). Rev F files are under `Rev F/CASA Files/`
  (Core, Spiral, Main, MidSitesPreferred, Long, SBA). Subarrays are formed by combining these.
- `ngvla-taperability-pipeline/` — Viviana Rosero's CASA pipeline that produces a taperability
  curve for one config. `run_all.py` is the only file meant to be edited; it sequentially
  `exec()`s `create_sim_ms.py` → `create_images.py` → `analyze_images.py`. Runs under CASA 6.
  Outputs a `taperability-{config}/` folder with the sim MS, residual/PSF images,
  `taperability_table.txt`, and plots. **Does not implement sculpting.**
- `ngvla-sensitivity-calculator/` — Viviana Rosero's sensitivity calculator (memo 96). Key
  entry points in `ngVLA_sensitivity_calculator.py`: `calculate_sensitivity(subarray, freq,
  theta, t_obs, delta_v, ...)` and `sigma_ps_fn(subarray, freq, type_cal, t_int, N_ant, theta,
  ...)`. Reads `receiver_data.pkl` and `subarray_data.pkl` (numpy pickles). Runs from the CLI
  (`./ngVLA_sensitivity_calculator.py -h`) or by importing the functions. Needs scipy >= 1.0;
  works in CASA 6 / Python 3, not CASA 5. Note SBA uses D=6 m and does not support tapering.
- `artifacts/` — **notional sketches** of the future EOP (Envelope Observing Program) subarray
  assignment, not the intended final approach (they cut corners). `saUtil.py` holds candidate
  logic: `identify_longest_sa`, `choose_longest_sa` (strategies: `lowestAntHrs`, `minMatching`,
  `manual`, `sa_new`), baseline computation from `.cfg` files, `getband(freq_GHz)`, LAS/time
  bookkeeping, station-usage tallies, and CSV/plot helpers. **Take `saUtil.py`'s implementations
  and approaches with a grain of salt** — reuse pieces if genuinely useful, but do not assume any
  given routine is the correct approach to its problem; verify before adopting. `assign_eop_sa.py`
  is a scratch driver (bare top-level code, undefined names — read it as notes, not runnable).
- `memo121artifacts/` — Viviana's memo-121 Rev-? subarray assignments as CSVs (`Main.csv`,
  `Efficient.csv`, `Performance.csv`) plus machine-cleaned variants (`*Cln.csv` add columns like
  `Nantennas`, `res_nat`, `eta_nat`, `robust`, `eta_rob`). See `memo121artifacts/notes.txt` for
  which files are cleaned. These are the closest existing example of per-case SA + imaging-param
  assignments.
- `memo67scripts/` — CASA scripts behind memo 67's LAS analysis (disk sims of core/SBA/SD,
  30 Dor). Reference for how LAS was measured.
- `memos/` — NGVLA memos as both `.pdf` and `.txt`. Most relevant: **67** (LAS), **65 & 121**
  (sculpting), **76** (SA selection LUT, robust vs. taper), **72 & 55** (taperability curves),
  **96** (sensitivity/T'sys), **106**, `ssa_update`.
- `notes.txt` — the user's running design notes and the evolving "new paradigm for science SA
  selection." Read this for intent and history.

## Environment & commands

> **Campaign freeze (rule; no freeze currently active — 8 Sep 2026):** while any
> campaign stage is queued or running, do not edit `curvegen/`, `sa_select/`, or
> `sa_select/data/*.csv` on `main`: each Slurm stage re-imports them from this
> checkout when it starts.  Code work goes in a separate git worktree and
> merges after collect has finished and been checked.  Live freeze window:
> `docs/worklog/mfs-campaigns.md`.


- **This IS a git repo** (since 5 Jul 2026, branch `main`); commit at milestones, and only
  when the user has asked or a milestone commit is queued in `docs/plans/PLAN.md`.
- **Current platform is TACC Stampede3** — use the `casapy` wrapper
  (`/work2/10240/bmason72/stampede3/casaenv/bin/casapy`, modular CASA 6.7.5 + numpy/scipy);
  see `docs/ops/casaLocation.md` for the wrapper rationale and quota/TempLattice gotchas, and
  `docs/ops/RUN_CAMPAIGNS.md` for Slurm campaign submission.  Tests:
  `casapy -m unittest discover -s tests -t .` from the repo root.
- Big data placement: MS stores persist under `$WORK/ngvla_curvegen` (`NGVLA_MS_BASE`);
  tclean scratch stays under `$SCRATCH/ngvla_curvegen` (`NGVLA_SCRATCH`, purged, disposable).
  `$HOME` has a 14 GB quota — never point CASA work dirs at it.
- *(Historical, macOS era:)* CASA was at `/Applications/CASA.app`
  (`/Applications/CASA.app/Contents/MacOS/python3` has the scientific stack) — still valid
  when working on a Mac.  **`.venv/`** is a bare pip-only venv; prefer CASA's Python.
- **Sensitivity calculator CLI:** `cd ngvla-sensitivity-calculator && ./ngVLA_sensitivity_calculator.py <subarray> <freq_GHz> <theta_arcsec> [--t_obs H] [--delta_v] [-v]`.
- **`pdftotxt`** is available if another PDF needs converting. **Do not read a PDF when the
  `.txt` already exists** — only open a PDF for figures or badly-formatted tables.

## Deliverables & dev guidance

- **The selection heuristic must be pluggable.** We will probably want to easily tweak the
  specific selection/ranking heuristic or drop in a different one — isolate it behind a small
  interface (e.g. a strategy function over the feasible-candidate list) rather than hard-coding.

- Document the algorithm/approach in a **LaTeX memo**; make sure it compiles and runs cleanly.
- **Make a plan and keep it in a Markdown file** so work can be resumed by a different coding
  agent; keep it updated and log gotchas. In the plan, note the recommended effort level and
  both an Anthropic and an OpenAI model per task — err toward high capability without wasting
  tokens.
- Efficiency vs. robustness tradeoff in curve generation: computing many PSFs over wide
  parameter ranges is slow, disk-hungry, and error-prone. Catch failures, clean up scratch
  files safely, and prune the parameter ranges up front to keep it tractable.

## Broader context (future direction, not current scope)

- The NGVLA EOP will later be updated to a) Rev F configs (not D/C), b) this SA-assignment
  heuristic, and c) beam sculpting — likely increasing observing times substantially. The
  `artifacts/` are notional sketches connected to this.
- A better imaging approach than `tclean` + taper + Briggs is desired eventually; that is just
  what exists now.
- For now assume all needed spatial frequencies are captured in one go (except SBA and total
  power); hierarchical component imaging + feather may relax this later.
- **Open question (no known solution yet):** how to adapt this approach to more varied and
  realistic use cases — mosaics, observation-specific / varying FOV (which changes how effective
  robust weighting is), and continuum vs. spectral line (fractional-bandwidth uv filling).
  v1 assumes the memo-121 fixed-FOV, single-pointing convention (fixed image size in
  pixels; the cell follows the taper beyond the native beam, so the angular field of view
  grows at coarse tapers; see `docs/worklog/mfs-campaigns.md` 7 Sep); document as a limitation.

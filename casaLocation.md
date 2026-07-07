# CASA on TACC (Stampede3)

**Use the project venv** (modular CASA 6.7.5, Python 3.12, numpy/scipy):

```
/work2/10240/bmason72/stampede3/casaenv/bin/casapy   # python3 wrapper — use this
```

`casapy` is a thin wrapper around the venv's `python3` that fixes the TACC
library environment (see below). Use it exactly like `python3`:

```bash
casaenv=/work2/10240/bmason72/stampede3/casaenv
$casaenv/bin/casapy -m unittest discover -s tests -t .   # from the repo root
cd curvegen && $casaenv/bin/casapy sweep.py core          # curve generation
```

## Why the wrapper (gotchas, 6 Jul 2026)

- TACC's default `LD_LIBRARY_PATH` (Intel oneAPI MPI/MKL) breaks casatools'
  bundled OpenMPI: `libopen-pal.so.80: undefined symbol: pmix_framework_names`.
  The wrapper strips it down to `/opt/apps/python/3.12.11/lib` (which the venv's
  python itself needs for `libpython3.12.so`).
- CASA measures data auto-downloaded to `~/.casa/data` (~860 MB) on first import.

## Previous install (do not use)

The install noted here previously —
`/scratch/10703/tashton/CASA_Packages/casa-6.6.1-17-pipeline-2024.1.0.8` —
is **broken**: `import casatools` fails (`ModuleNotFoundError: _image`) even via
its own `casa` launcher, plausibly scratch-purge damage. The "error but seems to
run" was IPython starting despite casatools being unimportable.

## Filesystem gotchas

- `$HOME` quota is ~14 GB: **never write MSes or tclean products under home.**
  `curvegen/ms` and `curvegen/work` are symlinks into
  `$SCRATCH/ngvla_curvegen/` (regenerable, so scratch-purge-safe).
- The venv lives in `$WORK` (persistent, not purged).
- Compute node sessions (VNC/idev): check remaining walltime with
  `squeue -u $USER` before launching multi-hour sweeps.

"""
Simulate a noise-only measurement set for one subarray.

Adapted from ngvla-taperability-pipeline/create_sim_ms.py (V. Rosero). Legacy
campaigns keep the same setup -- 60 s dumps, dec +24, one 1 MHz channel, 1 Jy
per-visibility noise. An MFS campaign instead takes its fixed spectral window,
channel count, and correlations from config and validates them against the
created or reused MS. The observing window comes from config.SIM: "track" is
the 4 h HA track (-2h..+2h); "snapshot" is a single 60 s integration centered
on transit (HA=0).

Run:  .../python3 curvegen/simulate.py core [spiral ...]
"""

import os
import shutil
import sys

import casatools
from casatasks.private.simutil import simutil

from config import (SUBARRAYS, SIM, SIM_MODE, CFG_DIR, MS_DIR, MFS, NCHAN,
                    FIRST_CHANNEL_CENTER_GHZ, CHANNEL_WIDTH_GHZ)
from campaign_manifest import ensure_manifest, casa_version_string


def make_ms(subarray, overwrite=False):
    """Create (or reuse) the simulated MS for `subarray`; returns its path."""
    cfg = os.path.join(CFG_DIR, subarray.replace("+", "_") + ".cfg")
    if not os.path.isfile(cfg):
        raise FileNotFoundError("%s missing -- run build_configs.py first" % cfg)
    os.makedirs(MS_DIR, exist_ok=True)
    ms_path = os.path.join(MS_DIR, subarray.replace("+", "_") + ".ms")
    if os.path.isdir(ms_path):
        if not overwrite:
            ensure_manifest(create=False, casa_version=casa_version_string())
            _validate_ms(ms_path)
            print("reusing existing %s" % ms_path)
            return ms_path
        shutil.rmtree(ms_path)

    ensure_manifest(create=True, casa_version=casa_version_string())

    u = simutil()
    # readantenna returns 7 or 8 items depending on CASA version; the last
    # three are always (telescope-ish, telescope, posobs)-adjacent -- unpack
    # defensively (this exact pitfall crashed CASA with a C++ abort).
    out = u.readantenna(cfg)
    if len(out) == 8:
        x, y, z, d, padnames, _, telescope, posobs = out
    else:
        x, y, z, d, padnames, telescope, posobs = out

    sm = casatools.simulator()
    me = casatools.measures()
    sm.open(ms_path)
    sm.setconfig(telescopename="ngvla", x=list(x), y=list(y), z=list(z),
                 dishdiameter=list(d), mount="alt-az",
                 antname=list(padnames), padname=list(padnames),
                 coordsystem="global", referencelocation=posobs)
    sm.setspwindow(spwname="band", freq=SIM["frequency"],
                   deltafreq=SIM["channel_width"],
                   freqresolution=SIM["channel_width"],
                   nchannels=SIM["nchannels"], stokes=SIM["correlations"])
    sm.setfeed("perfect R L")
    sm.setfield(sourcename="source",
                sourcedirection=["J2000", "00h0m0.0",
                                 SIM["source_dec"] + ".0.0.000"])
    sm.setlimits(shadowlimit=0.001, elevationlimit="8.0deg")
    sm.setauto(autocorrwt=0.0)
    sm.settimes(integrationtime=SIM["integration_time"], usehourangle=True,
                referencetime=me.epoch("utc", "today"))
    sm.observe("source", "band",
               starttime=SIM["timerange"][0], stoptime=SIM["timerange"][1])
    sm.setnoise(mode="simplenoise", simplenoise=SIM["noise"])
    sm.corrupt()
    sm.close()

    # snapshot must be exactly one integration at HA=0 -- fail loudly if the
    # CASA time-sampling produced 0 or 2 dumps for the 60 s window (bmason /
    # codex Q3: don't trust CASA edge behaviour without a post-sim check)
    n_dumps = _count_integrations(ms_path)
    if SIM_MODE == "snapshot" and n_dumps != 1:
        shutil.rmtree(ms_path, ignore_errors=True)
        raise RuntimeError(
            "snapshot sim for %s produced %d integrations (expected exactly 1)"
            " for window %s -- adjust config.SIM_MODES['snapshot'] timerange"
            % (subarray, n_dumps, SIM["timerange"]))
    _validate_ms(ms_path)
    print("created %s (%d antennas, %d integration%s)"
          % (ms_path, len(x), n_dumps, "" if n_dumps == 1 else "s"))
    return ms_path


def _count_integrations(ms_path):
    """Number of distinct integration timestamps in the MS (= dumps)."""
    tb = casatools.table()
    tb.open(ms_path)
    try:
        import numpy as np
        return int(np.unique(tb.getcol("TIME")).size)
    finally:
        tb.close()


def _channel_frequencies_hz(ms_path):
    """Flatten the sole spectral window's channel-centre frequencies."""
    tb = casatools.table()
    tb.open(os.path.join(ms_path, "SPECTRAL_WINDOW"))
    try:
        import numpy as np
        return np.asarray(tb.getcol("CHAN_FREQ"), dtype=float).reshape(-1)
    finally:
        tb.close()


def _correlation_codes(ms_path):
    """CASA Stokes integer codes in the sole polarization setup."""
    tb = casatools.table()
    tb.open(os.path.join(ms_path, "POLARIZATION"))
    try:
        import numpy as np
        return np.asarray(tb.getcol("CORR_TYPE"), dtype=int).reshape(-1)
    finally:
        tb.close()


def _validate_ms(ms_path):
    """Fail closed when a reusable MS does not match active channelization."""
    if MFS:
        n_dumps = _count_integrations(ms_path)
        expected_dumps = SIM["expected_integrations"]
        if n_dumps != expected_dumps:
            raise RuntimeError("%s has %d integrations; active MFS campaign "
                               "requires %d" % (ms_path, n_dumps,
                                                expected_dumps))
    freqs = _channel_frequencies_hz(ms_path)
    if freqs.size != NCHAN:
        raise RuntimeError("%s has %d channels; active campaign requires %d"
                           % (ms_path, freqs.size, NCHAN))
    stokes_codes = {"RR": 5, "RL": 6, "LR": 7, "LL": 8}
    expected_corr = [stokes_codes[name] for name in SIM["correlations"].split()]
    actual_corr = [int(value) for value in _correlation_codes(ms_path)]
    if actual_corr != expected_corr:
        raise RuntimeError("%s correlations %r do not match active campaign %r"
                           % (ms_path, actual_corr, expected_corr))
    expected_first = FIRST_CHANNEL_CENTER_GHZ * 1e9
    expected_last = (FIRST_CHANNEL_CENTER_GHZ
                     + (NCHAN - 1) * CHANNEL_WIDTH_GHZ) * 1e9
    tolerance_hz = max(1.0, abs(CHANNEL_WIDTH_GHZ * 1e9) * 1e-8)
    if (abs(float(freqs[0]) - expected_first) > tolerance_hz
            or abs(float(freqs[-1]) - expected_last) > tolerance_hz):
        raise RuntimeError(
            "%s channel centres %.9g..%.9g Hz do not match active campaign "
            "%.9g..%.9g Hz" % (ms_path, freqs[0], freqs[-1],
                                expected_first, expected_last))


if __name__ == "__main__":
    for name in (sys.argv[1:] or ["core"]):
        if name not in SUBARRAYS:
            sys.exit("unknown subarray %r (know: %s)" % (name, list(SUBARRAYS)))
        make_ms(name)

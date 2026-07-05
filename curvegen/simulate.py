"""
Simulate a noise-only measurement set for one Rev F subarray at 30 GHz.

Adapted from ngvla-taperability-pipeline/create_sim_ms.py (V. Rosero), with
the same observing setup -- 4 h track (HA -2h..+2h), 60 s dumps, dec +24,
one 1 MHz channel, 1 Jy per-visibility noise -- but callable as a plain
function under CASA's python3 (casatools, no casashell globals).

Run:  .../python3 curvegen/simulate.py core [spiral ...]
"""

import os
import shutil
import sys

import casatools
from casatasks.private.simutil import simutil

from config import SUBARRAYS, SIM, CFG_DIR, MS_DIR


def make_ms(subarray, overwrite=False):
    """Create (or reuse) the simulated MS for `subarray`; returns its path."""
    cfg = os.path.join(CFG_DIR, subarray.replace("+", "_") + ".cfg")
    if not os.path.isfile(cfg):
        raise FileNotFoundError("%s missing -- run build_configs.py first" % cfg)
    os.makedirs(MS_DIR, exist_ok=True)
    ms_path = os.path.join(MS_DIR, subarray.replace("+", "_") + ".ms")
    if os.path.isdir(ms_path):
        if not overwrite:
            print("reusing existing %s" % ms_path)
            return ms_path
        shutil.rmtree(ms_path)

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
                   deltafreq="1MHz", freqresolution="1MHz",
                   nchannels=1, stokes="RR RL LR LL")
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
    print("created %s (%d antennas)" % (ms_path, len(x)))
    return ms_path


if __name__ == "__main__":
    for name in (sys.argv[1:] or ["core"]):
        if name not in SUBARRAYS:
            sys.exit("unknown subarray %r (know: %s)" % (name, list(SUBARRAYS)))
        make_ms(name)

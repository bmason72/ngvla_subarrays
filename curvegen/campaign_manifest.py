"""Immutable provenance manifest for broadband MFS curve campaigns.

Mono campaigns predate manifests and remain untouched. For MFS, every reuse
of a measurement set or result table must match this file exactly; otherwise a
resumable run could silently mix channelization or sampler conventions.
"""

import json
import os

from config import (BAND, CAMPAIGN_VARIANT, MFS, REV, SIM_MODE, NCHAN, REF_FREQ_GHZ,
                    FREQ_LO_GHZ, FREQ_HI_GHZ, CHANNEL_WIDTH_GHZ,
                    FIRST_CHANNEL_CENTER_GHZ, CURVE_TYPES, NOISE_POLICY,
                    RESULTS_DIR, OVERSAMPLE, MFS_SUBARRAYS)

MANIFEST_NAME = "campaign_manifest.json"
MANIFEST_SCHEMA = 1


def casa_version_string():
    """Best-effort stable CASA version string for the runtime manifest."""
    try:
        import casatools
        direct = getattr(casatools, "version_string", None)
        if direct is not None:
            return str(direct())
        ctsys = getattr(casatools, "ctsys", None)
        if ctsys is not None and hasattr(ctsys, "version_string"):
            return str(ctsys.version_string())
    except Exception:
        pass
    return "unavailable"


def expected_manifest(casa_version=None):
    """Return the complete MFS identity dictated by the current environment."""
    if not MFS:
        return None
    # Lazy to keep ordinary config imports independent of the planner stack.
    from adaptive import manifest as sampler_manifest
    data = {
        "schema": MANIFEST_SCHEMA,
        "campaign": {
            "rev": REV, "sim_mode": SIM_MODE, "band": BAND,
            "variant": CAMPAIGN_VARIANT,
            "subarrays": list(MFS_SUBARRAYS), "curve_types": CURVE_TYPES,
            "run_mode": "fresh",
        },
        "spectral_window": {
            "ref_freq_ghz": REF_FREQ_GHZ,
            "freq_lo_ghz": FREQ_LO_GHZ,
            "freq_hi_ghz": FREQ_HI_GHZ,
            "nchan": NCHAN,
            "channel_width_ghz": CHANNEL_WIDTH_GHZ,
            "first_channel_center_ghz": FIRST_CHANNEL_CENTER_GHZ,
            "correlations": ["RR", "LL"],
            "noise_policy": NOISE_POLICY,
        },
        "imaging": {
            "specmode": "mfs", "reffreq_ghz": REF_FREQ_GHZ,
            "nterms": 1, "deconvolver": "hogbom", "stokes": "I",
            "parallel": False,
            "cell_policy": "imager-advise/%d scaled ref_freq/freq_hi; MFS seeds "
                           "require minor axis >= %d pixels"
                           % (OVERSAMPLE, OVERSAMPLE),
        },
        "sampler": sampler_manifest(),
        "casa_version": casa_version or casa_version_string(),
    }
    # JSON is the source-of-truth representation.  Normalize tuples from the
    # sampler manifest now so create-then-reload compares equal.
    return json.loads(json.dumps(data, sort_keys=True))


def manifest_path():
    return os.path.join(RESULTS_DIR, MANIFEST_NAME)


def ensure_manifest(create=False, casa_version=None):
    """Validate the MFS manifest, optionally creating it atomically.

    A missing manifest is never created while merely reusing old artifacts;
    callers pass ``create=True`` only before producing a fresh MFS MS.
    """
    if not MFS:
        return None
    path = manifest_path()
    expected = expected_manifest(casa_version)
    if os.path.isfile(path):
        with open(path) as f:
            actual = json.load(f)
        different = [key for key in sorted(set(expected) | set(actual))
                     if expected.get(key) != actual.get(key)]
        if different:
            raise RuntimeError(
                "%s does not match the active MFS campaign (changed: %s); "
                "use a fresh combo directory or restore the manifest inputs"
                % (path, ", ".join(different)))
        return actual
    if not create:
        raise RuntimeError(
            "MFS artifacts cannot be reused without %s; regenerate them in "
            "a fresh combo directory" % path)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    tmp = path + ".tmp.%d" % os.getpid()
    try:
        with open(tmp, "w") as f:
            json.dump(expected, f, indent=2, sort_keys=True)
            f.write("\n")
        try:
            # Atomic create-without-overwrite: concurrent workers may race to
            # initialize the combo, but none may replace another's identity.
            os.link(tmp, path)
        except FileExistsError:
            return ensure_manifest(create=False, casa_version=casa_version)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return expected

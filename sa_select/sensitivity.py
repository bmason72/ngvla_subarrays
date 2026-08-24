"""Natural-weight sensitivity used by the subarray selector.

This is the small, explicitly used kernel of V. Rosero's ngVLA Memo-96
sensitivity calculator.  Runtime data are inert JSON package resources, so the
module neither imports a sibling checkout nor changes the process working
directory.  Only native, natural-weight rms is calculated here; taper/robust
loss is supplied by this project's measured eta curves.

Units are GHz, hours, arcsec, Jy/beam, K, and (for ``delta_v``) m/s.
"""

from importlib import resources
import json

import numpy as np
from scipy.interpolate import CubicSpline, interp1d


def _load_tables():
    resource = resources.files("sa_select").joinpath("data", "sensitivity_data.json")
    with resource.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if (payload.get("schema") != "ngvla.memo96.sensitivity-tables"
            or payload.get("schema_version") != 1):
        raise RuntimeError("unsupported packaged sensitivity-data schema")
    return payload


_DATA = _load_tables()
_RECEIVER_TABLE = _DATA["receiver_data"]
_SUBARRAY_TABLE = _DATA["subarray_data"]
_BAND_ORDER = _DATA["table_key_order"]["receiver_data"]

#: N_ant for every subarray key the calculator itself knows about.
_N_ANT_TABLE = {name: int(info["N_ant"]) for name, info in _SUBARRAY_TABLE.items()}

#: Subarrays absent from the calculator's tables are synthesized by donor rescaling
#: from `main`: for same-band 18-m arrays the per-antenna parameters are band-keyed,
#: so thermal sigma scales exactly as 1/sqrt(N(N-1)) (verified in the self-test).
#: The value is the subarray's nominal target N_ant.  The donor also carries
#: MAIN's native-beam confusion term; it is negligible at these resolutions.
_DONOR = "main"
_DONOR_N_ANT = {
    "core+mid": 160,                    # measured but dropped from the offered set
    "core-inner": 57,
    "core-outer": 57,
    "spiral+core-outer": 111,
    "mid+spiral+core-outer": 157,
    "spiral+mid+long": 130,
    "long+mid+spiral+core-outer": 187,
}
CORE_MID_N_ANT = _DONOR_N_ANT["core+mid"]   # kept for callers/tests

#: Names natural_rms()/integration_time() accept, in addition to the calculator's own keys.
KNOWN_CALC_NAMES = sorted(_N_ANT_TABLE) + sorted(_DONOR_N_ANT)


def data_info():
    """Machine-readable provenance and coverage of the packaged backing data."""
    return {
        "schema": _DATA["schema"],
        "schema_version": _DATA["schema_version"],
        "provenance": _DATA["provenance"],
        "redistribution_note": _DATA["redistribution_note"],
        "source_sha256": dict(_DATA["source_sha256"]),
        "receiver_bands": list(_BAND_ORDER),
        "backing_subarrays": list(_DATA["table_key_order"]["subarray_data"]),
        "supported_calc_names": list(KNOWN_CALC_NAMES),
    }


def _resolve_calc_name(calc_name):
    """Return (name_to_query_the_calculator_with, n_ant_to_report_as).

    n_ant_to_report_as is None when the calculator's own subarray entry is used directly
    (no rescaling needed); it is an int when we're donor-rescaling.  An empty name is
    kept as a core+mid alias for backward compatibility.
    """
    if calc_name == "":
        calc_name = "core+mid"
    if calc_name in _DONOR_N_ANT:
        return _DONOR, _DONOR_N_ANT[calc_name]
    if calc_name not in _N_ANT_TABLE:
        raise ValueError(
            "unknown subarray calc_name %r; known names: %s" % (calc_name, KNOWN_CALC_NAMES)
        )
    return calc_name, None


def _n_ant_for(calc_name):
    """N_ant for any name natural_rms() accepts (calculator keys plus 'core+mid')."""
    query_name, n_target = _resolve_calc_name(calc_name)
    return n_target if n_target is not None else _N_ANT_TABLE[query_name]


def _band_for(freq_ghz):
    valid = []
    for key in _BAND_ORDER:
        frequencies = np.asarray(_RECEIVER_TABLE[key]["freq"], dtype=float)
        if freq_ghz < frequencies.max() and freq_ghz >= frequencies.min():
            valid.append(key)
    if not valid:
        raise ValueError("frequency %.4g GHz is outside all receiver bands" % freq_ghz)
    # Preserve the upstream overlap policy and original table order.
    return valid[-1]


def _confusion_ujy(freq_ghz, theta_arcsec):
    counts = _DATA["confusion_counts"]
    log_s_jy = np.asarray(counts["log_s_jy"], dtype=float)
    n_total_sr = np.asarray(counts["n_total_sr"], dtype=float)
    omega = 1.0 / (25.0 * n_total_sr)
    theta_fwhm = (
        np.sqrt(4.0 * np.log(2.0) * omega / np.pi)
        * np.rad2deg(1.0) * 3600.0
    )
    confusion = 1e6 * (10.0 ** log_s_jy) / 5.0
    scaled = confusion * (freq_ghz / 1.4) ** -0.7
    fn = interp1d(theta_fwhm, scaled, bounds_error=False, fill_value=0)
    return float(fn(theta_arcsec))


def _native_rms_ujy(subarray, freq_ghz, t_obs_hr, delta_v):
    """Memo-96 native-beam result, kept separate for parity testing."""
    if subarray not in _SUBARRAY_TABLE:
        raise ValueError("unknown backing subarray %r" % subarray)
    if not np.isfinite(freq_ghz) or freq_ghz <= 0:
        raise ValueError("frequency must be positive")
    if not np.isfinite(t_obs_hr) or t_obs_hr <= 0:
        raise ValueError("t_obs_hr must be positive")
    if delta_v is not None and (not np.isfinite(delta_v) or delta_v <= 0):
        raise ValueError("delta_v must be positive when supplied")

    band_key = _band_for(freq_ghz)
    receiver = _RECEIVER_TABLE[band_key]
    frequencies = np.asarray(receiver["freq"], dtype=float)
    tprime_spline = CubicSpline(frequencies, receiver["tprimeSys"])
    efficiency_spline = CubicSpline(frequencies, receiver["antEff"])
    f_low, f_high = frequencies.min(), frequencies.max()
    nu = float(freq_ghz)

    if delta_v is None:
        if band_key != "BAND_6":
            sample_freqs = np.linspace(f_low, f_high, 100)
            nu = float(np.mean([f_low, f_high]))
        else:
            if nu - 10.0 < f_low:
                nu = f_low + 10.0
            elif nu + 10.0 > f_high:
                nu = f_high - 10.0
            sample_freqs = np.linspace(nu - 10.0, nu + 10.0, 100)
        tprime = float(np.mean(tprime_spline(sample_freqs)))
        eta_a = float(np.mean(efficiency_spline(sample_freqs)))
        bandwidth_hz = float(receiver["max_bw"]) * 1e9
    else:
        tprime = float(tprime_spline(nu))
        eta_a = float(efficiency_spline(nu))
        bandwidth_hz = nu * float(delta_v) / 2.9979246e8 * 1e9

    parameters = _SUBARRAY_TABLE[subarray]
    n_ant = int(parameters["N_ant"])
    diameter_m = 6.0 if subarray == "sba" else 18.0
    area_m2 = np.pi * (diameter_m / 2.0) ** 2
    sefd_jy = (2.0 * 1.38e-23 * tprime / (0.9625 * eta_a * area_m2)) / 1e-26
    thermal_ujy = sefd_jy / (
        0.98 * np.sqrt(2.0 * bandwidth_hz * t_obs_hr * 3600.0
                       * n_ant * (n_ant - 1))
    ) / 1e-6
    theta_arcsec = float(parameters["theta_nat_30_GHz"]) * 30.0 / nu / 1e3
    confusion_ujy = _confusion_ujy(nu, theta_arcsec)
    return float(np.hypot(thermal_ujy, confusion_ujy))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def natural_rms(calc_name, freq_ghz, t_obs_hr=1.0, delta_v=None):
    """Point-source rms (Jy/beam) at NATURAL weighting (eta == 1) for one subarray.

    Parameters
    ----------
    calc_name : str
        A calculator subarray key (sba, core, spiral, mid, long, main, main+long,
        spiral+mid, spiral+core, mid+long), or 'core+mid' / '' for the donor-rescaled
        core+mid combination (see module docstring).
    freq_ghz : float
        Observing frequency, GHz. Note the calculator may re-center this to the middle
        of the receiver band for the continuum bandwidth/Tsys average (see self-test).
    t_obs_hr : float
        On-source integration time, hours.
    delta_v : float or None
        Channel width, m/s, for a spectral-line rms. None (default) means continuum,
        using the full receiver bandwidth (``max_bw`` in the packaged receiver table, e.g. 13.5 GHz
        for Band 4, 20 GHz for Band 5) rather than a narrow channel.

    Returns
    -------
    float
        rms in Jy/beam, at the subarray's native (untapered, natural-weighted) resolution.
    """
    query_name, n_target = _resolve_calc_name(calc_name)
    sigma_rms_ujy = _native_rms_ujy(
        query_name, freq_ghz, t_obs_hr=t_obs_hr, delta_v=delta_v)

    if n_target is not None:
        n_donor = _N_ANT_TABLE[query_name]
        sigma_rms_ujy = sigma_rms_ujy * np.sqrt(
            n_donor * (n_donor - 1) / (n_target * (n_target - 1))
        )

    return float(sigma_rms_ujy) * 1e-6  # uJy -> Jy


def integration_time(calc_name, freq_ghz, eta, goal_jy_per_beam, delta_v=None, n_ant_actual=None):
    """Hours of on-source time so that ``eta * natural_rms(t) == goal_jy_per_beam``.

    Radiometer scaling: rms ~ 1/sqrt(t), so t = t_ref * (eta * sigma_ref / goal)**2 for
    any reference time t_ref (the reference time cancels out of the ratio).

    Parameters
    ----------
    calc_name : str
        See natural_rms.
    freq_ghz : float
        Observing frequency, GHz.
    eta : float
        Sensitivity-loss factor (>= 1) for the chosen robust/taper, from curves.py.
    goal_jy_per_beam : float
        Target point-source rms, Jy/beam.
    delta_v : float or None
        See natural_rms.
    n_ant_actual : int or None
        Override the subarray's nominal antenna count (e.g. fewer antennas available on
        the day). Rescales sigma by sqrt(N_nominal*(N_nominal-1) / N_actual*(N_actual-1)).

    Returns
    -------
    float
        Required on-source integration time, hours.
    """
    if goal_jy_per_beam <= 0:
        raise ValueError("goal_jy_per_beam must be positive")
    if eta <= 0:
        raise ValueError("eta must be positive")

    t_ref_hr = 1.0
    sigma_ref = natural_rms(calc_name, freq_ghz, t_obs_hr=t_ref_hr, delta_v=delta_v)

    if n_ant_actual is not None:
        if not isinstance(n_ant_actual, (int, np.integer)) or n_ant_actual < 2:
            raise ValueError("n_ant_actual must be an integer >= 2")
        n_nominal = _n_ant_for(calc_name)
        sigma_ref = sigma_ref * np.sqrt(
            n_nominal * (n_nominal - 1) / (n_ant_actual * (n_ant_actual - 1))
        )

    return t_ref_hr * (eta * sigma_ref / goal_jy_per_beam) ** 2


# ---------------------------------------------------------------------------
# Brightness temperature <-> flux density (Rayleigh-Jeans, Gaussian beam)
# ---------------------------------------------------------------------------

_C_M_S = 2.99792458e8       # speed of light, m/s
_K_B = 1.380649e-23         # Boltzmann constant, J/K
_ARCSEC_TO_RAD = np.pi / (180.0 * 3600.0)
_JY = 1e-26                 # 1 Jy in W / m^2 / Hz


def _beam_solid_angle_sr(theta_arcsec):
    """Solid angle (sr) of a circular Gaussian beam of FWHM theta_arcsec.

    Omega = pi * theta^2 / (4 ln 2), with theta in radians.
    """
    theta_rad = theta_arcsec * _ARCSEC_TO_RAD
    return np.pi * theta_rad ** 2 / (4.0 * np.log(2.0))


def tb_to_jy(tb_k, theta_arcsec, freq_ghz):
    """Rayleigh-Jeans brightness temperature (K) -> flux density (Jy/beam).

    S = 2 k_B T_B Omega / lambda**2
    """
    lam_m = _C_M_S / (freq_ghz * 1e9)
    omega_sr = _beam_solid_angle_sr(theta_arcsec)
    s_si = 2.0 * _K_B * tb_k * omega_sr / lam_m ** 2  # W / m^2 / Hz
    return s_si / _JY


def jy_to_tb(s_jy, theta_arcsec, freq_ghz):
    """Flux density (Jy/beam) -> Rayleigh-Jeans brightness temperature (K)."""
    lam_m = _C_M_S / (freq_ghz * 1e9)
    omega_sr = _beam_solid_angle_sr(theta_arcsec)
    s_si = s_jy * _JY
    return s_si * lam_m ** 2 / (2.0 * _K_B * omega_sr)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("packaged data schema:", _DATA["schema"], _DATA["schema_version"])
    print("known calc_names:", KNOWN_CALC_NAMES)
    assert _N_ANT_TABLE["core"] + _N_ANT_TABLE["mid"] == CORE_MID_N_ANT, (
        "core+mid antenna count assumption is stale: core=%d mid=%d != %d"
        % (_N_ANT_TABLE["core"], _N_ANT_TABLE["mid"], CORE_MID_N_ANT)
    )

    # (a) natural rms for main, 30 GHz, 1 hr, continuum
    rms_main = natural_rms("main", 30.0, t_obs_hr=1.0)
    print("\n(a) natural_rms('main', 30 GHz, 1 hr, continuum) = %.6g Jy/beam" % rms_main)

    # (b) same, via the core+mid donor path
    rms_coremid = natural_rms("core+mid", 30.0, t_obs_hr=1.0)
    print("(b) natural_rms('core+mid', 30 GHz, 1 hr, continuum) = %.6g Jy/beam" % rms_coremid)
    n_main, n_cm = _N_ANT_TABLE["main"], CORE_MID_N_ANT
    expected_ratio = np.sqrt((n_main * (n_main - 1)) / (n_cm * (n_cm - 1)))
    print(
        "    ratio rms_coremid/rms_main = %.4f (expected sqrt(N_main(N_main-1)/N_cm(N_cm-1)) = %.4f)"
        % (rms_coremid / rms_main, expected_ratio)
    )
    assert abs(rms_coremid / rms_main - expected_ratio) < 1e-9

    # also exercise the '' alias and a line observation, and check delta_v plumbing
    rms_coremid_alias = natural_rms("", 30.0, t_obs_hr=1.0)
    assert rms_coremid_alias == rms_coremid
    rms_line = natural_rms("main", 30.0, t_obs_hr=1.0, delta_v=2e3)
    print("    natural_rms('main', 30 GHz, 1 hr, line dv=2 km/s) = %.6g Jy/beam" % rms_line)
    assert rms_line > rms_main, "narrower line channel should be noisier than full continuum band"

    # (c) integration_time round-trip: goal = eta*natural_rms(t=X) should return ~X hours
    eta = 1.35
    x_hr = 3.7
    goal = eta * natural_rms("spiral", 15.0, t_obs_hr=x_hr)
    t_back = integration_time("spiral", 15.0, eta, goal)
    print(
        "\n(c) integration_time round-trip: injected %.3f hr, recovered %.6f hr" % (x_hr, t_back)
    )
    assert abs(t_back - x_hr) / x_hr < 1e-9

    # round-trip also through the core+mid donor path
    goal2 = eta * natural_rms("core+mid", 15.0, t_obs_hr=x_hr)
    t_back2 = integration_time("core+mid", 15.0, eta, goal2)
    assert abs(t_back2 - x_hr) / x_hr < 1e-9
    print("    same check via core+mid donor path: recovered %.6f hr" % t_back2)

    # n_ant_actual override sanity check: fewer antennas -> longer time
    t_full = integration_time("main", 15.0, eta, goal)
    t_fewer = integration_time("main", 15.0, eta, goal, n_ant_actual=100)
    print("    integration_time with 100/%d antennas: %.4f hr (vs %.4f hr at full count)"
          % (_N_ANT_TABLE["main"], t_fewer, t_full))
    assert t_fewer > t_full

    # (d) tb_to_jy / jy_to_tb round trip
    tb0, theta0, freq0 = 12.3, 0.05, 27.0
    s0 = tb_to_jy(tb0, theta0, freq0)
    tb_back = jy_to_tb(s0, theta0, freq0)
    print("\n(d) tb_to_jy(%.3g K, %.3g arcsec, %.3g GHz) = %.6g Jy; jy_to_tb round-trip = %.6g K"
          % (tb0, theta0, freq0, s0, tb_back))
    assert abs(tb_back - tb0) / tb0 < 1e-9

    print("\nAll self-tests passed.")

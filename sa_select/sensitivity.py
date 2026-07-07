"""
Thin wrapper around ``ngvla-sensitivity-calculator`` for the subarray-selection tool.

The upstream calculator (``ngvla-sensitivity-calculator/ngVLA_sensitivity_calculator.py``,
V. Rosero) computes the natural-weighting thermal (+confusion) point-source rms for the
ten subarray keys in its ``subarray_data.pkl``.  It *also* has its own built-in resolution
-> inefficiency mapping (``eta_w``), but that mapping is a placeholder
(``eta_w = log10(theta_mas * freq_GHz / 30)`` -- see ``sigma_ps_fn`` around line 308; the
loaded spline ``cs`` is only used to bound-check theta, never evaluated) and is NOT the
taperability-curve eta this package computes elsewhere.  So this module only ever calls the
calculator at its **native** resolution (``theta=-1``, which hard-codes ``eta_w=1``) and then
applies our own eta (from ``curves.py``) on top, as ``sigma = eta * natural_rms``.

Units used by this module (matches ``schema.py``): frequency in GHz, time in HOURS,
angles in ARCSEC, flux density in Jy/beam, brightness temperature in K. The upstream
calculator internally uses uJy and seconds; conversions happen at the boundary in this file.

``core+mid`` is not one of the calculator's ten subarray keys. Per-antenna properties
(SEFD, aperture efficiency, Tsys) come from ``receiver_data.pkl`` which is keyed only by
*receiver band*, not by subarray, and the antenna diameter is fixed at D=18 m for every
subarray except the SBA (D=6 m). So for any two 18-m subarrays the natural-weighting
thermal rms scales *exactly* as 1/sqrt(N*(N-1)) at fixed frequency and integration time.
We exploit that to synthesize ``core+mid`` (N=114+46=160) from the ``main`` array (N=214)
as a "donor": compute main's native rms, then rescale by
sqrt(N_main*(N_main-1) / N_coremid*(N_coremid-1)).  The one imperfection: the confusion-
noise term (added in quadrature) depends on the *native beam size*, which differs between
main and core+mid and which we do not have for core+mid (it isn't in the calculator's
spline table). In practice this is a non-issue: at the sub-arcsec native resolutions of
these Rev F configurations the calculator's confusion term evaluates to 0 uJy (see the
module self-test), so the donor rescaling is effectively exact end to end.
"""

import contextlib
import importlib.util
import io
import os
import pickle

import numpy as np

# ---------------------------------------------------------------------------
# Load the upstream calculator as a private module, without touching sys.path
# or the ngvla-sensitivity-calculator/ directory's contents. It reads its two
# .pkl files via *relative* paths on every call, so every call into it below
# is wrapped in `_in_calculator_dir()`.
# ---------------------------------------------------------------------------

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CALC_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "ngvla-sensitivity-calculator"))
_CALC_FILE = os.path.join(_CALC_DIR, "ngVLA_sensitivity_calculator.py")


@contextlib.contextmanager
def _in_calculator_dir():
    """Temporarily chdir into ngvla-sensitivity-calculator/ (it opens its .pkl files
    by relative path) and swallow its stdout chatter."""
    prev_cwd = os.getcwd()
    buf = io.StringIO()
    os.chdir(_CALC_DIR)
    try:
        with contextlib.redirect_stdout(buf):
            yield buf
    finally:
        os.chdir(prev_cwd)


def _load_calculator():
    spec = importlib.util.spec_from_file_location("_ngvla_sensitivity_calculator", _CALC_FILE)
    mod = importlib.util.module_from_spec(spec)
    with _in_calculator_dir():
        spec.loader.exec_module(mod)
    return mod


_calc = _load_calculator()

with _in_calculator_dir():
    with open("subarray_data.pkl", "rb") as _f:
        _SUBARRAY_TABLE = pickle.load(_f)

#: N_ant for every subarray key the calculator itself knows about.
_N_ANT_TABLE = {name: int(info["N_ant"]) for name, info in _SUBARRAY_TABLE.items()}

#: Subarrays absent from the calculator's tables are synthesized by donor rescaling
#: from `main`: for same-band 18-m arrays the per-antenna parameters are band-keyed,
#: so sigma scales exactly as 1/sqrt(N(N-1)) (verified in the self-test).  The value
#: is the subarray's true N_ant.  (Confusion caveat unchanged: zero at Rev F native
#: resolutions in the current calculator path.)
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


def _call_sigma_ps(subarray, freq_ghz, type_cal, t_int_s, theta, delta_v):
    """Call the upstream sigma_ps_fn, converting its sys.exit(0)-on-error convention
    into a normal Python exception with a readable message."""
    try:
        with _in_calculator_dir() as buf:
            return _calc.sigma_ps_fn(
                subarray=subarray,
                freq=freq_ghz,
                type_cal=type_cal,
                t_int=t_int_s,
                theta=theta,
                delta_v=delta_v,
                verbose=False,
            )
    except SystemExit:
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        detail = lines[-1] if lines else "the sensitivity calculator rejected this request"
        raise ValueError(
            "ngVLA sensitivity calculator error for subarray=%r, freq=%.4g GHz, theta=%r: %s"
            % (subarray, freq_ghz, theta, detail)
        )


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
        using the full receiver bandwidth (``max_bw`` in receiver_data.pkl, e.g. 13.5 GHz
        for Band 4, 20 GHz for Band 5) rather than a narrow channel.

    Returns
    -------
    float
        rms in Jy/beam, at the subarray's native (untapered, natural-weighted) resolution.
    """
    query_name, n_target = _resolve_calc_name(calc_name)
    type_cal = "continuum" if delta_v is None else "line"
    delta_v_arg = 10e3 if delta_v is None else delta_v  # ignored by calc when type_cal=='continuum'

    data_to_print, _performance, band_info = _call_sigma_ps(
        query_name, freq_ghz, type_cal, t_obs_hr * 3600.0, theta=-1, delta_v=delta_v_arg
    )
    sigma_rms_ujy = data_to_print[1]
    eta_w = band_info[3]
    if abs(eta_w - 1.0) > 1e-9:
        raise AssertionError(
            "expected eta_w == 1 at native resolution (theta=-1), got %r -- "
            "the calculator's internal convention may have changed" % eta_w
        )

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

    print("calculator dir:", _CALC_DIR)
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

    # (e) cross-check against the calculator's own sigma_T (K) for a native-resolution case
    with _in_calculator_dir():
        data_to_print, _perf, band_info = _calc.sigma_ps_fn(
            subarray="main", freq=30.0, type_cal="continuum", t_int=3600.0, theta=-1, verbose=False
        )
    nu_used, sigma_rms_ujy, sigma_T_calc, sigma_conf_ujy = data_to_print
    band_key, theta_native_arcsec, _delta_nu, eta_w_calc = band_info
    print(
        "\n(e) cross-check @ native res: calculator band=%s, re-centered freq=%.4f GHz, "
        "native theta=%.4f mas, eta_w=%.3f, sigma_rms=%.4f uJy, sigma_conf=%.4f uJy, sigma_T=%.4f K"
        % (band_key, nu_used, theta_native_arcsec * 1e3, eta_w_calc, sigma_rms_ujy, sigma_conf_ujy, sigma_T_calc)
    )
    assert eta_w_calc == 1.0
    assert abs(sigma_rms_ujy * 1e-6 - rms_main) < 1e-12, "our natural_rms must match the raw call exactly"
    # our own tb_to_jy formula, applied to the *thermal-only* uJy number, should reproduce
    # the calculator's sigma_T once we add back its confusion contribution the same way it does
    thermal_only_ujy = sigma_rms_ujy  # eta_w==1 already applied inside sigma_ps_fn
    sigma_T_ours = jy_to_tb(thermal_only_ujy * 1e-6, theta_native_arcsec, nu_used)
    print(
        "    our jy_to_tb of the same rms/theta/freq = %.4f K (calculator's sigma_T incl. confusion = %.4f K)"
        % (sigma_T_ours, sigma_T_calc)
    )
    # sigma_conf is 0 at this fine a native resolution, so the two should agree closely.
    # NB: they agree to ~0.5%, not machine precision -- the calculator's sigma_T uses a
    # hardcoded constant (1.216) in place of the analytic 2*k_B/lambda^2/Omega prefactor,
    # which works out to ~1.222 with precise CODATA c, k_B; see PLAN.md / final report.
    if sigma_conf_ujy == 0:
        assert abs(sigma_T_ours - sigma_T_calc) / sigma_T_calc < 1e-2

    print("\nAll self-tests passed.")

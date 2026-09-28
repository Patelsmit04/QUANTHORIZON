"""
BLACK-SCHOLES GREEKS ENGINE — PY_VOLLIB CROSS-CHECK & VALIDATION TEST SUITE
=============================================================================
Formally cross-checks options_greeks_analyzer.black_scholes_greeks against
industry-standard py_vollib across:
  1. ATM calls and puts
  2. Deep ITM calls and puts
  3. Deep OTM calls and puts
  4. Near-expiry options (1 day, 0.1 day / intraday expiry)
  5. High volatility (45%, 150%)
  6. Low volatility (3%, 8.5%)
  7. Fail-loud validation on non-positive IV or invalid inputs
"""

import pytest
from py_vollib.black_scholes.greeks.analytical import delta, gamma, theta, vega
from options_greeks_analyzer import black_scholes_greeks


@pytest.mark.parametrize("label,S,K,iv,days,opt_type,r", [
    ("ATM Call 7d", 24000, 24000, 15.0, 7, "CE", 0.07),
    ("ATM Put 7d", 24000, 24000, 15.0, 7, "PE", 0.07),
    ("Deep ITM Call 7d", 25000, 23000, 16.0, 7, "CE", 0.07),
    ("Deep ITM Put 7d", 23000, 25000, 16.0, 7, "PE", 0.07),
    ("Deep OTM Call 7d", 23000, 25000, 14.0, 7, "CE", 0.07),
    ("Deep OTM Put 7d", 25000, 23000, 14.0, 7, "PE", 0.07),
    ("Near Expiry ATM Call 1d", 24000, 24000, 13.5, 1, "CE", 0.07),
    ("Near Expiry ATM Put 1d", 24000, 24000, 13.5, 1, "PE", 0.07),
    ("Near Expiry OTM Call 1d", 24000, 24200, 15.0, 1, "CE", 0.07),
    ("Near Expiry ITM Put 1d", 24000, 24200, 15.0, 1, "PE", 0.07),
    ("High IV ATM Call 3d", 24000, 24000, 45.0, 3, "CE", 0.07),
    ("High IV ATM Put 3d", 24000, 24000, 45.0, 3, "PE", 0.07),
    ("Low IV ATM Call 14d", 24000, 24000, 8.5, 14, "CE", 0.07),
    ("Low IV ATM Put 14d", 24000, 24000, 8.5, 14, "PE", 0.07),
    ("Bank Nifty ATM Call 4d", 56000, 56000, 18.0, 4, "CE", 0.07),
    ("Bank Nifty ATM Put 4d", 56000, 56000, 18.0, 4, "PE", 0.07),
    ("Super Near Expiry 0.1d Call", 24000, 24000, 15.0, 0.1, "CE", 0.07),
    ("Super Near Expiry 0.1d Put", 24000, 24000, 15.0, 0.1, "PE", 0.07),
    ("Extreme High IV 150%", 24000, 24000, 150.0, 7, "CE", 0.07),
    ("Extreme Low IV 3%", 24000, 24000, 3.0, 7, "CE", 0.07),
])
def test_greeks_match_py_vollib(label, S, K, iv, days, opt_type, r):
    """
    Verify our custom Black-Scholes implementation matches py_vollib's
    analytical Greeks to within strict numerical tolerances.
    """
    custom = black_scholes_greeks(S, K, iv, days, opt_type, r)
    assert custom is not None, f"Greeks computation returned None for valid case: {label}"

    flag = "c" if opt_type == "CE" else "p"
    t = days / 365.0
    sigma = iv / 100.0

    v_delta = round(delta(flag, S, K, t, r, sigma), 4)
    v_gamma = round(gamma(flag, S, K, t, r, sigma), 6)
    v_theta = round(theta(flag, S, K, t, r, sigma), 2)  # py_vollib theta is already per-day
    v_vega = round(vega(flag, S, K, t, r, sigma), 2)    # py_vollib vega is already per-1% IV

    assert abs(custom["delta"] - v_delta) <= 0.0001, (
        f"[{label}] Delta mismatch: custom={custom['delta']}, py_vollib={v_delta}"
    )
    assert abs(custom["gamma"] - v_gamma) <= 0.000001, (
        f"[{label}] Gamma mismatch: custom={custom['gamma']}, py_vollib={v_gamma}"
    )
    assert abs(custom["theta_per_day"] - v_theta) <= 0.02, (
        f"[{label}] Theta mismatch: custom={custom['theta_per_day']}, py_vollib={v_theta}"
    )
    assert abs(custom["vega"] - v_vega) <= 0.02, (
        f"[{label}] Vega mismatch: custom={custom['vega']}, py_vollib={v_vega}"
    )


def test_black_scholes_fail_loud_on_invalid_inputs():
    """
    Verify FAIL LOUD principle: unverified or missing IV, non-positive days,
    or negative spot/strike must return None and NEVER synthesize fake Greeks.
    """
    assert black_scholes_greeks(24000, 24000, 0.0, 7, "CE") is None  # zero IV
    assert black_scholes_greeks(24000, 24000, -10.0, 7, "CE") is None  # negative IV
    assert black_scholes_greeks(24000, 24000, None, 7, "CE") is None  # None IV
    assert black_scholes_greeks(24000, 24000, 15.0, 0, "CE") is None  # 0 days
    assert black_scholes_greeks(24000, 24000, 15.0, -2, "CE") is None  # negative days
    assert black_scholes_greeks(-100, 24000, 15.0, 7, "CE") is None  # invalid spot
    assert black_scholes_greeks(24000, -100, 15.0, 7, "CE") is None  # invalid strike

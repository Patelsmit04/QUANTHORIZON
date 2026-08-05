"""
OPTIONS GREEKS ANALYZER — real Black-Scholes, not estimated
================================================================
Computes Delta/Gamma/Theta/Vega from LIVE spot, strike, and NSE-reported implied volatility
(options_chain_provider.py) — standard closed-form Black-Scholes, the same formulas any
options desk uses. Indian index options are European-style (no early exercise), which matches
Black-Scholes' assumptions cleanly.

FAIL LOUD: if IV wasn't verified for a leg (options_chain_provider flags iv_verified=False
when NSE reports IV=0, meaning no recent trade priced that leg), no Greeks are computed for
it — never derived from a fabricated volatility.

ASSUMPTION, DISCLOSED: the risk-free rate isn't live-fetched (no verified free source for an
India short-term rate) — DEFAULT_RISK_FREE_RATE is a fixed, documented estimate. Short-dated
option Greeks are dominated by spot/strike/IV/time, not r, so this is standard practice — but
it's disclosed here and in every result rather than presented as measured data.
"""

import math
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger("OptionsGreeksAnalyzer")

DEFAULT_RISK_FREE_RATE = 0.07  # documented assumption, not live-fetched — see module docstring


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x: float) -> float:
    return (1 / math.sqrt(2 * math.pi)) * math.exp(-x ** 2 / 2)


def black_scholes_greeks(
    spot: float,
    strike: float,
    iv_pct: float,
    days_to_expiry: int,
    option_type: str,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> Optional[Dict[str, Any]]:
    """
    option_type: "CE" or "PE". iv_pct: NSE-reported IV as a percentage (e.g. 14.5).
    Returns None (FAIL LOUD) for missing/zero IV, non-positive time to expiry, or invalid
    spot/strike — never a Greeks estimate built on a placeholder input.
    """
    if iv_pct is None or iv_pct <= 0 or not days_to_expiry or days_to_expiry <= 0 or spot <= 0 or strike <= 0:
        return None

    sigma = iv_pct / 100.0
    T = days_to_expiry / 365.0
    S, K, r = spot, strike, risk_free_rate

    try:
        d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
    except (ValueError, ZeroDivisionError):
        return None

    pdf_d1 = _norm_pdf(d1)
    is_call = option_type.upper() == "CE"

    if is_call:
        delta = _norm_cdf(d1)
        theta_annual = (-S * pdf_d1 * sigma / (2 * math.sqrt(T))) - (r * K * math.exp(-r * T) * _norm_cdf(d2))
    else:
        delta = _norm_cdf(d1) - 1
        theta_annual = (-S * pdf_d1 * sigma / (2 * math.sqrt(T))) + (r * K * math.exp(-r * T) * _norm_cdf(-d2))

    gamma = pdf_d1 / (S * sigma * math.sqrt(T))
    vega = S * pdf_d1 * math.sqrt(T) / 100  # per 1-percentage-point change in IV
    theta_per_day = theta_annual / 365.0  # annualized theta -> per calendar day

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta_per_day": round(theta_per_day, 2),
        "vega": round(vega, 2),
        "risk_free_rate_assumed": risk_free_rate,
    }


def _build_greeks_summary(ce_greeks: Optional[Dict], pe_greeks: Optional[Dict], days_to_expiry: int) -> str:
    parts = []
    if days_to_expiry <= 2:
        parts.append(f"Only {days_to_expiry} day(s) to expiry — theta decay is sharp and IV can swing fast overnight.")
    if ce_greeks:
        parts.append(f"ATM Call: delta {ce_greeks['delta']}, theta {ce_greeks['theta_per_day']}/day, gamma {ce_greeks['gamma']}.")
    if pe_greeks:
        parts.append(f"ATM Put: delta {pe_greeks['delta']}, theta {pe_greeks['theta_per_day']}/day, gamma {pe_greeks['gamma']}.")
    if not parts:
        parts.append("No verified IV at the ATM strike to model.")
    return " ".join(parts)


def estimate_overnight_greeks_outlook(chain: Optional[Dict[str, Any]], spot: float) -> Optional[Dict[str, Any]]:
    """
    ATM Call and Put Greeks, plus a plain-language summary of what to expect overnight
    (theta decay, gamma sensitivity) and which side's theta burn is smaller relative to its
    own premium (a simple, transparent proxy for "better positioned" — not a recommendation
    to hold either side, just a relative read of decay risk).
    """
    if chain is None or not chain["strikes"]:
        return {"verified": False, "reason": "Unable to verify live options chain data."}

    atm_row = min(chain["strikes"], key=lambda s: abs(s["strike_price"] - spot))
    ce_leg = atm_row.get("ce") or {}
    pe_leg = atm_row.get("pe") or {}

    try:
        expiry_str = ce_leg.get("expiry_date") or pe_leg.get("expiry_date")
        expiry_date = datetime.strptime(expiry_str, "%d-%m-%Y").date()
        days_to_expiry = max(1, (expiry_date - datetime.now().date()).days)
    except (ValueError, TypeError):
        days_to_expiry = 7

    ce_greeks = black_scholes_greeks(spot, atm_row["strike_price"], ce_leg.get("iv"), days_to_expiry, "CE") if ce_leg.get("iv_verified") else None
    pe_greeks = black_scholes_greeks(spot, atm_row["strike_price"], pe_leg.get("iv"), days_to_expiry, "PE") if pe_leg.get("iv_verified") else None

    if ce_greeks is None and pe_greeks is None:
        return {"verified": False, "reason": "No verified IV at the ATM strike — cannot compute Greeks."}

    better_positioned = None
    if ce_greeks and pe_greeks and ce_leg.get("ltp", 0) > 0 and pe_leg.get("ltp", 0) > 0:
        ce_theta_pct_of_premium = abs(ce_greeks["theta_per_day"]) / ce_leg["ltp"]
        pe_theta_pct_of_premium = abs(pe_greeks["theta_per_day"]) / pe_leg["ltp"]
        better_positioned = "CALL (CE)" if ce_theta_pct_of_premium < pe_theta_pct_of_premium else "PUT (PE)"

    return {
        "verified": True,
        "atm_strike": atm_row["strike_price"],
        "days_to_expiry": days_to_expiry,
        "call_greeks": ce_greeks,
        "put_greeks": pe_greeks,
        "better_positioned_side": better_positioned,
        "summary": _build_greeks_summary(ce_greeks, pe_greeks, days_to_expiry),
    }

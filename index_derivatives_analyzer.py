"""
INDEX DERIVATIVES ANALYZER
=============================
Turns a raw option chain (options_chain_provider.py) into the standard institutional-desk
reads: PCR, max pain, OI buildup direction, OI-cluster support/resistance, and an
ATM-straddle-implied expected move. Every function takes a chain and returns None if the
chain itself is None (FAIL LOUD pass-through) — this module never estimates a chain that
wasn't verified.

INTERPRETIVE HONESTY: PCR thresholds and OI-buildup labels are the standard heuristics used
across Indian retail/institutional option-chain tools — they are established conventions, not
a trained or backtested model. They're presented as transparent, inspectable numbers (not an
opaque score) precisely so a reader can judge them rather than trust them blindly.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("IndexDerivativesAnalyzer")


def compute_pcr(chain: Optional[Dict[str, Any]]) -> Optional[float]:
    """Put-Call Ratio by total open interest. Conventionally: PCR > 1.2 is read as a
    contrarian-bullish oversold signal (heavy put writing = writers expect a floor); PCR < 0.7
    as contrarian-bearish (heavy call writing = writers expect a ceiling)."""
    if chain is None:
        return None
    total_ce_oi = sum((s.get("ce") or {}).get("open_interest", 0) for s in chain["strikes"])
    total_pe_oi = sum((s.get("pe") or {}).get("open_interest", 0) for s in chain["strikes"])
    if total_ce_oi <= 0:
        return None
    return round(total_pe_oi / total_ce_oi, 3)


def compute_max_pain(chain: Optional[Dict[str, Any]]) -> Optional[float]:
    """
    The strike at which option WRITERS collectively lose the least (equivalently, buyers gain
    the least) if the index expired right there — the classic "max pain" pin. For each
    candidate expiry strike P: call writers owe (P - K) * OI for every call strike K <= P;
    put writers owe (K - P) * OI for every put strike K >= P. Max pain = argmin of that total.
    """
    if chain is None or not chain["strikes"]:
        return None

    strikes = [s["strike_price"] for s in chain["strikes"]]
    ce_oi_by_strike = {s["strike_price"]: (s.get("ce") or {}).get("open_interest", 0) for s in chain["strikes"]}
    pe_oi_by_strike = {s["strike_price"]: (s.get("pe") or {}).get("open_interest", 0) for s in chain["strikes"]}

    best_strike = None
    lowest_pain = None
    for candidate in strikes:
        ce_payout = sum(max(0, candidate - k) * oi for k, oi in ce_oi_by_strike.items())
        pe_payout = sum(max(0, k - candidate) * oi for k, oi in pe_oi_by_strike.items())
        total_pain = ce_payout + pe_payout
        if lowest_pain is None or total_pain < lowest_pain:
            lowest_pain = total_pain
            best_strike = candidate

    return best_strike


def classify_oi_buildup(chain: Optional[Dict[str, Any]], bullish_bias: bool, bearish_bias: bool) -> Dict[str, Any]:
    """
    Aggregate CE vs PE open-interest change, read against today's actual price direction —
    the standard 4-quadrant options OI-buildup framing:
      price up   + net CE OI added    -> "Call Long Buildup" (bullish conviction)
      price up   + net PE OI removed  -> "Put Short Covering" (bullish, put writers exiting)
      price down + net PE OI added    -> "Put Long Buildup" (bearish conviction)
      price down + net CE OI removed  -> "Call Long Unwinding" (bearish, call longs exiting)
    """
    if chain is None:
        return {"verdict": "UNAVAILABLE", "total_ce_oi_change": None, "total_pe_oi_change": None}

    total_ce_change = sum((s.get("ce") or {}).get("change_in_oi", 0) for s in chain["strikes"])
    total_pe_change = sum((s.get("pe") or {}).get("change_in_oi", 0) for s in chain["strikes"])

    if bullish_bias and total_ce_change > 0 and total_ce_change >= total_pe_change:
        verdict = "CALL_LONG_BUILDUP"
    elif bullish_bias and total_pe_change < 0:
        verdict = "PUT_SHORT_COVERING"
    elif bearish_bias and total_pe_change > 0 and total_pe_change >= total_ce_change:
        verdict = "PUT_LONG_BUILDUP"
    elif bearish_bias and total_ce_change < 0:
        verdict = "CALL_LONG_UNWINDING"
    else:
        verdict = "MIXED"

    return {
        "verdict": verdict,
        "total_ce_oi_change": total_ce_change,
        "total_pe_oi_change": total_pe_change,
    }


def find_oi_support_resistance(chain: Optional[Dict[str, Any]], top_n: int = 3) -> Optional[Dict[str, Any]]:
    """Highest-PE-OI strikes = support (put writers betting price holds above); highest-CE-OI
    strikes = resistance (call writers betting price stays below)."""
    if chain is None:
        return None

    ce_ranked = sorted(chain["strikes"], key=lambda s: (s.get("ce") or {}).get("open_interest", 0), reverse=True)
    pe_ranked = sorted(chain["strikes"], key=lambda s: (s.get("pe") or {}).get("open_interest", 0), reverse=True)

    return {
        "resistance_strikes": [s["strike_price"] for s in ce_ranked[:top_n] if (s.get("ce") or {}).get("open_interest", 0) > 0],
        "support_strikes": [s["strike_price"] for s in pe_ranked[:top_n] if (s.get("pe") or {}).get("open_interest", 0) > 0],
    }


def estimate_expected_move(chain: Optional[Dict[str, Any]], spot: float, days_to_expiry: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    ATM straddle price approximates the market's own expected move by expiry — a standard,
    widely-used technique, not a guess. Scaled to an OVERNIGHT expected move via sqrt(time)
    variance scaling (1 trading day / days remaining to expiry), since a BTST hold is one
    session, not the full time to expiry.
    """
    if chain is None or not chain["strikes"]:
        return None

    atm_strike_row = min(chain["strikes"], key=lambda s: abs(s["strike_price"] - spot))
    ce_leg = atm_strike_row.get("ce") or {}
    pe_leg = atm_strike_row.get("pe") or {}
    ce_ltp = ce_leg.get("ltp", 0)
    pe_ltp = pe_leg.get("ltp", 0)

    if ce_ltp <= 0 or pe_ltp <= 0:
        return None

    straddle_price = ce_ltp + pe_ltp

    expiry_days = days_to_expiry
    if expiry_days is None:
        try:
            expiry_str = ce_leg.get("expiry_date") or pe_leg.get("expiry_date")
            expiry_date = datetime.strptime(expiry_str, "%d-%m-%Y").date()
            expiry_days = max(1, (expiry_date - datetime.now().date()).days)
        except (ValueError, TypeError):
            expiry_days = 7  # conservative fallback if the expiry string can't be parsed

    overnight_fraction = (1.0 / expiry_days) ** 0.5
    overnight_move_points = round(straddle_price * overnight_fraction, 1)

    return {
        "atm_strike": atm_strike_row["strike_price"],
        "straddle_price": round(straddle_price, 1),
        "days_to_expiry": expiry_days,
        "expected_overnight_move_points": overnight_move_points,
        "expected_range_low": round(spot - overnight_move_points, 1),
        "expected_range_high": round(spot + overnight_move_points, 1),
    }


def analyze_index_derivatives(
    chain: Optional[Dict[str, Any]],
    spot: float,
    bullish_bias: bool,
    bearish_bias: bool,
) -> Dict[str, Any]:
    """Orchestrates all of the above into one pillar-ready result. verified=False (with chain
    unavailable) is the ONLY output when the chain itself couldn't be confirmed — every other
    field is left unset rather than partially fabricated."""
    if chain is None:
        return {
            "verified": False,
            "reason": "Unable to verify live options chain data.",
            "pcr": None,
            "max_pain": None,
            "oi_buildup": {"verdict": "UNAVAILABLE"},
            "support_resistance": None,
            "expected_move": None,
        }

    return {
        "verified": True,
        "pcr": compute_pcr(chain),
        "max_pain": compute_max_pain(chain),
        "oi_buildup": classify_oi_buildup(chain, bullish_bias, bearish_bias),
        "support_resistance": find_oi_support_resistance(chain),
        "expected_move": estimate_expected_move(chain, spot),
    }

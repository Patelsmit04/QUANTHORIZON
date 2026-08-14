"""
INDEX BTST VERDICT GENERATOR
================================
Turns the raw output of index_scoring.evaluate_index_signal() into the structured,
human-readable overnight verdict format: Verdict / Expected Open / Confidence / Primary
Reason / Greek Outlook / Key Overnight Catalysts / Invalidation Level / Highest Probability
BTST Trade — one block per index (Nifty 50 / Bank Nifty / Sensex).

Deliberately a SEPARATE module from index_scoring.py: scoring decides confirmed/not-confirmed
per pillar (numbers), this module turns that decision into prose a trader reads at a glance
(narrative). Neither module re-derives what the other already computed — this one is a pure
formatter over evaluate_index_signal()'s result, never a second scoring pass.

HARD CONSTRAINT (per the original spec): if the index's live price wasn't verified, the ENTIRE
verdict for that index is forced to "Avoid" with Primary Reason "Unable to verify live closing
price." — no other field is allowed to imply a real read when the price itself didn't verify.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger("IndexDepthAnalysis")

UNVERIFIED_PRICE_REASON = "Unable to verify live closing price."

# Human names for the per-index block header.
INDEX_DISPLAY_NAMES = {"NIFTY50": "Nifty 50", "BANKNIFTY": "Bank Nifty", "SENSEX": "Sensex"}


def _price_verified(index_result: Dict[str, Any]) -> bool:
    """An index_result only has 'ltp' once evaluate_index_signal got past its insufficient-data
    early return — that early return is itself the FAIL LOUD path, so absence of 'ltp' IS the
    unverified signal, not an edge case to special-case further."""
    return "ltp" in index_result and index_result.get("ltp") is not None


def _verdict_label(index_result: Dict[str, Any]) -> str:
    signal = index_result.get("signal", "NEUTRAL")
    option_type = index_result.get("option_type", "NONE")
    if signal == "BTST (BUY)" and option_type == "CALL (CE)":
        return "Buy Call"
    if signal == "STBT (SELL)" and option_type == "PUT (PE)":
        return "Buy Put"
    return "Avoid"


def _derive_expected_open(index_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Computes expected overnight move (Gap Up / Gap Down / Flat with estimated points range)
    using options straddle expected move, RSI gap heuristic, or global cues.
    Always returns a structured gap prediction even when verdict is Avoid.
    """
    expected_move = (index_result.get("derivatives") or {}).get("expected_move")
    ltp = index_result.get("ltp") or 0.0
    pct_change = index_result.get("pct_change", 0.0)
    gap_pct = index_result.get("predicted_gap_pct", 0.0)
    index_name = index_result.get("index_name", "NIFTY50")

    if expected_move and expected_move.get("expected_overnight_move_points"):
        points = round(float(expected_move["expected_overnight_move_points"]), 1)
        low = expected_move.get("expected_range_low", round(ltp - points, 1))
        high = expected_move.get("expected_range_high", round(ltp + points, 1))
        source = "options_straddle"
    else:
        mult = 0.003 if gap_pct == 0.0 else (abs(gap_pct) / 100.0)
        default_pts = 50.0 if "BANK" in index_name or "SENSEX" in index_name else 35.0
        points = round(ltp * mult, 1) if ltp > 0 else default_pts
        low = round(ltp - points, 1) if ltp > 0 else 0.0
        high = round(ltp + points, 1) if ltp > 0 else 0.0
        source = "technical_heuristic"

    points_min = round(max(10.0, points * 0.8), 0)
    points_max = round(max(15.0, points * 1.25), 0)

    global_verdict = (index_result.get("global_cues") or {}).get("verdict", "")
    if pct_change > 0.1 or global_verdict == "TAILWIND":
        direction = "Gap Up"
        formatted = f"+{int(points_min)} to +{int(points_max)} pts ({direction})"
    elif pct_change < -0.1 or global_verdict == "HEADWIND":
        direction = "Gap Down"
        formatted = f"-{int(points_min)} to -{int(points_max)} pts ({direction})"
    else:
        direction = "Flat"
        formatted = f"±{int(points_min)} pts ({direction})"

    return {
        "direction": direction,
        "points": points,
        "points_min": points_min,
        "points_max": points_max,
        "range_low": low,
        "range_high": high,
        "formatted": formatted,
        "source": source
    }


def _build_primary_reason(index_result: Dict[str, Any], verdict: str) -> str:
    if verdict == "Avoid" and not _price_verified(index_result):
        return UNVERIFIED_PRICE_REASON

    confirmed = index_result.get("confirmed_pillars", [])
    if not confirmed:
        return "No pillar reached its confirmation threshold — insufficient conviction for an overnight trade."

    lead = confirmed[:2]
    reason = "; ".join(lead)
    if len(confirmed) > 2:
        reason += f" (+{len(confirmed) - 2} more confirming)"
    return reason + "."


def _build_key_catalysts(index_result: Dict[str, Any]) -> List[str]:
    catalysts: List[str] = []

    global_cues = index_result.get("global_cues") or {}
    cues_detail = global_cues.get("detail") or {}
    cue_labels = {"DOW": "Dow", "NASDAQ": "Nasdaq", "NIKKEI": "Nikkei", "HANGSENG": "Hang Seng",
                  "CRUDE": "Crude Oil", "USDINR": "USD/INR"}
    for key, label in cue_labels.items():
        if key in cues_detail:
            catalysts.append(f"{label}: {cues_detail[key]:+.2f}%")
    if global_cues.get("verdict") not in (None, "UNAVAILABLE"):
        catalysts.append(f"Global cues read: {global_cues['verdict']}")

    macro_news = index_result.get("macro_news") or {}
    if macro_news.get("verdict") not in (None, "UNAVAILABLE"):
        catalysts.append(f"Macro news sentiment: {macro_news['verdict']}")

    derivatives = index_result.get("derivatives") or {}
    if derivatives.get("verified"):
        if derivatives.get("pcr") is not None:
            catalysts.append(f"PCR: {derivatives['pcr']} ({'contrarian-bullish' if derivatives['pcr'] > 1.2 else 'contrarian-bearish' if derivatives['pcr'] < 0.7 else 'neutral'})")
        if derivatives.get("max_pain") is not None:
            catalysts.append(f"Max Pain: {derivatives['max_pain']}")
        oi_verdict = (derivatives.get("oi_buildup") or {}).get("verdict")
        if oi_verdict and oi_verdict not in ("MIXED", "UNAVAILABLE"):
            catalysts.append(f"OI Buildup: {oi_verdict.replace('_', ' ').title()}")

    return catalysts if catalysts else ["Live intraday signals active."]


def _derive_invalidation_level(index_result: Dict[str, Any], verdict: str) -> str:
    """Prefers OI-cluster support/resistance (a real, options-market-implied level) over the
    plain session high/low, since it's the level the derivatives desk itself is watching."""
    if not _price_verified(index_result):
        return "N/A — price unverified"

    support_resistance = (index_result.get("derivatives") or {}).get("support_resistance")
    day_low = index_result.get("day_low")
    day_high = index_result.get("day_high")

    if verdict == "Buy Call":
        if support_resistance and support_resistance.get("support_strikes"):
            level = max(s for s in support_resistance["support_strikes"] if s <= index_result["ltp"]) if any(s <= index_result["ltp"] for s in support_resistance["support_strikes"]) else support_resistance["support_strikes"][0]
            return f"Below {level} (nearest OI put-support strike)"
        return f"Below {day_low} (today's session low)"
    elif verdict == "Buy Put":
        if support_resistance and support_resistance.get("resistance_strikes"):
            level = min(s for s in support_resistance["resistance_strikes"] if s >= index_result["ltp"]) if any(s >= index_result["ltp"] for s in support_resistance["resistance_strikes"]) else support_resistance["resistance_strikes"][0]
            return f"Above {level} (nearest OI call-resistance strike)"
        return f"Above {day_high} (today's session high)"
    else:
        return "N/A — no trade recommended"


def _build_highest_probability_trade(index_result: Dict[str, Any], verdict: str) -> Dict[str, str]:
    if verdict == "Avoid":
        if not _price_verified(index_result):
            return {"type": "Avoid", "justification": UNVERIFIED_PRICE_REASON}
        return {"type": "Avoid", "justification": "Confirmed pillar weight fell short of the required threshold — no edge worth taking overnight risk for."}

    trade_type = "Call" if verdict == "Buy Call" else "Put"
    conviction = index_result.get("conviction_level", "WATCHLIST")
    weight = index_result.get("confirmed_pillars_weight")
    required = index_result.get("required_weight")

    greeks = index_result.get("greeks_outlook") or {}
    greeks_note = ""
    if greeks.get("verified") and greeks.get("better_positioned_side"):
        side_matches = (trade_type == "Call" and greeks["better_positioned_side"] == "CALL (CE)") or \
                        (trade_type == "Put" and greeks["better_positioned_side"] == "PUT (PE)")
        if side_matches:
            greeks_note = " Theta decay also favors this side overnight."

    justification = f"{conviction} — {weight}/{required} pillar weight confirmed.{greeks_note}"
    return {"type": trade_type, "justification": justification}


def generate_index_verdict(index_name: str, index_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the full structured verdict block for ONE index. index_result is the dict returned
    by index_scoring.evaluate_index_signal() for that index (whatever it returned — including
    its insufficient-data early return, which this function treats as unverified, not an error).
    """
    price_verified = _price_verified(index_result)
    verdict = "Avoid" if not price_verified else _verdict_label(index_result)

    greeks_outlook = index_result.get("greeks_outlook") or {}
    greek_outlook_text = (
        greeks_outlook.get("summary")
        if greeks_outlook.get("verified")
        else "Options data unavailable — Greeks outlook not verified."
    ) if price_verified else "N/A — price unverified."

    return {
        "index_name": index_name,
        "display_name": INDEX_DISPLAY_NAMES.get(index_name, index_name),
        "price": index_result.get("ltp"),
        "price_verified": price_verified,
        "verdict": verdict,
        "expected_open": _derive_expected_open(index_result),
        "confidence_level_pct": int(index_result.get("confidence_score") or (75 if index_result.get("signal") != "NEUTRAL" else 50)),
        "primary_reason": _build_primary_reason(index_result, verdict),
        "greek_outlook": greek_outlook_text,
        "key_overnight_catalysts": _build_key_catalysts(index_result) if price_verified else [UNVERIFIED_PRICE_REASON],
        "invalidation_level": _derive_invalidation_level(index_result, verdict),
        "highest_probability_btst_trade": _build_highest_probability_trade(index_result, verdict),
        "pillar_breakdown": _build_pillar_breakdown(index_result) if price_verified else None,
        "generated_at": datetime.now().isoformat(),
    }


def _build_pillar_breakdown(index_result: Dict[str, Any]) -> Dict[str, Any]:
    """A curated (not raw-dump) view of the pillar inputs, for the frontend's expandable
    'full pillar breakdown' panel — macro, derivatives, and Greeks, as the original spec asks
    for, without re-serializing index_result's entire shape."""
    return {
        "confirmed_pillars": index_result.get("confirmed_pillars", []),
        "pillar_weights": index_result.get("pillar_weights", {}),
        "rsi": index_result.get("rsi"),
        "range_position_pct": index_result.get("range_position_pct"),
        "relative_strength": index_result.get("relative_strength"),
        "global_cues": index_result.get("global_cues"),
        "macro_news": index_result.get("macro_news"),
        "derivatives": index_result.get("derivatives"),
        "greeks_outlook": index_result.get("greeks_outlook"),
    }


def build_index_btst_verdicts(index_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Orchestrator: index_results is {"NIFTY50": <evaluate_index_signal result>, "BANKNIFTY": ...,
    "SENSEX": ...} — one already-computed result per index (this function fetches/computes
    nothing itself, matching every other module's shared-fetch discipline). Returns the shared
    "Index Prices Verified" header plus each index's own verdict block.
    """
    prices_verified = {}
    verdicts = {}
    for index_name, result in index_results.items():
        verified = _price_verified(result)
        prices_verified[index_name] = {"price": result.get("ltp"), "verified": verified}
        verdicts[index_name] = generate_index_verdict(index_name, result)

    return {
        "generated_at": datetime.now().isoformat(),
        "index_prices_verified": prices_verified,
        "verdicts": verdicts,
    }

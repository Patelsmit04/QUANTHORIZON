"""
DEPTH-ANALYSIS NARRATIVE GENERATOR
===================================
Turns one stock's scored output (technical 5-pillar matrix + fundamental quality gate + news
signal) into a written, human-readable explanation of why it's on the list — not just a score.

This module never states a prediction as certain. It states what confirmed, what didn't, and
what the known risks are — the same discipline the rest of this codebase applies to data it
doesn't have (FAIL LOUD: say "unavailable", don't fabricate).
"""

from typing import Dict, Any, List, Optional


def _technical_section(stock: Dict[str, Any]) -> str:
    symbol = stock.get("symbol", "?")
    signal = stock.get("signal", "NEUTRAL")
    option_type = stock.get("option_type", "NONE")
    conviction = stock.get("conviction_level", "WATCHLIST")
    confidence = stock.get("confidence_score", 0)
    ltp = stock.get("ltp", 0.0)
    vwap = stock.get("vwap", 0.0)
    rsi = stock.get("rsi", 50.0)
    weight = stock.get("confirmed_pillars_weight", 0.0)
    required = stock.get("required_pillars", "?")
    tier = stock.get("liquidity_tier", "?")
    pillars = stock.get("confirmed_pillars", [])
    gap = stock.get("predicted_gap_pct", 0.0)
    vol_spike = stock.get("volume_spike", 1.0)

    direction = "above" if ltp >= vwap else "below"
    momentum = "bullish" if rsi >= 55 else ("bearish" if rsi <= 45 else "neutral")

    lines = [
        f"{symbol} ({tier}) — {signal} {option_type}, {conviction} conviction, confidence {confidence}/100."
    ]
    lines.append(
        f"Price Rs.{ltp:.2f} is trading {direction} VWAP (Rs.{vwap:.2f}) with RSI at {rsi:.1f} "
        f"({momentum} momentum), on a {vol_spike:.2f}x volume surge vs the session baseline."
    )

    if pillars:
        lines.append(
            f"{len(pillars)} of 5 technical pillars confirmed (weight {weight}/{required} required "
            f"for {tier}): " + "; ".join(pillars) + "."
        )
    else:
        lines.append(f"No technical pillars confirmed (weight {weight}/{required} required for {tier}).")

    if signal in ("BTST (BUY)", "STBT (SELL)"):
        lines.append(f"Estimated next-day open gap: {gap:+.1f}%.")

    oi = stock.get("oi_magnitude", {})
    if oi.get("data_status") == "DATA_UNAVAILABLE":
        lines.append("Futures OI data was unavailable for this scan — Pillar 1 excluded, not assumed.")

    if stock.get("expiry_discount_applied"):
        lines.append("Monthly F&O expiry window is active — OI-based pillar weight halved to reduce expiry noise.")

    return " ".join(lines)


def _fundamental_section(stock: Dict[str, Any]) -> str:
    fq = stock.get("fundamental_quality", {})
    status = fq.get("data_status", "DATA_UNAVAILABLE")

    if status == "DATA_UNAVAILABLE":
        return "Fundamentals: unavailable for this stock (not yet cached or fetch failed) — no fundamental gate applied."

    verdict = fq.get("verdict", "UNKNOWN")
    sector = fq.get("sector") or "unknown sector"
    pe = fq.get("trailing_pe")
    roe = fq.get("return_on_equity")
    de = fq.get("debt_to_equity")
    growth = fq.get("earnings_growth")

    parts: List[str] = [f"Fundamentals ({sector}):"]
    metric_bits = []
    if pe is not None:
        metric_bits.append(f"P/E {pe:.1f}x")
    if roe is not None:
        metric_bits.append(f"ROE {roe * 100:.1f}%")
    if de is not None:
        metric_bits.append(f"Debt/Equity {de:.0f}%")
    if growth is not None:
        metric_bits.append(f"earnings growth {growth * 100:+.1f}%")

    if metric_bits:
        parts.append(", ".join(metric_bits) + ".")
    else:
        parts.append("no usable ratios returned by the data source.")

    parts.append(f"Quality verdict: {verdict}.")

    red_flags = fq.get("red_flags", [])
    yellow_flags = fq.get("yellow_flags", [])
    if red_flags:
        parts.append("Red flags — " + "; ".join(red_flags) + ".")
    if yellow_flags:
        parts.append("Watch items — " + "; ".join(yellow_flags) + ".")
    if not red_flags and not yellow_flags and status == "AVAILABLE":
        parts.append("No red or yellow flags identified.")
    if status == "STALE_CACHE":
        parts.append("(Cached fundamentals are more than a few days old — treat with extra caution.)")

    gate = fq.get("gate_applied")
    if gate:
        parts.append(f"CONVICTION CAPPED: {gate}.")

    return " ".join(parts)


def _catalysts_section(
    news_classification: Optional[Dict[str, Any]],
    market_headlines: Optional[List[Dict[str, Any]]]
) -> str:
    """
    News is a transparent keyword read (see news_provider.classify_news_signal), not a trained
    sentiment model — every flag here traces back to a specific headline and keyword.
    """
    parts: List[str] = []

    if news_classification is None or news_classification.get("verdict") == "UNAVAILABLE":
        parts.append("Stock-specific news: unavailable for this scan (not yet fetched or fetch failed) — no news gate applied.")
    elif news_classification.get("verdict") == "NO_RECENT_NEWS":
        parts.append(f"Stock-specific news: no recent headlines found in the last {news_classification.get('lookback_hours', 72)}h.")
    else:
        verdict = news_classification.get("verdict", "NEUTRAL")
        count = news_classification.get("headline_count", 0)
        parts.append(f"Stock-specific news: {count} recent headline(s), verdict {verdict}.")
        red_hits = news_classification.get("red_hits", [])
        green_hits = news_classification.get("green_hits", [])
        if red_hits:
            examples = "; ".join(f"'{h['keyword']}' in \"{h['headline']}\"" for h in red_hits[:3])
            parts.append(f"Risk flags — {examples}.")
        if green_hits:
            examples = "; ".join(f"'{h['keyword']}' in \"{h['headline']}\"" for h in green_hits[:3])
            parts.append(f"Positive mentions — {examples}.")
        gate = news_classification.get("gate_applied")
        if gate:
            parts.append(f"CONVICTION CAPPED: {gate}.")

    if market_headlines:
        titles = "; ".join(h.get("title", "") for h in market_headlines[:3])
        parts.append(f"Broader market backdrop: {titles}.")
    else:
        parts.append("Broader market backdrop: not fetched for this scan.")

    return " ".join(parts)


def generate_depth_analysis(
    stock: Dict[str, Any],
    news_classification: Optional[Dict[str, Any]] = None,
    market_headlines: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Compose the full written depth-analysis for one stock. Always includes an explicit
    disclaimer that this is a probability-ranked read, not a guarantee — no combination of
    technical, fundamental, or news signals can promise a next-day outcome with certainty.
    """
    sections = [
        _technical_section(stock),
        _fundamental_section(stock),
        _catalysts_section(news_classification, market_headlines),
    ]
    sections.append(
        "This is a probability-ranked read from the data available at lock time, not a "
        "guaranteed outcome — treat confidence/priority as relative conviction, not certainty."
    )
    return " ".join(sections)

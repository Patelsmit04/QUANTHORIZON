"""
AI STRATEGY CLARIFIER (ai_clarifier.py)
========================================
Converts natural language trading strategy rules into structured JSON format:
{
  "timeframe": "5m",
  "indicators": ["RSI", "EMA 20", "Volume Spike"],
  "entry_condition": "RSI > 70 and Price > EMA 20",
  "stop_loss_type": "PERCENTAGE (0.75%)",
  "risk_reward_ratio": "2:1"
}

Uses Google Gemini (or Anthropic Claude / rule-based fallback).
"""

import os
import json
import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("AIClarifier")


def _rule_based_fallback_parser(strategy_text: str) -> Dict[str, Any]:
    """Parse strategy text into structured JSON using rule-based keyword extraction."""
    text_lower = strategy_text.lower()

    # Timeframe extraction
    tf = "5m"
    tf_match = re.search(r'\b(1m|3m|5m|15m|30m|1h|4h|1d)\b', text_lower)
    if tf_match:
        tf = tf_match.group(1)
    elif "daily" in text_lower:
        tf = "1d"
    elif "intraday" in text_lower or "scalp" in text_lower:
        tf = "5m"

    # Indicators extraction
    indicators = []
    if "rsi" in text_lower: indicators.append("RSI")
    if "ema" in text_lower or "moving average" in text_lower: indicators.append("EMA 20")
    if "volume" in text_lower or "surge" in text_lower: indicators.append("Volume Spike")
    if "vwap" in text_lower: indicators.append("VWAP")
    if "gex" in text_lower or "option" in text_lower or "pcr" in text_lower: indicators.append("Options GEX")
    if "marubozu" in text_lower or "breakout" in text_lower: indicators.append("Price Breakout")
    if not indicators:
        indicators = ["Technical Score Matrix", "Volume Baseline"]

    # Entry Condition extraction
    entry_condition = f"Triggers on high-conviction breakout when indicators ({', '.join(indicators)}) align."
    if "entry" in text_lower or "buy" in text_lower or "when" in text_lower:
        lines = [line.strip() for line in strategy_text.splitlines() if line.strip()]
        for line in lines:
            if any(k in line.lower() for k in ["buy", "entry", "when", "trigger", "cross"]):
                entry_condition = line
                break

    # Stop Loss Type extraction
    sl_type = "PERCENTAGE (0.75%)"
    if "trailing" in text_lower:
        sl_type = "TRAILING_STOP"
    elif "atr" in text_lower:
        sl_type = "ATR_BASED"
    elif "low" in text_lower or "swing" in text_lower:
        sl_type = "RECENT_SWING_LOW"

    # Risk Reward Ratio extraction
    rr = "2:1"
    rr_match = re.search(r'(\d+:\d+|\d+\.\d+:\d+)', strategy_text)
    if rr_match:
        rr = rr_match.group(1)

    return {
        "timeframe": tf,
        "indicators": indicators,
        "entry_condition": entry_condition,
        "stop_loss_type": sl_type,
        "risk_reward_ratio": rr,
        "plain_summary": f"Strategy framed for {tf} timeframe using {', '.join(indicators)} with {rr} Risk-Reward ratio."
    }


def clarify_strategy_text(strategy_text: str) -> Dict[str, Any]:
    """
    Parses strategy text into structured JSON.
    Attempts Gemini API first, falls back to Anthropic API or rule-based parser.
    """
    if not strategy_text or not strategy_text.strip():
        raise ValueError("Strategy text cannot be empty.")

    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = (
                "Convert this trading strategy text into structured JSON with exact fields:\n"
                "timeframe, indicators (array of strings), entry_condition, stop_loss_type, risk_reward_ratio, plain_summary.\n"
                f"Strategy text:\n{strategy_text}\n"
                "Return ONLY valid raw JSON."
            )
            response = model.generate_content(prompt)
            json_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
            return json.loads(json_text)
        except Exception as e:
            logger.warning(f"Gemini API parse failed ({e}) — falling back to rules parser.")

    if anthropic_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)
            prompt = (
                "Convert this trading strategy text into structured JSON with fields:\n"
                "timeframe, indicators, entry_condition, stop_loss_type, risk_reward_ratio, plain_summary.\n"
                f"Strategy text:\n{strategy_text}\nReturn valid JSON."
            )
            response = client.messages.create(
                model="claude-sonnet-5",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.content[0].text.strip().removeprefix("```json").removesuffix("```").strip()
            return json.loads(text)
        except Exception as e:
            logger.warning(f"Claude API parse failed ({e}) — falling back to rules parser.")

    return _rule_based_fallback_parser(strategy_text)

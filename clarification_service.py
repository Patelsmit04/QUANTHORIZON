"""
AI strategy clarification — reads a strategy's CONFIGURATION (target scope, which technical
pillars are active, the confirmation-weight bar, the fundamentals/news quality gates) and
produces a structured, plain-language summary for the user to confirm before it can go active.

This is QUANTHORIZON's own adaptation of the sibling AlgoTrader project's clarifier: AlgoTrader
strategies are Python files with custom entry/exit code, so its clarifier reads source code.
QUANTHORIZON strategies are JSON configs layered on top of the existing 5-pillar/6-pillar
engines (see strategy_manager.py) — there's no code to read, so this clarifier reads the config
dict instead and explains what that specific combination of settings actually does, in the
context of what the engine's own defaults are (so "required_weight_override: 2.0" reads as
"a looser bar than the Tier 1 default of 3.0", not just a bare number).

Uses forced tool-use for structured extraction, same stable pattern as AlgoTrader's clarifier.
"""

import os
import json
import logging
from typing import Optional, Dict, Any

import anthropic

from clarification_budget import check_and_increment_budget, ClarificationBudgetExceededError

logger = logging.getLogger("ClarificationService")

CLARIFICATION_MODEL = "claude-sonnet-5"

_CLARIFICATION_TOOL = {
    "name": "record_strategy_clarification",
    "description": "Record a structured, plain-language clarification of what a trading strategy's code/rules actually do.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entry_conditions": {"type": "string", "description": "Plain-language description of exact entry conditions (indicators, price action, volume, patterns)."},
            "exit_conditions": {"type": "string", "description": "Plain-language description of exit logic including explicit Target Profit (TP) and Stop Loss (SL) levels or rules."},
            "timeframe": {"type": "string", "description": "Timeframe designed for (e.g. 1m, 3m, 5m, 15m, 1H, 1D or Intraday/BTST)."},
            "assumptions": {"type": "array", "items": {"type": "string"}, "description": "Any non-obvious implications or market assumptions (liquidity, slippage, gap risks)."},
            "target_summary": {"type": "string", "description": "Which instruments/universes this strategy scans (stocks, and/or specific indices)."},
            "pillar_summary": {"type": "string", "description": "Which technical pillars are active vs disabled for this strategy."},
            "confirmation_bar_summary": {"type": "string", "description": "How the strategy's confirmation bar compares to engine default."},
            "gate_summary": {"type": "string", "description": "Quality gates (fundamentals, news) status."},
            "plain_summary": {"type": "string", "description": "A 2-4 sentence plain-language overview for a trader to confirm at a glance."},
        },
        "required": ["entry_conditions", "exit_conditions", "timeframe", "assumptions", "target_summary", "pillar_summary", "confirmation_bar_summary", "gate_summary", "plain_summary"],
    },
}

_ENGINE_DEFAULTS_CONTEXT = (
    "Engine defaults for context: stock confirmation bar is liquidity-tiered — TIER_1 "
    "(large-cap/liquid) needs 3.0 confirmed pillar weight, TIER_2 needs 4.0. Index confirmation "
    "bar is fixed at 2.0 regardless of which index. A strategy's required_weight_override "
    "replaces whichever of these applies to its scope; null/None means the engine's own default "
    "is used unchanged."
)


class ClarificationUnavailableError(Exception):
    """Raised when ANTHROPIC_API_KEY isn't configured, daily budget is exhausted, or call fails."""
    pass


def _describe_config(strategy: Dict[str, Any]) -> str:
    active_pillars = strategy.get("active_pillars", {})
    on = sorted(p for p, enabled in active_pillars.items() if enabled)
    off = sorted(p for p, enabled in active_pillars.items() if not enabled)
    return json.dumps({
        "name": strategy.get("name"),
        "description": strategy.get("description"),
        "target_scope": strategy.get("target_scope"),
        "pillars_active": on,
        "pillars_disabled": off,
        "required_weight_override": strategy.get("required_weight_override"),
        "fundamentals_gate_enabled": strategy.get("fundamentals_gate_enabled"),
        "news_gate_enabled": strategy.get("news_gate_enabled"),
        "auto_paper_trade": strategy.get("auto_paper_trade"),
        "python_code": strategy.get("python_code", ""),
    }, indent=2)


def _generate_fallback_clarification(strategy: Dict[str, Any], correction_note: Optional[str] = None) -> Dict[str, Any]:
    name = strategy.get("name", "Custom Strategy")
    scope_str = ", ".join(strategy.get("target_scope", ["STOCKS"]))
    code = strategy.get("python_code", "")
    
    tp_str = "1.5% profit target"
    sl_str = "0.75% stop loss"
    if "tp_pct" in code:
        tp_str = "Custom TP rule defined in Python code"
    if "sl_pct" in code:
        sl_str = "Custom SL rule defined in Python code"

    summary = f"Strategy '{name}' scans {scope_str} for institutional breakout setups."
    if correction_note:
        summary += f" [User Note Incorporated: {correction_note}]"

    return {
        "entry_conditions": f"Triggers when technical score threshold ({strategy.get('required_weight_override') or 'Default Tier'}) is met on {scope_str}.",
        "exit_conditions": f"Target Profit (TP): {tp_str} | Stop Loss (SL): {sl_str}.",
        "timeframe": "5m Intraday & Scalping / BTST",
        "assumptions": [
            "Assumes sufficient intraday liquidity for instant simulated fills.",
            "Quality gates enforced if enabled; risk strictly capped per position."
        ],
        "target_summary": f"Target universe: {scope_str}.",
        "pillar_summary": f"Active technical pillars: {len([k for k, v in strategy.get('active_pillars', {}).items() if v])} active.",
        "confirmation_bar_summary": f"Confirmation bar weight: {strategy.get('required_weight_override') or 'Engine Default'}.",
        "gate_summary": f"Fundamentals gate: {'ON' if strategy.get('fundamentals_gate_enabled') else 'OFF'}, News gate: {'ON' if strategy.get('news_gate_enabled') else 'OFF'}.",
        "plain_summary": summary,
    }


def generate_clarification(strategy: Dict[str, Any], correction_note: Optional[str] = None) -> Dict[str, Any]:
    """Returns the structured clarification dict matching _CLARIFICATION_TOOL's schema."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.info("ANTHROPIC_API_KEY not set — using structured rules analyzer fallback.")
        return _generate_fallback_clarification(strategy, correction_note)

    try:
        check_and_increment_budget()
    except ClarificationBudgetExceededError as e:
        logger.warning(f"Clarification budget exceeded: {e} — falling back to rules analyzer.")
        return _generate_fallback_clarification(strategy, correction_note)

    client = anthropic.Anthropic(api_key=api_key)

    prompt = (
        "Read this trading strategy's configuration and Python code, then produce a structured clarification "
        "of what it does — entry conditions, exit conditions (TP/SL rules), target timeframe, assumptions, and plain summary.\n\n"
        f"{_ENGINE_DEFAULTS_CONTEXT}\n\n"
        f"Strategy configuration & code:\n```json\n{_describe_config(strategy)}\n```"
    )
    if correction_note:
        prompt += (
            "\n\nA previous clarification attempt was reviewed by the author with this correction: \"" + correction_note + "\"\n"
            "Produce a revised, accurate clarification incorporating this correction."
        )

    try:
        response = client.messages.create(
            model=CLARIFICATION_MODEL,
            max_tokens=2000,
            tools=[_CLARIFICATION_TOOL],
            tool_choice={"type": "tool", "name": "record_strategy_clarification"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "record_strategy_clarification":
                return block.input
    except Exception as e:
        logger.warning(f"Claude API call failed ({e}) — returning fallback clarification.")
        return _generate_fallback_clarification(strategy, correction_note)

    return _generate_fallback_clarification(strategy, correction_note)

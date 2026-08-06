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
    "description": "Record a structured, plain-language clarification of what a trading strategy's pillar/scope/gate configuration actually does.",
    "input_schema": {
        "type": "object",
        "properties": {
            "target_summary": {"type": "string", "description": "Plain-language description of exactly which instruments/universes this strategy scans (stocks, and/or which specific indices)."},
            "pillar_summary": {"type": "string", "description": "Which technical pillars are active vs disabled for this strategy's scope, and what disabling them means for how strict or loose its signals will be compared to using every pillar."},
            "confirmation_bar_summary": {"type": "string", "description": "How the strategy's confirmation-weight bar compares to the engine's own default for its scope (stricter, looser, or unchanged) — state the actual numbers."},
            "gate_summary": {"type": "string", "description": "Whether the fundamentals and news quality gates are on or off, and what that implies for risk (a gate can only cap conviction, never manufacture it, so turning one off removes a safety check, it doesn't add aggression by itself)."},
            "assumptions": {"type": "array", "items": {"type": "string"}, "description": "Any non-obvious implication of this specific combination of settings — e.g. a very loose confirmation bar combined with both gates off, or a scope that includes an index whose pillars are mostly disabled."},
            "plain_summary": {"type": "string", "description": "A 2-4 sentence plain-language summary of what this strategy will actually do differently from the Default 5-Pillar strategy, for a trader (not a programmer) to confirm at a glance."},
        },
        "required": ["target_summary", "pillar_summary", "confirmation_bar_summary", "gate_summary", "assumptions", "plain_summary"],
    },
}

# Context the model needs to judge "stricter/looser than default" — these mirror the real
# constants in scoring_engine.py (liquidity-tiered) and index_scoring.py (fixed), restated here
# rather than imported, since this module intentionally has no dependency on the scoring
# engines themselves (same "controls the engine, doesn't reimplement it" boundary
# strategy_manager.py's own docstring describes).
_ENGINE_DEFAULTS_CONTEXT = (
    "Engine defaults for context: stock confirmation bar is liquidity-tiered — TIER_1 "
    "(large-cap/liquid) needs 3.0 confirmed pillar weight, TIER_2 needs 4.0. Index confirmation "
    "bar is fixed at 2.0 regardless of which index. A strategy's required_weight_override "
    "replaces whichever of these applies to its scope; null/None means the engine's own default "
    "is used unchanged."
)


class ClarificationUnavailableError(Exception):
    """Raised when ANTHROPIC_API_KEY isn't configured, the daily budget is exhausted, or the
    API call itself fails — callers should surface this as a clear, catchable error, never
    silently skip clarification and let a strategy go active unconfirmed."""
    pass


def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ClarificationUnavailableError(
            "ANTHROPIC_API_KEY is not set — add it to .env (see .env.example) to enable strategy "
            "clarification. A strategy cannot be created/edited without it, since clarification is "
            "the gate that stops an unconfirmed configuration from going active."
        )
    return anthropic.Anthropic(api_key=api_key)


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
    }, indent=2)


def generate_clarification(strategy: Dict[str, Any], correction_note: Optional[str] = None) -> Dict[str, Any]:
    """Returns the structured clarification dict (matching _CLARIFICATION_TOOL's schema).
    Pass correction_note when re-running after the user said the previous summary was wrong —
    it's sent alongside the ORIGINAL config so Claude revises against the real settings, not
    just the user's restated understanding of them."""
    try:
        check_and_increment_budget()
    except ClarificationBudgetExceededError as e:
        raise ClarificationUnavailableError(str(e))

    client = _get_client()

    prompt = (
        "Read this trading strategy's configuration and produce a structured clarification of "
        "exactly what it does — which instruments it scans, which technical pillars are active "
        "vs disabled and what that means, how its confirmation-weight bar compares to the "
        "engine's default, whether the fundamentals/news quality gates are on, and any "
        "non-obvious implication of this specific combination. Be precise and grounded in the "
        "actual configuration, not a generic description.\n\n"
        f"{_ENGINE_DEFAULTS_CONTEXT}\n\n"
        f"Strategy configuration:\n```json\n{_describe_config(strategy)}\n```"
    )
    if correction_note:
        prompt += (
            "\n\nA previous clarification attempt was shown to the strategy's author, who said it "
            "was WRONG with this correction: \"" + correction_note + "\"\n"
            "Re-read the configuration with this correction in mind and produce a revised, accurate "
            "clarification. If the correction contradicts what the configuration actually does, side "
            "with the configuration — note the discrepancy in `assumptions` rather than describing "
            "something the settings don't actually do."
        )

    try:
        response = client.messages.create(
            model=CLARIFICATION_MODEL,
            max_tokens=2000,
            tools=[_CLARIFICATION_TOOL],
            tool_choice={"type": "tool", "name": "record_strategy_clarification"},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        raise ClarificationUnavailableError(f"Claude API call failed: {e}")

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_strategy_clarification":
            return block.input

    raise ClarificationUnavailableError("Claude did not return the expected structured clarification.")

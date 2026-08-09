"""
STRATEGY MANAGER — user-defined, CRUD-able trading strategies
================================================================
A Strategy is a named configuration applied on top of the existing scoring engines
(scoring_engine.evaluate_5_pillar_matrix for stocks, index_scoring.evaluate_index_signal for
indices) — it does NOT reimplement scoring. It controls:

- target_scope: which universe(s) the strategy scans (STOCKS / NIFTY50 / BANKNIFTY / SENSEX)
- active_pillars: which of the underlying pillars count toward this strategy's score
- required_weight_override: a custom confirmation-weight bar (None = use the engine's own
  tier-based / index default)
- fundamentals_gate_enabled / news_gate_enabled: whether those quality gates apply
- auto_paper_trade: whether live signals from this strategy get logged as simulated
  (paper/dry-run) trades — see execution_provider.py. Never places a real order.

Disabling a pillar reuses the SAME injection point the auto-improving weights already use
(pillar_weight_multipliers) — a disabled pillar just gets multiplier 0.0, an enabled one gets
its current dynamic weight (or 1.0 default). No changes needed to the scoring engines' pillar
logic itself, only to what gets multiplied in.

Every strategy's outcomes are tracked separately in the signal journal (strategy_id column)
so each one shows its own win rate / accuracy, not a blended average.
"""

import os
import json
import uuid
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from json_utils import atomic_write_json, read_json, json_file_lock
from clarification_service import generate_clarification, ClarificationUnavailableError
from env_utils import DATA_DIR
from pg_utils import USE_POSTGRES, pg_read_json, pg_write_json, pg_key_lock

logger = logging.getLogger("StrategyManager")

STRATEGIES_FILE = os.path.join(DATA_DIR, "strategies.json")

STOCK_PILLAR_NAMES = [
    "Pillar 1: Futures OI",
    "Pillar 2: Vol Persistence",
    "Pillar 3: Relative Strength",
    "Pillar 4: Volume Spike",
    "Pillar 5: Marubozu Close",
    "Pillar 6: Institutional Flow",
]

INDEX_PILLAR_NAMES = [
    "Index: Marubozu Close",
    "Index: Relative Strength",
    "Index: Global Cues",
    "Index: Macro News",
    "Index: Derivatives Positioning",
    "Index: Greeks Outlook",
]

ALL_PILLAR_NAMES = STOCK_PILLAR_NAMES + INDEX_PILLAR_NAMES

VALID_SCOPES = {"STOCKS", "NIFTY50", "BANKNIFTY", "SENSEX"}

DEFAULT_STRATEGY_ID = "default-5-pillar"

# The fields _compute_config_hash treats as "what the strategy actually does" — the same set
# that the built-in strategy's configuration must stay fixed on (see update_strategy).
CONFIG_FIELDS = {
    "target_scope", "active_pillars", "required_weight_override",
    "fundamentals_gate_enabled", "news_gate_enabled", "python_code",
}


def _validate_required_weight_override(value: Optional[float]):
    """A confirmation-weight bar of 0 or negative would make `confirmed_pillars_weight >=
    required_weight_override` always true, silently defeating the confirmation gate entirely
    for that strategy. target_scope/active_pillars already get this kind of validation; this
    field previously had none."""
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"required_weight_override must be a positive number or None, got {value!r}.")
    if not (value > 0):
        raise ValueError(f"required_weight_override must be greater than 0, got {value!r}.")


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_all() -> Dict[str, Any]:
    if USE_POSTGRES:
        return pg_read_json("strategies", default={})
    return read_json(STRATEGIES_FILE, default={})


def _save_all(store: Dict[str, Any]):
    if USE_POSTGRES:
        pg_write_json("strategies", store)
        return
    _ensure_data_dir()
    atomic_write_json(STRATEGIES_FILE, store)


def _state_lock():
    """Cross-process lock when shared via Postgres, in-process-only lock otherwise — see
    pg_utils.py's module docstring for why json_file_lock alone isn't enough once a second
    process (e.g. a Vercel instance) can write strategies.json's Postgres-backed equivalent."""
    return pg_key_lock("strategies") if USE_POSTGRES else json_file_lock(STRATEGIES_FILE)


def _compute_config_hash(strategy: Dict[str, Any]) -> str:
    """Stable hash of the fields that actually change what a strategy DOES — scope, pillars,
    confirmation bar, gates, python_code — never name/description/auto_paper_trade/is_active/scope_toggles."""
    meaningful = {
        "target_scope": sorted(strategy.get("target_scope", [])),
        "active_pillars": dict(sorted(strategy.get("active_pillars", {}).items())),
        "required_weight_override": strategy.get("required_weight_override"),
        "fundamentals_gate_enabled": strategy.get("fundamentals_gate_enabled"),
        "news_gate_enabled": strategy.get("news_gate_enabled"),
        "python_code": (strategy.get("python_code") or "").strip(),
    }
    normalized = json.dumps(meaningful, sort_keys=True)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _ensure_clarification_field(strategy: Dict[str, Any]) -> Dict[str, Any]:
    """Grandfathers in strategies that existed before the clarification gate was added —
    never retroactively deactivates or blocks something that was already running."""
    if "scope_toggles" not in strategy:
        scope = strategy.get("target_scope", ["STOCKS", "NIFTY50", "BANKNIFTY", "SENSEX"])
        strategy["scope_toggles"] = {
            "stocks": "STOCKS" in scope,
            "indices": any(idx in scope for idx in ["NIFTY50", "BANKNIFTY", "SENSEX"]),
        }
    if "python_code" not in strategy:
        strategy["python_code"] = (
            "# AlgoTrader Python Strategy Logic\n"
            "# Defines entry and exit rules for scanning\n"
            "def evaluate_signal(df, pillars_matrix):\n"
            "    # Standard 5-pillar confirmation gate\n"
            "    score = sum(pillars_matrix.values())\n"
            "    if score >= 3.0:\n"
            "        return {'signal': 'BTST_BUY', 'tp_pct': 1.5, 'sl_pct': 0.75}\n"
            "    return {'signal': 'NEUTRAL'}\n"
        )
    if "clarification" not in strategy:
        strategy["clarification"] = {
            "confirmed": True,
            "confirmed_at": strategy.get("created_at"),
            "auto_confirmed_reason": "Existing strategy — grandfathered in when the AI clarification gate was added.",
        }
    if "config_hash" not in strategy:
        strategy["config_hash"] = _compute_config_hash(strategy)
    return strategy


def _seed_default_strategy_if_missing():
    """
    The original hardcoded behavior (every pillar active, tier-based thresholds, both gates
    on) is preserved as a real strategy — DEFAULT_STRATEGY_ID — so existing behavior doesn't
    silently change for anyone who doesn't touch the strategy system at all. Pre-confirmed —
    it's the documented original behavior, not a user-authored configuration, so there's
    nothing to clarify and no reason to spend a real API call seeding it on first run.
    """
    # M8 audit fix: read-check-write, wrapped so two threads racing this at startup can't both
    # pass the "missing" check and both write (harmless duplicate work today, but the same
    # pattern as every other read-modify-write in this file, kept consistent).
    with _state_lock():
        store = _load_all()
        now = datetime.now(timezone.utc).isoformat()
        needs_save = False

        if DEFAULT_STRATEGY_ID not in store:
            strategy = {
                "id": DEFAULT_STRATEGY_ID,
                "name": "Default 5-Pillar",
                "description": "The original scanner behavior: every pillar active, liquidity-tiered "
                                "thresholds for stocks, both fundamentals and news gates on.",
                "target_scope": ["STOCKS", "NIFTY50", "BANKNIFTY", "SENSEX"],
                "active_pillars": {p: True for p in ALL_PILLAR_NAMES},
                "required_weight_override": None,
                "fundamentals_gate_enabled": True,
                "news_gate_enabled": True,
                "auto_paper_trade": False,
                "is_active": True,
                "is_builtin": True,
                "clarification": {
                    "confirmed": True,
                    "confirmed_at": now,
                    "target_summary": "Every tracked stock plus Nifty 50, Bank Nifty, and Sensex.",
                    "pillar_summary": "All 5 stock pillars and all 6 index pillars active — no pillar disabled.",
                    "confirmation_bar_summary": "Engine defaults unchanged: liquidity-tiered for stocks (3.0/4.0), fixed 2.0 for indices.",
                    "gate_summary": "Both the fundamentals and news quality gates are on.",
                    "assumptions": [],
                    "plain_summary": "The baseline scanner behavior every custom strategy is compared against — nothing disabled, nothing loosened.",
                    "auto_confirmed_reason": "Built-in default strategy — matches the original scanner behavior exactly, no clarification needed.",
                },
                "created_at": now,
                "updated_at": now,
            }
            strategy["config_hash"] = _compute_config_hash(strategy)
            store[DEFAULT_STRATEGY_ID] = strategy
            needs_save = True

        smc_id = "smc-institutional-v1"
        smc_code = (
            "# AlgoTrader Python Strategy Logic\n"
            "# SMC (Smart Money Concepts): structure shift + order block/FVG + liquidity sweep confirmation\n\n"
            "from smc_helpers import (\n"
            "    detect_market_structure,\n"
            "    detect_liquidity_sweep,\n"
            "    find_nearest_order_block,\n"
            "    find_nearest_fvg,\n"
            "    premium_discount_zone,\n"
            "    check_inducement_cleared,\n"
            "    next_opposing_liquidity_pool,\n"
            "    distance_pct\n"
            ")\n\n"
            "def evaluate_signal(df, pillars_matrix=None):\n"
            "    combine_with_pillars = False\n"
            "    structure = detect_market_structure(df)\n"
            "    swept = detect_liquidity_sweep(df)\n"
            "    ob_zone = find_nearest_order_block(df, direction=structure)\n"
            "    fvg_zone = find_nearest_fvg(df, direction=structure)\n"
            "    zone_state = premium_discount_zone(df)\n"
            "    inducement_clear = check_inducement_cleared(df)\n"
            "    signal = None\n"
            "    entry = tp_pct = sl_pct = None\n"
            "    if structure in ('bullish_bos', 'bullish_choch') and swept == 'sell_side_swept' \\\n"
            "       and zone_state == 'discount' and inducement_clear and (ob_zone or fvg_zone):\n"
            "        entry_zone = ob_zone or fvg_zone\n"
            "        signal = 'BTST_BUY'\n"
            "        entry = entry_zone['level']\n"
            "        sl_pct = distance_pct(entry, entry_zone['invalidation'])\n"
            "        tp_pct = distance_pct(entry, next_opposing_liquidity_pool(df))\n"
            "    elif structure in ('bearish_bos', 'bearish_choch') and swept == 'buy_side_swept' \\\n"
            "         and zone_state == 'premium' and inducement_clear and (ob_zone or fvg_zone):\n"
            "        entry_zone = ob_zone or fvg_zone\n"
            "        signal = 'STBT_SELL'\n"
            "        entry = entry_zone['level']\n"
            "        sl_pct = distance_pct(entry, entry_zone['invalidation'])\n"
            "        tp_pct = distance_pct(entry, next_opposing_liquidity_pool(df))\n"
            "    if signal is None:\n"
            "        return None\n"
            "    if combine_with_pillars and pillars_matrix:\n"
            "        score = sum(pillars_matrix.values())\n"
            "        if score < 3.0:\n"
            "            return None\n"
            "    return {\n"
            "        'signal': signal,\n"
            "        'entry': entry,\n"
            "        'tp_pct': tp_pct,\n"
            "        'sl_pct': sl_pct,\n"
            "        'reason': f'{structure} + {swept} + {zone_state} zone, OB/FVG confirmed'\n"
            "    }\n"
        )
        if smc_id not in store or not store[smc_id].get("python_code"):
            smc_strat = {
                "id": smc_id,
                "name": "SMC (Smart Money Concepts)",
                "description": "Detects institutional order flow via market structure shifts, order blocks, fair value gaps, and liquidity sweeps — entries taken at premium/discount extremes with sweep confirmation.",
                "target_scope": ["STOCKS", "NIFTY50", "BANKNIFTY", "SENSEX"],
                "active_pillars": {p: True for p in ALL_PILLAR_NAMES},
                "required_weight_override": None,
                "fundamentals_gate_enabled": True,
                "news_gate_enabled": True,
                "auto_paper_trade": False,
                "is_active": True,
                "is_builtin": False,
                "scope_toggles": {"stocks": False, "indices": False},
                "python_code": smc_code,
                "clarification": {
                    "confirmed": True,
                    "confirmed_at": now,
                    "target_summary": "Stocks Intraday/Scalping and Index Options (Nifty/BankNifty/Sensex).",
                    "pillar_summary": "SMC Structure Shifts (BOS/CHoCH), OB/FVG, Liquidity Sweeps, and OTE retracements.",
                    "confirmation_bar_summary": "High-conviction SMC entry filters.",
                    "gate_summary": "Both fundamentals and news gates enabled.",
                    "assumptions": [],
                    "plain_summary": "Detects institutional order block re-entries, FVG fills, and liquidity sweeps.",
                    "auto_confirmed_reason": "Custom SMC strategy card.",
                },
                "created_at": now,
                "updated_at": now,
            }
            smc_strat["config_hash"] = _compute_config_hash(smc_strat)
            store[smc_id] = smc_strat
            needs_save = True

        # Intraday Strategy Engine (strategy_engine.py) — 6 rule-based options-alert
        # strategies (spec: VWAP Pullback / Breakdown Spike / ORB / OI Surge / Death Cross /
        # Volatility Straddle). These are pure on/off toggle registrations, not python_code-
        # driven pillar strategies — strategy_engine.py calls strategy_engine_rules.py
        # directly and only reads scope_toggles/is_active from here (same check
        # smc_scanner.is_smc_scope_enabled does for smc-institutional-v1 above). Default ON
        # for every applicable scope, per the spec ("Default: All strategies ON").
        intraday_specs = [
            ("vwap-pullback-v1", "VWAP Pullback", "Buy Call on a bullish pullback to VWAP/EMA with an RSI reversal above 50.",
             ["NIFTY50", "BANKNIFTY", "SENSEX"], {"stocks": False, "indices": True}),
            ("breakdown-spike-v1", "Breakdown Spike", "Buy Put on a range breakdown confirmed by a 1.5x volume spike.",
             ["NIFTY50", "BANKNIFTY", "SENSEX"], {"stocks": False, "indices": True}),
            ("orb-v1", "ORB", "Opening Range Breakout — Buy Call/Put on a break of the first 30 minutes' high/low.",
             ["NIFTY50", "BANKNIFTY", "SENSEX"], {"stocks": False, "indices": True}),
            ("oi-surge-v1", "OI Surge", "Buy 1-strike-OTM Call on a 15-min price surge with long OI build-up.",
             ["STOCKS"], {"stocks": True, "indices": False}),
            ("death-cross-v1", "Death Cross", "Buy ATM Put on a 15-min 5/20 EMA death cross with short OI build-up.",
             ["STOCKS"], {"stocks": True, "indices": False}),
            ("volatility-straddle-v1", "Volatility Straddle", "Buy ATM Call + Put ahead of a high-impact event when IV is in its low percentile. Sensex excluded — no live options data source exists for it.",
             ["STOCKS", "NIFTY50", "BANKNIFTY"], {"stocks": True, "indices": True}),
        ]
        for strat_id, strat_name, desc, target_scope, scope_toggles in intraday_specs:
            if strat_id in store:
                continue
            strat = {
                "id": strat_id,
                "name": strat_name,
                "description": desc,
                "target_scope": target_scope,
                "active_pillars": {p: True for p in ALL_PILLAR_NAMES},
                "required_weight_override": None,
                "fundamentals_gate_enabled": True,
                "news_gate_enabled": True,
                "auto_paper_trade": False,
                "is_active": True,
                "is_builtin": True,
                "scope_toggles": scope_toggles,
                "clarification": {
                    "confirmed": True,
                    "confirmed_at": now,
                    "target_summary": ", ".join(target_scope),
                    "pillar_summary": "Rule-based condition chain (strategy_engine_rules.py), not the pillar matrix.",
                    "confirmation_bar_summary": "Fixed rule conditions from the intraday Strategy Engine spec.",
                    "gate_summary": "Fundamentals/news gates not applicable — this is an intraday rule engine, not the BTST pillar model.",
                    "assumptions": [],
                    "plain_summary": desc,
                    "auto_confirmed_reason": "Built-in intraday Strategy Engine strategy — no clarification needed.",
                },
                "created_at": now,
                "updated_at": now,
            }
            strat["config_hash"] = _compute_config_hash(strat)
            store[strat_id] = strat
            needs_save = True

        if needs_save:
            _save_all(store)


def list_strategies(active_only: bool = False) -> List[Dict[str, Any]]:
    _seed_default_strategy_if_missing()
    store = _load_all()
    strategies = [_ensure_clarification_field(s) for s in store.values()]
    if active_only:
        strategies = [s for s in strategies if s.get("is_active", True)]
    return sorted(strategies, key=lambda s: s.get("created_at", ""))


def get_strategy(strategy_id: str) -> Optional[Dict[str, Any]]:
    _seed_default_strategy_if_missing()
    strategy = _load_all().get(strategy_id)
    return _ensure_clarification_field(strategy) if strategy is not None else None


def create_strategy_draft(
    name: str,
    description: str = "",
    target_scope: Optional[List[str]] = None,
    active_pillars: Optional[Dict[str, bool]] = None,
    required_weight_override: Optional[float] = None,
    fundamentals_gate_enabled: bool = True,
    news_gate_enabled: bool = True,
    auto_paper_trade: bool = False,
    python_code: Optional[str] = None,
    scope_toggles: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    """Add flow: validate the config, generate an AI clarification of what it actually does,
    and store it as an unconfirmed draft — is_active stays False until confirm_strategy() runs."""
    _seed_default_strategy_if_missing()

    if not name or not name.strip():
        raise ValueError("Strategy name is required.")

    scope = target_scope or ["STOCKS"]
    invalid_scopes = set(scope) - VALID_SCOPES
    if invalid_scopes:
        raise ValueError(f"Invalid target_scope values: {sorted(invalid_scopes)}. Must be from {sorted(VALID_SCOPES)}.")

    _validate_required_weight_override(required_weight_override)

    pillars = {p: True for p in ALL_PILLAR_NAMES}
    if active_pillars:
        unknown = set(active_pillars.keys()) - set(ALL_PILLAR_NAMES)
        if unknown:
            raise ValueError(f"Unknown pillar names: {sorted(unknown)}.")
        pillars.update(active_pillars)

    toggles = scope_toggles or {
        "stocks": "STOCKS" in scope,
        "indices": any(idx in scope for idx in ["NIFTY50", "BANKNIFTY", "SENSEX"]),
    }

    code = (python_code or "").strip() or (
        "# AlgoTrader Python Strategy Logic\n"
        "# Defines entry and exit rules for scanning\n"
        "def evaluate_signal(df, pillars_matrix):\n"
        "    score = sum(pillars_matrix.values())\n"
        "    if score >= 3.0:\n"
        "        return {'signal': 'BTST_BUY', 'tp_pct': 1.5, 'sl_pct': 0.75}\n"
        "    return {'signal': 'NEUTRAL'}\n"
    )

    strategy_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    strategy = {
        "id": strategy_id,
        "name": name.strip(),
        "description": description.strip(),
        "target_scope": scope,
        "active_pillars": pillars,
        "required_weight_override": required_weight_override,
        "fundamentals_gate_enabled": fundamentals_gate_enabled,
        "news_gate_enabled": news_gate_enabled,
        "auto_paper_trade": auto_paper_trade,
        "python_code": code,
        "scope_toggles": toggles,
        "is_active": False,
        "is_builtin": False,
        "created_at": now,
        "updated_at": now,
    }
    strategy["config_hash"] = _compute_config_hash(strategy)

    clarification = generate_clarification(strategy)  # raises ClarificationUnavailableError
    clarification.update({"confirmed": False, "confirmed_at": None})
    strategy["clarification"] = clarification

    with _state_lock():
        store = _load_all()
        store[strategy_id] = strategy
        _save_all(store)
    logger.info(f"Strategy draft created: {strategy_id} ({name})")
    return strategy


def resubmit_clarification(strategy_id: str, correction_note: str) -> Dict[str, Any]:
    """Free-text correction loop: re-send the ORIGINAL config + the user's correction to
    Claude, replacing the stored (still-unconfirmed) clarification."""
    store = _load_all()
    if strategy_id not in store:
        raise KeyError(f"Strategy {strategy_id} not found.")
    strategy = _ensure_clarification_field(store[strategy_id])
    if strategy["clarification"].get("confirmed"):
        raise ValueError("This strategy is already confirmed — edit its configuration to trigger re-clarification instead.")

    clarification = generate_clarification(strategy, correction_note=correction_note)

    with _state_lock():
        store = _load_all()
        if strategy_id not in store:
            raise KeyError(f"Strategy {strategy_id} not found.")
        strategy = _ensure_clarification_field(store[strategy_id])
        clarification.update({"confirmed": False, "confirmed_at": None})
        strategy["clarification"] = clarification
        strategy["updated_at"] = datetime.now(timezone.utc).isoformat()
        store[strategy_id] = strategy
        _save_all(store)
    return strategy


def confirm_strategy(strategy_id: str) -> Dict[str, Any]:
    """User accepted the clarification — confirms it and activates the strategy."""
    with _state_lock():
        store = _load_all()
        if strategy_id not in store:
            raise KeyError(f"Strategy {strategy_id} not found.")
        strategy = _ensure_clarification_field(store[strategy_id])
        if "clarification" not in strategy:
            raise ValueError(f"Strategy {strategy_id} has no pending clarification to confirm.")

        strategy["clarification"]["confirmed"] = True
        strategy["clarification"]["confirmed_at"] = datetime.now(timezone.utc).isoformat()
        strategy["is_active"] = True
        strategy["updated_at"] = datetime.now(timezone.utc).isoformat()
        store[strategy_id] = strategy
        _save_all(store)
    logger.info(f"Strategy confirmed and activated: {strategy_id}")
    return strategy


def update_strategy(strategy_id: str, **fields) -> Dict[str, Any]:
    """Update flow for a strategy."""
    with _state_lock():
        store = _load_all()
        if strategy_id not in store:
            raise KeyError(f"Strategy {strategy_id} not found.")

        strategy = _ensure_clarification_field(store[strategy_id])
        if strategy.get("is_builtin"):
            if fields.get("is_active") is False:
                raise ValueError("The built-in Default 5-Pillar strategy can be edited but not deactivated.")
            attempted_config_change = CONFIG_FIELDS & {k for k, v in fields.items() if v is not None}
            if attempted_config_change:
                raise ValueError(
                    "The built-in Default 5-Pillar strategy's scoring configuration "
                    f"({sorted(attempted_config_change)}) cannot be changed."
                )

        requested_active = fields.pop("is_active", None)

        editable_fields = {
            "name", "description", "target_scope", "active_pillars",
            "required_weight_override", "fundamentals_gate_enabled", "news_gate_enabled",
            "auto_paper_trade", "python_code", "scope_toggles",
        }
        old_hash = strategy["config_hash"]

        for key, value in fields.items():
            if key not in editable_fields:
                continue
            if key == "target_scope" and value is not None:
                invalid_scopes = set(value) - VALID_SCOPES
                if invalid_scopes:
                    raise ValueError(f"Invalid target_scope values: {sorted(invalid_scopes)}.")
            if key == "active_pillars" and value is not None:
                unknown = set(value.keys()) - set(ALL_PILLAR_NAMES)
                if unknown:
                    raise ValueError(f"Unknown pillar names: {sorted(unknown)}.")
                merged = dict(strategy.get("active_pillars", {}))
                merged.update(value)
                value = merged
            if key == "required_weight_override":
                _validate_required_weight_override(value)
            if key == "scope_toggles" and isinstance(value, dict):
                merged_toggles = dict(strategy.get("scope_toggles", {"stocks": True, "indices": True}))
                merged_toggles.update(value)
                value = merged_toggles
            strategy[key] = value

        new_hash = _compute_config_hash(strategy)
        config_changed = new_hash != old_hash
        strategy["config_hash"] = new_hash

        if config_changed and not strategy.get("is_builtin"):
            clarification = generate_clarification(strategy)
            clarification.update({"confirmed": False, "confirmed_at": None})
            strategy["clarification"] = clarification
            strategy["is_active"] = False
            logger.info(f"Strategy {strategy_id} config changed — re-clarification required, deactivated.")

        if requested_active is True:
            if not strategy["clarification"].get("confirmed", False) and not strategy.get("is_builtin"):
                raise ValueError("This strategy isn't confirmed yet — confirm its clarification before activating it.")
            strategy["is_active"] = True
        elif requested_active is False:
            strategy["is_active"] = False

        strategy["updated_at"] = datetime.now(timezone.utc).isoformat()
        store[strategy_id] = strategy
        _save_all(store)
    logger.info(f"Strategy updated: {strategy_id}")
    return strategy


def delete_strategy(strategy_id: str):
    with _state_lock():
        store = _load_all()
        if strategy_id not in store:
            raise KeyError(f"Strategy {strategy_id} not found.")
        if store[strategy_id].get("is_builtin"):
            raise ValueError("The built-in Default 5-Pillar strategy cannot be deleted — deactivate custom strategies instead, or edit this one.")
        del store[strategy_id]
        _save_all(store)
    logger.info(f"Strategy deleted: {strategy_id}")


def compute_effective_pillar_multipliers(
    strategy: Dict[str, Any],
    base_dynamic_weights: Dict[str, float]
) -> Dict[str, float]:
    """
    Combine a strategy's pillar on/off toggles with the current auto-improved dynamic
    weights: disabled -> 0.0 (fully suppressed), enabled -> whatever the dynamic weight
    currently is (defaults to 1.0 until the auto-improve system has earned a change).
    This is passed straight into evaluate_5_pillar_matrix / evaluate_index_signal's
    pillar_weight_multipliers parameter — no scoring-engine changes needed.
    """
    active_pillars = strategy.get("active_pillars", {})
    effective = {}
    for pillar_name in ALL_PILLAR_NAMES:
        is_enabled = active_pillars.get(pillar_name, True)
        effective[pillar_name] = base_dynamic_weights.get(pillar_name, 1.0) if is_enabled else 0.0
    return effective

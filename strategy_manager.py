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
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from json_utils import atomic_write_json, read_json

logger = logging.getLogger("StrategyManager")

DATA_DIR = "data"
STRATEGIES_FILE = os.path.join(DATA_DIR, "strategies.json")

STOCK_PILLAR_NAMES = [
    "Pillar 1: Futures OI",
    "Pillar 2: Vol Persistence",
    "Pillar 3: Relative Strength",
    "Pillar 4: Volume Spike",
    "Pillar 5: Marubozu Close",
]

INDEX_PILLAR_NAMES = [
    "Index: Marubozu Close",
    "Index: Relative Strength",
    "Index: Global Cues",
    "Index: Macro News",
]

ALL_PILLAR_NAMES = STOCK_PILLAR_NAMES + INDEX_PILLAR_NAMES

VALID_SCOPES = {"STOCKS", "NIFTY50", "BANKNIFTY", "SENSEX"}

DEFAULT_STRATEGY_ID = "default-5-pillar"


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_all() -> Dict[str, Any]:
    return read_json(STRATEGIES_FILE, default={})


def _save_all(store: Dict[str, Any]):
    _ensure_data_dir()
    atomic_write_json(STRATEGIES_FILE, store)


def _seed_default_strategy_if_missing():
    """
    The original hardcoded behavior (every pillar active, tier-based thresholds, both gates
    on) is preserved as a real strategy — DEFAULT_STRATEGY_ID — so existing behavior doesn't
    silently change for anyone who doesn't touch the strategy system at all.
    """
    store = _load_all()
    if DEFAULT_STRATEGY_ID in store:
        return
    now = datetime.now(timezone.utc).isoformat()
    store[DEFAULT_STRATEGY_ID] = {
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
        "created_at": now,
        "updated_at": now,
    }
    _save_all(store)


def list_strategies(active_only: bool = False) -> List[Dict[str, Any]]:
    _seed_default_strategy_if_missing()
    store = _load_all()
    strategies = list(store.values())
    if active_only:
        strategies = [s for s in strategies if s.get("is_active", True)]
    return sorted(strategies, key=lambda s: s.get("created_at", ""))


def get_strategy(strategy_id: str) -> Optional[Dict[str, Any]]:
    _seed_default_strategy_if_missing()
    return _load_all().get(strategy_id)


def create_strategy(
    name: str,
    description: str = "",
    target_scope: Optional[List[str]] = None,
    active_pillars: Optional[Dict[str, bool]] = None,
    required_weight_override: Optional[float] = None,
    fundamentals_gate_enabled: bool = True,
    news_gate_enabled: bool = True,
    auto_paper_trade: bool = False,
) -> Dict[str, Any]:
    _seed_default_strategy_if_missing()

    if not name or not name.strip():
        raise ValueError("Strategy name is required.")

    scope = target_scope or ["STOCKS"]
    invalid_scopes = set(scope) - VALID_SCOPES
    if invalid_scopes:
        raise ValueError(f"Invalid target_scope values: {sorted(invalid_scopes)}. Must be from {sorted(VALID_SCOPES)}.")

    pillars = {p: True for p in ALL_PILLAR_NAMES}
    if active_pillars:
        unknown = set(active_pillars.keys()) - set(ALL_PILLAR_NAMES)
        if unknown:
            raise ValueError(f"Unknown pillar names: {sorted(unknown)}.")
        pillars.update(active_pillars)

    store = _load_all()
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
        "is_active": True,
        "is_builtin": False,
        "created_at": now,
        "updated_at": now,
    }
    store[strategy_id] = strategy
    _save_all(store)
    logger.info(f"Strategy created: {strategy_id} ({name})")
    return strategy


def update_strategy(strategy_id: str, **fields) -> Dict[str, Any]:
    store = _load_all()
    if strategy_id not in store:
        raise KeyError(f"Strategy {strategy_id} not found.")

    strategy = store[strategy_id]
    if strategy.get("is_builtin") and fields.get("is_active") is False:
        raise ValueError("The built-in Default 5-Pillar strategy can be edited but not deactivated.")

    editable_fields = {
        "name", "description", "target_scope", "active_pillars",
        "required_weight_override", "fundamentals_gate_enabled",
        "news_gate_enabled", "auto_paper_trade", "is_active",
    }
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
        strategy[key] = value

    strategy["updated_at"] = datetime.now(timezone.utc).isoformat()
    store[strategy_id] = strategy
    _save_all(store)
    logger.info(f"Strategy updated: {strategy_id}")
    return strategy


def delete_strategy(strategy_id: str):
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

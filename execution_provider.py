"""
EXECUTION PROVIDER — generic broker adapter, PAPER MODE ONLY
================================================================
This module exists to let a strategy be marked "auto_paper_trade" and have its live signals
turn into a simulated order trail with entry/exit tracking — WITHOUT ever touching a real
broker or moving real money. That's not a partial implementation waiting to be finished; it's
the deliberate scope for this pass (see the project's own design notes on why):

  - Placing real orders in India requires SEBI's retail algo-trading framework (effective Feb
    2025): exchange-empanelled Algo IDs and broker-level registration. An app cannot legally
    fire live retail algo orders through a generic broker API key without that in place.
  - EXECUTION_MODE below is hardcoded to "PAPER". There is no code path in this file that
    calls a real broker network endpoint — going live means writing a new BrokerAdapter
    subclass (e.g. ZerodhaKiteAdapter) that plugs into place_order(), and deliberately
    swapping the mode, once real credentials + registration are actually in place. Nothing
    here does that swap automatically.

Every simulated order is persisted to data/paper_trades.json so paper performance can be
reviewed the same way real fills would be.
"""

import os
import uuid
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from json_utils import atomic_write_json, read_json

logger = logging.getLogger("ExecutionProvider")

DATA_DIR = "data"
PAPER_TRADES_FILE = os.path.join(DATA_DIR, "paper_trades.json")

EXECUTION_MODE = "PAPER"  # the only mode this file implements — see module docstring
DEFAULT_QUANTITY = 1  # placeholder lot size; no risk/position-sizing input exists yet


class BrokerAdapter(ABC):
    """Generic interface a real broker integration would implement. PaperBrokerAdapter below
    is the only concrete implementation shipped — it never calls a network endpoint."""

    @abstractmethod
    def place_order(self, symbol: str, action: str, instrument_type: str, quantity: int) -> Dict[str, Any]:
        ...


class PaperBrokerAdapter(BrokerAdapter):
    """Simulates an order fill. No network call, no real broker, no real money — logs what
    would have been placed."""

    def place_order(self, symbol: str, action: str, instrument_type: str, quantity: int) -> Dict[str, Any]:
        order_id = f"PAPER-{uuid.uuid4().hex[:10]}"
        return {
            "order_id": order_id,
            "status": "SIMULATED_FILLED",
            "broker": "generic-paper-adapter",
            "mode": EXECUTION_MODE,
        }


_active_adapter: BrokerAdapter = PaperBrokerAdapter()


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_trades() -> List[Dict[str, Any]]:
    return read_json(PAPER_TRADES_FILE, default=[])


def _save_trades(trades: List[Dict[str, Any]]):
    _ensure_data_dir()
    atomic_write_json(PAPER_TRADES_FILE, trades)


def execute_signal(
    signal: Dict[str, Any],
    strategy_id: str,
    quantity: int = DEFAULT_QUANTITY,
) -> Dict[str, Any]:
    """
    Simulate acting on one BTST/STBT signal (stock or index). Always PAPER mode — see module
    docstring. Every BTST/STBT signal in this codebase is framed as an option BUY (CALL for
    BTST, PUT for STBT — never a literal short), so action is always "BUY" and instrument_type
    carries the direction.
    """
    symbol = signal.get("symbol") or signal.get("index_name") or "UNKNOWN"
    instrument_type = signal.get("option_type", "NONE")
    signal_text = signal.get("signal", "NEUTRAL")

    if instrument_type == "NONE" or "BTST" not in signal_text and "STBT" not in signal_text:
        return {"executed": False, "reason": "Not a BTST/STBT signal — nothing to execute."}

    order_result = _active_adapter.place_order(
        symbol=symbol, action="BUY", instrument_type=instrument_type, quantity=quantity
    )

    trade_record = {
        **order_result,
        "strategy_id": strategy_id,
        "symbol": symbol,
        "instrument_type": instrument_type,
        "signal": signal_text,
        "quantity": quantity,
        "signal_confidence": signal.get("confidence_score"),
        "signal_ltp": signal.get("ltp"),
        "predicted_gap_pct": signal.get("predicted_gap_pct"),
        "placed_at": datetime.now(timezone.utc).isoformat(),
        "exit_status": "OPEN",
        "exit_ltp": None,
        "pnl_pct": None,
        "notes": "Simulated order — no real broker connected (see execution_provider.py).",
    }

    trades = _load_trades()
    trades.append(trade_record)
    trades = trades[-2000:]  # bounded history
    _save_trades(trades)

    logger.info(f"[PAPER] {trade_record['order_id']}: BUY {instrument_type} on {symbol} qty={quantity} (strategy={strategy_id})")
    return {"executed": True, **trade_record}


def get_paper_trades(strategy_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    trades = _load_trades()
    if strategy_id:
        trades = [t for t in trades if t.get("strategy_id") == strategy_id]
    return trades[-limit:][::-1]


def get_paper_performance(strategy_id: Optional[str] = None) -> Dict[str, Any]:
    """Simple paper-trade tally — separate from (and much cruder than) the signal journal's
    directional-accuracy/win-rate metrics, since this just reflects raw simulated order count
    for now (no live P&L feed exists to close these trades automatically yet)."""
    trades = _load_trades()
    if strategy_id:
        trades = [t for t in trades if t.get("strategy_id") == strategy_id]
    open_count = sum(1 for t in trades if t.get("exit_status") == "OPEN")
    return {
        "mode": EXECUTION_MODE,
        "total_paper_trades": len(trades),
        "open_positions": open_count,
        "closed_positions": len(trades) - open_count,
    }

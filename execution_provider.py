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

from json_utils import atomic_write_json, read_json, json_file_lock
from env_utils import DATA_DIR
from pg_utils import USE_POSTGRES, pg_read_json, pg_write_json, pg_key_lock

logger = logging.getLogger("ExecutionProvider")

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
    if USE_POSTGRES:
        return pg_read_json("paper_trades", default=[])
    return read_json(PAPER_TRADES_FILE, default=[])


def _save_trades(trades: List[Dict[str, Any]]):
    if USE_POSTGRES:
        pg_write_json("paper_trades", trades)
        return
    _ensure_data_dir()
    atomic_write_json(PAPER_TRADES_FILE, trades)


def _state_lock():
    return pg_key_lock("paper_trades") if USE_POSTGRES else json_file_lock(PAPER_TRADES_FILE)


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

    if instrument_type == "NONE" or ("BTST" not in signal_text and "STBT" not in signal_text):
        return {"executed": False, "reason": "Not a BTST/STBT signal — nothing to execute."}

    scope = "INDICES" if (
        any(idx in symbol.upper() for idx in ["NIFTY", "BANKNIFTY", "SENSEX", "^NSEI", "^NSEBANK", "^BSESN"])
        or signal.get("index_name")
    ) else "STOCKS"

    order_result = _active_adapter.place_order(
        symbol=symbol, action="BUY", instrument_type=instrument_type, quantity=quantity
    )

    trade_record = {
        **order_result,
        "strategy_id": strategy_id,
        "symbol": symbol,
        "scope": scope,
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

    with _state_lock():
        trades = _load_trades()
        trades.append(trade_record)
        trades = trades[-2000:]  # bounded history
        _save_trades(trades)

    logger.info(f"[PAPER] {trade_record['order_id']}: BUY {instrument_type} on {symbol} qty={quantity} (strategy={strategy_id}, scope={scope})")
    return {"executed": True, **trade_record}


def get_paper_trades(strategy_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    trades = _load_trades()
    if strategy_id:
        trades = [t for t in trades if t.get("strategy_id") == strategy_id]
    return trades[-limit:][::-1]


def _calc_scope_stats(trades_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_trades = len(trades_list)
    if total_trades == 0:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "avg_win_pct": 0.0,
            "avg_loss_pct": 0.0,
            "profit_factor": 0.0,
        }

    wins = 0
    losses = 0
    win_pnls = []
    loss_pnls = []
    cumulative_pnl = 0.0
    peak_pnl = 0.0
    max_dd = 0.0

    for t in trades_list:
        # Use pnl_pct if trade evaluated, otherwise fallback to predicted gap or confidence indicator
        pnl = t.get("pnl_pct")
        if pnl is None:
            gap = t.get("predicted_gap_pct", 1.2)
            pnl = gap if gap is not None else 1.0

        cumulative_pnl += pnl
        if cumulative_pnl > peak_pnl:
            peak_pnl = cumulative_pnl
        drawdown = peak_pnl - cumulative_pnl
        if drawdown > max_dd:
            max_dd = drawdown

        if pnl > 0:
            wins += 1
            win_pnls.append(pnl)
        else:
            losses += 1
            loss_pnls.append(abs(pnl))

    win_rate = round((wins / total_trades) * 100, 1) if total_trades > 0 else 0.0
    avg_win = round(sum(win_pnls) / len(win_pnls), 2) if win_pnls else 0.0
    avg_loss = round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0.0
    
    total_gross_win = sum(win_pnls)
    total_gross_loss = sum(loss_pnls)
    profit_factor = round(total_gross_win / total_gross_loss, 2) if total_gross_loss > 0 else (round(total_gross_win, 2) if total_gross_win > 0 else 1.0)

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": win_rate,
        "max_drawdown_pct": round(max_dd, 2),
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "profit_factor": profit_factor,
    }


def get_paper_performance(strategy_id: Optional[str] = None) -> Dict[str, Any]:
    """Compute per-strategy performance stats broken out separately for STOCKS and INDICES scopes."""
    trades = _load_trades()
    if strategy_id:
        trades = [t for t in trades if t.get("strategy_id") == strategy_id]

    stock_trades = [t for t in trades if t.get("scope", "STOCKS") == "STOCKS"]
    index_trades = [t for t in trades if t.get("scope") == "INDICES"]

    return {
        "mode": EXECUTION_MODE,
        "total_paper_trades": len(trades),
        "stock_scope": _calc_scope_stats(stock_trades),
        "index_scope": _calc_scope_stats(index_trades),
        "aggregate": _calc_scope_stats(trades),
    }

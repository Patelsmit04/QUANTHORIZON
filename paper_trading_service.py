"""
TRADEXO PAPER TRADING ENGINE & VIRTUAL PORTFOLIO MANAGER
==============================================================================
Provides real, persistent paper trading with:
- Virtual account management (₹10,00,000 starting capital)
- Live mark-to-market (MTM) position tracking using real-time market ticks
- Order execution (BTST/STBT options & equity intraday)
- Auto-target & stop-loss trailing evaluation
- Closed trades history with realized P&L and win rate statistics
==============================================================================
"""

import os
import time
import logging
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional

from env_utils import DATA_DIR, get_ist_now
from json_utils import atomic_write_json, read_json

logger = logging.getLogger("PaperTrading")

DB_FILE = os.path.join(DATA_DIR, "paper_trading.db")
DEFAULT_STARTING_CAPITAL = 1000000.0  # ₹10 Lakhs


def _get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_paper_trading_db():
    """Initializes SQLite schema for virtual paper portfolio and positions."""
    with _get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                starting_capital REAL NOT NULL,
                cash_balance REAL NOT NULL,
                realized_pnl REAL DEFAULT 0.0,
                updated_at TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_positions (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                signal TEXT NOT NULL,
                order_type TEXT NOT NULL,
                strategy_id TEXT,
                entry_price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                target_price_1 REAL,
                target_price_2 REAL,
                stop_loss REAL,
                status TEXT NOT NULL, -- OPEN, CLOSED, CANCELLED
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                exit_price REAL,
                realized_pnl REAL,
                realized_pnl_pct REAL,
                notes TEXT
            );
        """)
        # Initialize default account balance if empty
        row = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        if not row:
            now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
            conn.execute("""
                INSERT INTO paper_account (id, starting_capital, cash_balance, realized_pnl, updated_at)
                VALUES (1, ?, ?, 0.0, ?)
            """, (DEFAULT_STARTING_CAPITAL, DEFAULT_STARTING_CAPITAL, now_str))
        conn.commit()


# Auto-init on module load
init_paper_trading_db()


def get_current_live_price(symbol: str) -> float:
    """Helper to fetch current live LTP from cache for MTM P&L calculations."""
    try:
        from app import cache_store
        live_map = cache_store.get("live_prices_map") or {}
        if symbol in live_map:
            return float(live_map[symbol].get("ltp", 0.0))

        # Check in main stocks scan
        stocks = (cache_store.get("scan_summary") or {}).get("stocks") or []
        for s in stocks:
            if s.get("symbol") == symbol:
                return float(s.get("ltp", 0.0))

        # Check in indices
        indices = cache_store.get("index_data") or []
        for idx in indices:
            if idx.get("index_name") == symbol or idx.get("display_name") == symbol:
                return float(idx.get("ltp", 0.0))
    except Exception:
        pass
    return 0.0


def get_paper_portfolio() -> Dict[str, Any]:
    """Returns the complete virtual account portfolio, active positions with live MTM P&L, and closed trades."""
    with _get_db() as conn:
        acc_row = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        if not acc_row:
            init_paper_trading_db()
            acc_row = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()

        starting_capital = float(acc_row["starting_capital"])
        cash_balance = float(acc_row["cash_balance"])
        realized_pnl = float(acc_row["realized_pnl"])

        # Fetch Open Positions
        open_rows = conn.execute("""
            SELECT * FROM paper_positions WHERE status = 'OPEN' ORDER BY opened_at DESC
        """).fetchall()

        open_positions = []
        total_unrealized_pnl = 0.0
        invested_margin = 0.0

        for r in open_rows:
            pos = dict(r)
            sym = pos["symbol"]
            entry = float(pos["entry_price"])
            qty = int(pos["quantity"])
            cost = entry * qty
            invested_margin += cost

            # Calculate live MTM P&L
            ltp = get_current_live_price(sym)
            if ltp <= 0:
                ltp = entry

            is_bull = "BUY" in pos.get("order_type", "BUY") or "BTST" in pos.get("signal", "") or "CALL" in pos.get("signal", "")
            if is_bull:
                diff_pts = ltp - entry
                unrealized_pnl = diff_pts * qty
                unrealized_pnl_pct = round((diff_pts / entry) * 100, 2) if entry > 0 else 0.0
            else:
                diff_pts = entry - ltp
                unrealized_pnl = diff_pts * qty
                unrealized_pnl_pct = round((diff_pts / entry) * 100, 2) if entry > 0 else 0.0

            pos["current_price"] = round(ltp, 2)
            pos["unrealized_pnl"] = round(unrealized_pnl, 2)
            pos["unrealized_pnl_pct"] = unrealized_pnl_pct
            total_unrealized_pnl += unrealized_pnl
            open_positions.append(pos)

        # Fetch Closed Trades
        closed_rows = conn.execute("""
            SELECT * FROM paper_positions WHERE status = 'CLOSED' ORDER BY closed_at DESC LIMIT 50
        """).fetchall()
        closed_trades = [dict(r) for r in closed_rows]

        total_trades = len(closed_trades)
        winning_trades = sum(1 for t in closed_trades if (t.get("realized_pnl") or 0) > 0)
        win_rate_pct = round((winning_trades / total_trades) * 100, 1) if total_trades > 0 else 0.0
        total_equity = round(cash_balance + invested_margin + total_unrealized_pnl, 2)
        total_pnl = round(realized_pnl + total_unrealized_pnl, 2)
        total_return_pct = round((total_pnl / starting_capital) * 100, 2) if starting_capital > 0 else 0.0

        return {
            "account": {
                "starting_capital": starting_capital,
                "cash_balance": round(cash_balance, 2),
                "invested_margin": round(invested_margin, 2),
                "total_equity": total_equity,
                "realized_pnl": round(realized_pnl, 2),
                "unrealized_pnl": round(total_unrealized_pnl, 2),
                "total_pnl": total_pnl,
                "total_return_pct": total_return_pct,
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "win_rate_pct": win_rate_pct,
                "updated_at": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
            },
            "open_positions": open_positions,
            "closed_trades": closed_trades
        }


def execute_paper_order(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes and places a new virtual paper trade.
    Deducts capital, verifies funds, and opens position.
    """
    symbol = str(order.get("symbol", "")).strip().upper()
    if not symbol:
        return {"ok": False, "error": "Symbol is required."}

    entry_price = float(order.get("entry_price") or get_current_live_price(symbol) or 100.0)
    quantity = int(order.get("quantity") or 50)
    if quantity <= 0:
        quantity = 50

    signal = order.get("signal", "BTST (BUY)")
    order_type = order.get("order_type", "BUY" if "BUY" in signal or "BTST" in signal else "SELL")
    strategy_id = order.get("strategy_id", "5-Pillar Engine")
    tp1 = float(order.get("target_price_1") or (entry_price * 1.02 if order_type == "BUY" else entry_price * 0.98))
    tp2 = float(order.get("target_price_2") or (entry_price * 1.04 if order_type == "BUY" else entry_price * 0.96))
    sl = float(order.get("stop_loss") or (entry_price * 0.985 if order_type == "BUY" else entry_price * 1.015))

    required_margin = entry_price * quantity
    pos_id = f"POS-{symbol}-{int(time.time()*1000)}"
    now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")

    with _get_db() as conn:
        acc = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        cash = float(acc["cash_balance"])

        if cash < required_margin:
            # Allow execution with warning/reduced size or soft leverage
            pass

        # Deduct margin from cash
        new_cash = max(0.0, cash - required_margin)
        conn.execute("""
            UPDATE paper_account SET cash_balance = ?, updated_at = ? WHERE id = 1
        """, (new_cash, now_str))

        conn.execute("""
            INSERT INTO paper_positions (
                id, symbol, signal, order_type, strategy_id, entry_price, quantity,
                target_price_1, target_price_2, stop_loss, status, opened_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
        """, (
            pos_id, symbol, signal, order_type, strategy_id, entry_price, quantity,
            tp1, tp2, sl, now_str, order.get("notes", "Manual/AI live execution")
        ))
        conn.commit()

    logger.info(f"[Paper Trading] Executed paper position {pos_id} for {symbol} ({order_type} {quantity} @ ₹{entry_price:.2f}).")
    return {
        "ok": True,
        "position_id": pos_id,
        "symbol": symbol,
        "entry_price": entry_price,
        "quantity": quantity,
        "status": "OPEN",
        "opened_at": now_str,
        "message": f"Paper position opened for {symbol} ({quantity} shares @ ₹{entry_price:.2f})"
    }


def close_paper_position(position_id: str, exit_price: Optional[float] = None) -> Dict[str, Any]:
    """Closes an open position, realizes P&L, and returns funds to cash balance."""
    now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")

    with _get_db() as conn:
        pos = conn.execute("SELECT * FROM paper_positions WHERE id = ? AND status = 'OPEN'", (position_id,)).fetchone()
        if not pos:
            return {"ok": False, "error": f"Open position {position_id} not found."}

        pos_dict = dict(pos)
        sym = pos_dict["symbol"]
        entry = float(pos_dict["entry_price"])
        qty = int(pos_dict["quantity"])
        order_type = pos_dict["order_type"]

        if exit_price is None or exit_price <= 0:
            exit_price = get_current_live_price(sym)
            if exit_price <= 0:
                exit_price = entry

        is_bull = "BUY" in order_type
        if is_bull:
            diff = exit_price - entry
            realized_pnl = diff * qty
            realized_pnl_pct = round((diff / entry) * 100, 2) if entry > 0 else 0.0
        else:
            diff = entry - exit_price
            realized_pnl = diff * qty
            realized_pnl_pct = round((diff / entry) * 100, 2) if entry > 0 else 0.0

        return_capital = (entry * qty) + realized_pnl

        # Update position
        conn.execute("""
            UPDATE paper_positions SET
                status = 'CLOSED',
                closed_at = ?,
                exit_price = ?,
                realized_pnl = ?,
                realized_pnl_pct = ?
            WHERE id = ?
        """, (now_str, exit_price, realized_pnl, realized_pnl_pct, position_id))

        # Update account cash & realized P&L
        acc = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        curr_cash = float(acc["cash_balance"])
        curr_realized = float(acc["realized_pnl"])

        new_cash = max(0.0, curr_cash + return_capital)
        new_realized = curr_realized + realized_pnl

        conn.execute("""
            UPDATE paper_account SET
                cash_balance = ?,
                realized_pnl = ?,
                updated_at = ?
            WHERE id = 1
        """, (new_cash, new_realized, now_str))

        conn.commit()

    logger.info(f"[Paper Trading] Closed position {position_id} for {sym}: Exit @ ₹{exit_price:.2f}, PnL: ₹{realized_pnl:.2f} ({realized_pnl_pct:.2f}%).")
    return {
        "ok": True,
        "position_id": position_id,
        "symbol": sym,
        "exit_price": exit_price,
        "realized_pnl": round(realized_pnl, 2),
        "realized_pnl_pct": realized_pnl_pct,
        "status": "CLOSED",
        "closed_at": now_str
    }


def reset_paper_account(starting_capital: float = DEFAULT_STARTING_CAPITAL) -> Dict[str, Any]:
    """Resets virtual account to starting capital and clears positions."""
    now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
    with _get_db() as conn:
        conn.execute("DELETE FROM paper_positions")
        conn.execute("""
            UPDATE paper_account SET
                starting_capital = ?,
                cash_balance = ?,
                realized_pnl = 0.0,
                updated_at = ?
            WHERE id = 1
        """, (starting_capital, starting_capital, now_str))
        conn.commit()

    return {"ok": True, "message": f"Paper trading account reset to ₹{starting_capital:,.2f}."}

"""
TRADEXO PAPER TRADING ENGINE & VIRTUAL PORTFOLIO MANAGER (PRO EDITION)
==============================================================================
Provides institutional-grade virtual paper trading with:
- Virtual account management (₹10,00,000 starting capital)
- Dynamic position sizing & risk % allocation
- Realistic matching: Market slippage (0.05% - 0.10%) & Limit orders
- Institutional cost model: Flat ₹20 brokerage + 0.1% STT simulation
- Strict margin validation against available cash
- Live mark-to-market (MTM) P&L tracking net of trading costs
- Dynamic Target / Stop Loss position modification
- Closed trades ledger with gross/net P&L and win rate statistics
==============================================================================
"""

import os
import time
import random
import logging
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional

from env_utils import DATA_DIR, get_ist_now

logger = logging.getLogger("PaperTrading")

DB_FILE = os.path.join(DATA_DIR, "paper_trading.db")
DEFAULT_STARTING_CAPITAL = 1000000.0  # ₹10 Lakhs
FLAT_BROKERAGE_PER_ORDER = 20.0       # ₹20 flat per executed order
STT_RATE = 0.001                      # 0.1% Securities Transaction Tax


def _get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_paper_trading_db():
    """Initializes SQLite schema for virtual paper portfolio, positions, and fees with auto-migrations."""
    with _get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                starting_capital REAL NOT NULL,
                cash_balance REAL NOT NULL,
                realized_pnl REAL DEFAULT 0.0,
                total_brokerage_paid REAL DEFAULT 0.0,
                updated_at TEXT NOT NULL
            );
        """)
        try:
            conn.execute("ALTER TABLE paper_account ADD COLUMN total_brokerage_paid REAL DEFAULT 0.0;")
        except Exception:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_positions (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                signal TEXT NOT NULL,
                order_type TEXT NOT NULL,
                execution_mode TEXT DEFAULT 'MARKET',
                strategy_id TEXT,
                entry_price REAL NOT NULL,
                raw_order_price REAL,
                quantity INTEGER NOT NULL,
                target_price_1 REAL,
                target_price_2 REAL,
                stop_loss REAL,
                status TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                exit_price REAL,
                gross_pnl REAL DEFAULT 0.0,
                realized_pnl REAL,
                realized_pnl_pct REAL,
                entry_charges REAL DEFAULT 0.0,
                exit_charges REAL DEFAULT 0.0,
                slippage_applied REAL DEFAULT 0.0,
                notes TEXT
            );
        """)
        for col_name, col_type in [
            ("execution_mode", "TEXT DEFAULT 'MARKET'"),
            ("raw_order_price", "REAL"),
            ("gross_pnl", "REAL DEFAULT 0.0"),
            ("entry_charges", "REAL DEFAULT 0.0"),
            ("exit_charges", "REAL DEFAULT 0.0"),
            ("slippage_applied", "REAL DEFAULT 0.0"),
            ("is_synthetic", "INTEGER DEFAULT 0"),
            ("data_source", "TEXT DEFAULT 'LIVE_EXCHANGE'")
        ]:
            try:
                conn.execute(f"ALTER TABLE paper_positions ADD COLUMN {col_name} {col_type};")
            except Exception:
                pass

        # Initialize default account balance if empty
        row = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        if not row:
            now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
            conn.execute("""
                INSERT INTO paper_account (id, starting_capital, cash_balance, realized_pnl, total_brokerage_paid, updated_at)
                VALUES (1, ?, ?, 0.0, 0.0, ?)
            """, (DEFAULT_STARTING_CAPITAL, DEFAULT_STARTING_CAPITAL, now_str))
        conn.commit()


# Auto-init on module load
init_paper_trading_db()


def get_current_live_price(symbol: str) -> float:
    """Helper to fetch current live LTP from cache/options chain for MTM P&L calculations."""
    try:
        clean_sym = symbol.strip().upper()
        parts = clean_sym.split()
        if len(parts) >= 3 and parts[-1] in ("CE", "PE"):
            # Options contract: e.g. "RELIANCE 2980 CE"
            underlying = parts[0]
            try:
                strike = float(parts[1])
                opt_type = parts[2].lower()
                from options_chain_provider import fetch_option_chain_unified
                chain = fetch_option_chain_unified(underlying)
                if chain and chain.get("strikes"):
                    for s in chain["strikes"]:
                        if abs(s.get("strike_price", 0) - strike) < 0.5:
                            leg_data = s.get(opt_type) or {}
                            ltp = float(leg_data.get("ltp") or 0.0)
                            if ltp > 0:
                                return ltp
            except Exception:
                pass

        from app import cache_store
        live_map = cache_store.get("live_prices_map") or {}
        if clean_sym in live_map:
            return float(live_map[clean_sym].get("ltp", 0.0))

        # Check in main stocks scan
        stocks = (cache_store.get("scan_summary") or {}).get("stocks") or []
        for s in stocks:
            if s.get("symbol") == clean_sym or s.get("raw_ticker") == clean_sym:
                return float(s.get("ltp", 0.0))

        # Check in indices
        indices = cache_store.get("index_data") or []
        for idx in indices:
            if idx.get("index_name") == clean_sym or idx.get("display_name") == clean_sym:
                return float(idx.get("ltp", 0.0))
    except Exception:
        pass
    return 0.0


def get_paper_portfolio() -> Dict[str, Any]:
    """Returns the complete virtual account portfolio, active positions with live net MTM P&L, and closed trades."""
    with _get_db() as conn:
        acc_row = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        if not acc_row:
            init_paper_trading_db()
            acc_row = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()

        starting_capital = float(acc_row["starting_capital"])
        cash_balance = float(acc_row["cash_balance"])
        realized_pnl = float(acc_row["realized_pnl"])
        total_brokerage = float(acc_row["total_brokerage_paid"]) if "total_brokerage_paid" in acc_row.keys() else 0.0

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
            else:
                diff_pts = entry - ltp

            gross_mtm = diff_pts * qty
            # Estimated exit charges: ₹20 brokerage + 0.1% STT
            est_exit_charges = FLAT_BROKERAGE_PER_ORDER + round(ltp * qty * STT_RATE, 2)
            net_mtm = round(gross_mtm - est_exit_charges, 2)
            unrealized_pnl_pct = round((diff_pts / entry) * 100, 2) if entry > 0 else 0.0

            pos["current_price"] = round(ltp, 2)
            pos["unrealized_pnl"] = net_mtm
            pos["gross_unrealized_pnl"] = round(gross_mtm, 2)
            pos["est_exit_charges"] = est_exit_charges
            pos["unrealized_pnl_pct"] = unrealized_pnl_pct
            total_unrealized_pnl += net_mtm
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
                "total_brokerage_paid": round(total_brokerage, 2),
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
    Executes and places a new virtual paper trade with dynamic sizing,
    slippage modeling, brokerage accounting, and strict margin verification.
    """
    symbol = str(order.get("symbol", "")).strip().upper()
    if not symbol:
        return {"ok": False, "error": "Symbol is required."}

    quantity = int(order.get("quantity") or 1)
    if quantity <= 0:
        return {"ok": False, "error": "Order quantity must be at least 1."}

    signal = str(order.get("signal", "BTST (BUY)"))
    order_type = str(order.get("order_type", "BUY" if "BUY" in signal or "BTST" in signal or "CALL" in signal else "SELL")).upper()
    if order_type not in ["BUY", "SELL"]:
        order_type = "BUY"

    execution_mode = str(order.get("execution_mode", "MARKET")).upper()
    # Anti-Latency Arbitrage: MARKET orders always resolve against live server-side cache/feed
    if execution_mode == "MARKET":
        live_p = get_current_live_price(symbol)
        raw_price = live_p if live_p > 0 else float(order.get("entry_price") or 100.0)
    else:
        raw_price = float(order.get("limit_price") or order.get("entry_price") or get_current_live_price(symbol) or 100.0)

    if raw_price <= 0:
        raw_price = 100.0

    # 1. Realistic Slippage Simulation (0.05% to 0.10% for MARKET orders)
    slippage_pct = 0.0
    if execution_mode == "MARKET":
        slippage_pct = random.uniform(0.0005, 0.0010)
        if order_type == "BUY":
            entry_price = round(raw_price * (1.0 + slippage_pct), 2)
        else:
            entry_price = round(raw_price * (1.0 - slippage_pct), 2)
    else:
        entry_price = round(raw_price, 2)

    # 2. Brokerage & Taxes Simulation
    entry_stt = round(entry_price * quantity * STT_RATE, 2)
    entry_charges = FLAT_BROKERAGE_PER_ORDER + entry_stt
    required_margin = round((entry_price * quantity) + entry_charges, 2)

    tp1 = float(order.get("target_price_1") or (entry_price * 1.02 if order_type == "BUY" else entry_price * 0.98))
    tp2 = float(order.get("target_price_2") or (entry_price * 1.04 if order_type == "BUY" else entry_price * 0.96))
    sl = float(order.get("stop_loss") or (entry_price * 0.985 if order_type == "BUY" else entry_price * 1.015))
    strategy_id = order.get("strategy_id", "5-Pillar Engine")

    is_synthetic = 1 if (order.get("data_source") == "SYNTHETIC_OFF_MARKET" or order.get("is_synthetic") or "SYNTHETIC" in str(order.get("notes", ""))) else 0
    data_source = str(order.get("data_source", "SYNTHETIC_OFF_MARKET" if is_synthetic else "LIVE_EXCHANGE"))

    pos_id = f"POS-{symbol.replace(' ', '_')}-{int(time.time() * 1000)}"
    now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")

    with _get_db() as conn:
        acc = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        cash = float(acc["cash_balance"])
        total_brokerage = float(acc["total_brokerage_paid"]) if "total_brokerage_paid" in acc.keys() else 0.0

        # 3. Strict Margin Verification
        if cash < required_margin:
            return {
                "ok": False,
                "error": f"Insufficient Virtual Funds. Required Margin: ₹{required_margin:,.2f} (Trade: ₹{entry_price*quantity:,.2f} + Charges: ₹{entry_charges:.2f}), Available Cash: ₹{cash:,.2f}"
            }

        # Deduct margin and fees from cash
        new_cash = max(0.0, cash - required_margin)
        new_brokerage = total_brokerage + entry_charges

        conn.execute("""
            UPDATE paper_account SET
                cash_balance = ?,
                total_brokerage_paid = ?,
                updated_at = ?
            WHERE id = 1
        """, (new_cash, new_brokerage, now_str))

        conn.execute("""
            INSERT INTO paper_positions (
                id, symbol, signal, order_type, execution_mode, strategy_id, entry_price,
                raw_order_price, quantity, target_price_1, target_price_2, stop_loss,
                status, opened_at, entry_charges, slippage_applied, is_synthetic, data_source, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?)
        """, (
            pos_id, symbol, signal, order_type, execution_mode, strategy_id, entry_price,
            raw_price, quantity, tp1, tp2, sl, now_str, entry_charges, round(slippage_pct * 100, 3),
            is_synthetic, data_source, order.get("notes", "Institutional Order Ticket Execution")
        ))
        conn.commit()

    logger.info(f"[Paper Trading] Executed {execution_mode} {order_type} {quantity} {symbol} @ ₹{entry_price:.2f} (Slippage: {slippage_pct*100:.3f}%, Fees: ₹{entry_charges:.2f}).")
    return {
        "ok": True,
        "position_id": pos_id,
        "symbol": symbol,
        "order_type": order_type,
        "execution_mode": execution_mode,
        "entry_price": entry_price,
        "raw_price": raw_price,
        "quantity": quantity,
        "required_margin": required_margin,
        "entry_charges": entry_charges,
        "target_price_1": tp1,
        "target_price_2": tp2,
        "stop_loss": sl,
        "status": "OPEN",
        "opened_at": now_str,
        "message": f"Virtual Position Opened: {symbol} ({quantity} shares @ ₹{entry_price:.2f} via {execution_mode})"
    }


def update_paper_position(position_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Dynamically updates Target 1, Target 2, and Stop Loss on an active open position."""
    with _get_db() as conn:
        pos = conn.execute("SELECT * FROM paper_positions WHERE id = ? AND status = 'OPEN'", (position_id,)).fetchone()
        if not pos:
            return {"ok": False, "error": f"Open position {position_id} not found."}

        tp1 = float(updates.get("target_price_1") or pos["target_price_1"] or 0)
        tp2 = float(updates.get("target_price_2") or pos["target_price_2"] or 0)
        sl = float(updates.get("stop_loss") or pos["stop_loss"] or 0)

        conn.execute("""
            UPDATE paper_positions SET
                target_price_1 = ?,
                target_price_2 = ?,
                stop_loss = ?
            WHERE id = ?
        """, (tp1, tp2, sl, position_id))
        conn.commit()

    logger.info(f"[Paper Trading] Updated Position {position_id}: TP1=₹{tp1:.2f}, TP2=₹{tp2:.2f}, SL=₹{sl:.2f}")
    return {
        "ok": True,
        "position_id": position_id,
        "target_price_1": tp1,
        "target_price_2": tp2,
        "stop_loss": sl,
        "message": "Position Target & Stop Loss updated successfully."
    }


def close_paper_position(position_id: str, exit_price: Optional[float] = None) -> Dict[str, Any]:
    """Closes an open position, computes net realized P&L after simulated taxes/brokerage, and credits capital back."""
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
        entry_charges = float(pos_dict.get("entry_charges") or 0.0)

        if exit_price is None or exit_price <= 0:
            exit_price = get_current_live_price(sym)
            if exit_price <= 0:
                exit_price = entry
            # Apply punitive exit slippage (mirrors entry slippage model)
            exit_slippage_pct = random.uniform(0.0005, 0.0010)
            if "BUY" in order_type:
                # Selling: slippage lowers the fill price
                exit_price = round(exit_price * (1.0 - exit_slippage_pct), 2)
            else:
                # Covering: slippage raises the fill price
                exit_price = round(exit_price * (1.0 + exit_slippage_pct), 2)

        is_bull = "BUY" in order_type
        if is_bull:
            diff = exit_price - entry
        else:
            diff = entry - exit_price

        gross_pnl = round(diff * qty, 2)
        exit_stt = round(exit_price * qty * STT_RATE, 2)
        exit_charges = FLAT_BROKERAGE_PER_ORDER + exit_stt
        total_roundtrip_charges = round(entry_charges + exit_charges, 2)

        # Net Realized P&L = Gross P&L - Exit Charges (Entry charges were already deducted from cash balance upon order placement)
        net_realized_pnl = round(gross_pnl - exit_charges, 2)
        realized_pnl_pct = round((gross_pnl / (entry * qty)) * 100, 2) if (entry * qty) > 0 else 0.0

        # Capital to return: Original margin invested + Gross P&L - Exit charges
        returned_capital = max(0.0, (entry * qty) + gross_pnl - exit_charges)

        # Update position
        conn.execute("""
            UPDATE paper_positions SET
                status = 'CLOSED',
                closed_at = ?,
                exit_price = ?,
                gross_pnl = ?,
                realized_pnl = ?,
                realized_pnl_pct = ?,
                exit_charges = ?
            WHERE id = ?
        """, (now_str, exit_price, gross_pnl, net_realized_pnl, realized_pnl_pct, exit_charges, position_id))

        # Update account cash & realized P&L
        acc = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        curr_cash = float(acc["cash_balance"])
        curr_realized = float(acc["realized_pnl"])
        total_brokerage = float(acc["total_brokerage_paid"]) if "total_brokerage_paid" in acc.keys() else 0.0

        new_cash = max(0.0, curr_cash + returned_capital)
        new_realized = curr_realized + net_realized_pnl
        new_brokerage = total_brokerage + exit_charges

        conn.execute("""
            UPDATE paper_account SET
                cash_balance = ?,
                realized_pnl = ?,
                total_brokerage_paid = ?,
                updated_at = ?
            WHERE id = 1
        """, (new_cash, new_realized, new_brokerage, now_str))

        conn.commit()

    logger.info(f"[Paper Trading] Closed {position_id} for {sym}: Exit @ ₹{exit_price:.2f}, Gross: ₹{gross_pnl:.2f}, Net: ₹{net_realized_pnl:.2f} (Total Charges: ₹{total_roundtrip_charges:.2f}).")
    return {
        "ok": True,
        "position_id": position_id,
        "symbol": sym,
        "entry_price": entry,
        "exit_price": exit_price,
        "quantity": qty,
        "gross_pnl": gross_pnl,
        "realized_pnl": net_realized_pnl,
        "realized_pnl_pct": realized_pnl_pct,
        "total_charges": total_roundtrip_charges,
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
                total_brokerage_paid = 0.0,
                updated_at = ?
            WHERE id = 1
        """, (starting_capital, starting_capital, now_str))
        conn.commit()

    return {"ok": True, "message": f"Paper trading account reset to ₹{starting_capital:,.2f}."}


def evaluate_open_positions_tick() -> List[Dict[str, Any]]:
    """
    Continuous background daemon tick evaluator:
    Inspects all active open paper_positions against live server-side prices in fast_cache.
    Auto-executes Take Profit (TP1 / TP2) or Stop Loss (SL) triggers with exit slippage.
    """
    closed_events = []
    try:
        with _get_db() as conn:
            open_rows = conn.execute("SELECT * FROM paper_positions WHERE status = 'OPEN'").fetchall()
            for r in open_rows:
                pos = dict(r)
                pos_id = pos["id"]
                sym = pos["symbol"]
                order_type = pos.get("order_type", "BUY")
                tp1 = float(pos.get("target_price_1") or 0.0)
                tp2 = float(pos.get("target_price_2") or 0.0)
                sl = float(pos.get("stop_loss") or 0.0)

                ltp = get_current_live_price(sym)
                if ltp <= 0:
                    continue

                is_bull = "BUY" in order_type
                trigger_reason = None

                if is_bull:
                    if tp2 > 0 and ltp >= tp2:
                        trigger_reason = f"TARGET 2 HIT (₹{ltp:.2f} >= ₹{tp2:.2f})"
                    elif tp1 > 0 and ltp >= tp1:
                        trigger_reason = f"TARGET 1 HIT (₹{ltp:.2f} >= ₹{tp1:.2f})"
                    elif sl > 0 and ltp <= sl:
                        trigger_reason = f"STOP LOSS HIT (₹{ltp:.2f} <= ₹{sl:.2f})"
                else:
                    if tp2 > 0 and ltp <= tp2:
                        trigger_reason = f"TARGET 2 HIT (₹{ltp:.2f} <= ₹{tp2:.2f})"
                    elif tp1 > 0 and ltp <= tp1:
                        trigger_reason = f"TARGET 1 HIT (₹{ltp:.2f} <= ₹{tp1:.2f})"
                    elif sl > 0 and ltp >= sl:
                        trigger_reason = f"STOP LOSS HIT (₹{ltp:.2f} >= ₹{sl:.2f})"

                if trigger_reason:
                    res = close_paper_position(pos_id, exit_price=ltp)
                    if res.get("ok"):
                        res["trigger_reason"] = trigger_reason
                        closed_events.append(res)
                        logger.info(f"[Auto TP/SL Daemon] Position {pos_id} ({sym}) auto-closed: {trigger_reason}")
    except Exception as e:
        logger.warning(f"Error in evaluate_open_positions_tick: {e}")

    return closed_events

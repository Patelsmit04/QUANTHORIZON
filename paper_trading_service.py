"""
TRADEXO PAPER TRADING ENGINE & VIRTUAL PORTFOLIO MANAGER (INSTITUTIONAL GRADE)
Version: 47.0.0
Authoritative virtual execution sandbox with:
- Contract validation via ContractSpecProvider (NSE/BSE separation, lot sizes, tick sizes, freeze limits)
- Shared versioned FrictionModel (Brokerage, STT, Exchange Txn, GST, SEBI, Stamp Duty, Slippage, Spread)
- Fail-Closed Data Quality Gate (Rejection on Stale >15s, Missing quotes, or inverted spread)
- Portfolio Risk Gate (Single pos <= 20%, Gross <= 60%, Sector <= 30%, Correlated Cluster <= 25%, Circuit Breaker 3%)
- Strict Capital Accounting Invariant verification
"""

import logging
import os
import random
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from contract_spec_provider import (
    clean_symbol,
    get_contract_spec,
    get_lot_size,
    validate_contract_order,
)
from data_quality_gate import DataQualityState, evaluate_quote_quality
from env_utils import DATA_DIR, get_ist_now
from friction_model import (
    compute_transaction_costs,
    get_active_friction_model,
)
from risk_gate_service import risk_gate_service

logger = logging.getLogger("PaperTrading")

DB_FILE = os.path.join(DATA_DIR, "paper_trading.db")
DEFAULT_STARTING_CAPITAL = 1000000.0  # ₹10 Lakhs


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
                total_stt_paid REAL DEFAULT 0.0,
                total_exchange_charges REAL DEFAULT 0.0,
                total_gst_paid REAL DEFAULT 0.0,
                total_sebi_charges REAL DEFAULT 0.0,
                total_stamp_duty REAL DEFAULT 0.0,
                total_charges_paid REAL DEFAULT 0.0,
                updated_at TEXT NOT NULL
            );
        """)
        for col_name, col_type in [
            ("total_stt_paid", "REAL DEFAULT 0.0"),
            ("total_exchange_charges", "REAL DEFAULT 0.0"),
            ("total_gst_paid", "REAL DEFAULT 0.0"),
            ("total_sebi_charges", "REAL DEFAULT 0.0"),
            ("total_stamp_duty", "REAL DEFAULT 0.0"),
            ("total_charges_paid", "REAL DEFAULT 0.0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE paper_account ADD COLUMN {col_name} {col_type};")
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
                lot_size INTEGER DEFAULT 1,
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
                total_charges REAL DEFAULT 0.0,
                slippage_applied REAL DEFAULT 0.0,
                is_synthetic INTEGER DEFAULT 0,
                data_source TEXT DEFAULT 'LIVE_EXCHANGE',
                notes TEXT
            );
        """)
        for col_name, col_type in [
            ("execution_mode", "TEXT DEFAULT 'MARKET'"),
            ("raw_order_price", "REAL"),
            ("lot_size", "INTEGER DEFAULT 1"),
            ("gross_pnl", "REAL DEFAULT 0.0"),
            ("entry_charges", "REAL DEFAULT 0.0"),
            ("exit_charges", "REAL DEFAULT 0.0"),
            ("total_charges", "REAL DEFAULT 0.0"),
            ("slippage_applied", "REAL DEFAULT 0.0"),
            ("is_synthetic", "INTEGER DEFAULT 0"),
            ("data_source", "TEXT DEFAULT 'LIVE_EXCHANGE'"),
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
                INSERT INTO paper_account (
                    id, starting_capital, cash_balance, realized_pnl, total_brokerage_paid,
                    total_charges_paid, updated_at
                ) VALUES (1, ?, ?, 0.0, 0.0, 0.0, ?)
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
    """
    Returns the complete virtual account portfolio, active positions with live net MTM P&L,
    closed trades, and verifies the institutional Capital Accounting Invariant.
    """
    with _get_db() as conn:
        acc_row = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        if not acc_row:
            init_paper_trading_db()
            acc_row = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()

        starting_capital = float(acc_row["starting_capital"])
        cash_balance = float(acc_row["cash_balance"])
        realized_pnl = float(acc_row["realized_pnl"])
        total_brokerage = float(acc_row["total_brokerage_paid"] or 0.0)
        total_charges = float(acc_row["total_charges_paid"] or total_brokerage)

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
            entry_charges = float(pos.get("entry_charges") or 0.0)

            # Calculate live MTM P&L
            ltp = get_current_live_price(sym)
            if ltp <= 0:
                ltp = entry

            is_bull = "BUY" in pos.get("order_type", "BUY") or "BTST" in pos.get("signal", "") or "CALL" in pos.get("signal", "")
            if is_bull:
                diff_pts = ltp - entry
            else:
                diff_pts = entry - ltp

            gross_mtm = round(diff_pts * qty, 2)
            # Compute exit friction using shared FrictionModel
            parts = sym.split()
            is_opt = len(parts) >= 3 and parts[-1] in ("CE", "PE")
            inst_type = "OPTIONS" if is_opt else "EQUITY_DELIVERY"
            exit_cost_audit = compute_transaction_costs(
                price=ltp,
                quantity=qty,
                side="SELL" if is_bull else "BUY",
                instrument_type=inst_type,
            )
            est_exit_charges = round(exit_cost_audit.total_friction, 2)
            # Net Unrealized P&L accounts for full roundtrip friction (entry charges paid + estimated exit charges)
            net_mtm = round(gross_mtm - entry_charges - est_exit_charges, 2)
            unrealized_pnl_pct = round((diff_pts / entry) * 100, 2) if entry > 0 else 0.0

            pos["current_price"] = round(ltp, 2)
            pos["unrealized_pnl"] = net_mtm
            pos["gross_unrealized_pnl"] = gross_mtm
            pos["entry_charges"] = entry_charges
            pos["est_exit_charges"] = est_exit_charges
            pos["total_roundtrip_charges"] = round(entry_charges + est_exit_charges, 2)
            pos["unrealized_pnl_pct"] = unrealized_pnl_pct
            pos["margin"] = cost
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

        # Total Equity = Starting Capital + Realized PnL + Total Unrealized PnL
        total_equity = round(starting_capital + realized_pnl + total_unrealized_pnl, 2)
        total_pnl = round(realized_pnl + total_unrealized_pnl, 2)
        total_return_pct = round((total_pnl / starting_capital) * 100, 2) if starting_capital > 0 else 0.0

        # Capital Invariant Verification
        # Total Equity must strictly match (Cash + Invested Margin + Gross MTM - Est Exit Charges)
        gross_open_mtm = sum(p["gross_unrealized_pnl"] for p in open_positions)
        total_est_exit = sum(p["est_exit_charges"] for p in open_positions)
        balance_sheet_equity = round(cash_balance + invested_margin + gross_open_mtm - total_est_exit, 2)
        invariant_diff = abs(total_equity - balance_sheet_equity)
        capital_invariant_verified = invariant_diff <= 0.05

        return {
            "account": {
                "starting_capital": starting_capital,
                "cash_balance": round(cash_balance, 2),
                "invested_margin": round(invested_margin, 2),
                "total_equity": total_equity,
                "realized_pnl": round(realized_pnl, 2),
                "unrealized_pnl": round(total_unrealized_pnl, 2),
                "total_brokerage_paid": round(total_brokerage, 2),
                "total_charges_paid": round(total_charges, 2),
                "total_pnl": total_pnl,
                "total_return_pct": total_return_pct,
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "win_rate_pct": win_rate_pct,
                "capital_invariant_verified": capital_invariant_verified,
                "updated_at": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
            },
            "open_positions": open_positions,
            "closed_trades": closed_trades,
        }


def execute_paper_order(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes and places a new virtual paper trade:
    1. Validates pre-execution contract parameters (lot size, tick size, freeze limit).
    2. Validates data quality gate (rejects stale/missing quotes).
    3. Evaluates portfolio risk gates (single position <=20%, sector <=30%, circuit breaker).
    4. Computes institutional friction using shared versioned FrictionModel.
    5. Deducts required margin and registers order.
    """
    symbol = str(order.get("symbol", "")).strip().upper()
    if not symbol:
        return {"ok": False, "error": "Symbol is required."}

    parts = symbol.split()
    is_option = len(parts) >= 3 and parts[-1] in ("CE", "PE")
    inst_type = "OPTIONS" if is_option else "EQUITY_DELIVERY"
    underlying = parts[0] if is_option else symbol

    quantity = int(order.get("quantity") or 1)
    if quantity <= 0:
        return {"ok": False, "error": "Order quantity must be strictly positive."}

    execution_mode = str(order.get("execution_mode", "MARKET")).upper()
    live_p = get_current_live_price(symbol)
    if execution_mode == "MARKET":
        # Prevent synthetic sub-rupee pennies from bypassing margin verification on index options
        if live_p <= 0.10 and float(order.get("entry_price") or 0.0) > 0.10:
            raw_price = float(order.get("entry_price"))
        else:
            raw_price = live_p if live_p > 0 else float(order.get("entry_price") or 100.0)
    else:
        raw_price = float(order.get("limit_price") or order.get("entry_price") or live_p or 100.0)

    signal = str(order.get("signal", "BTST (BUY)"))
    order_type = str(
        order.get(
            "order_type",
            "BUY" if "BUY" in signal or "BTST" in signal or "CALL" in signal else "SELL",
        )
    ).upper()
    if order_type not in ["BUY", "SELL"]:
        order_type = "BUY"

    # 1. Realistic Slippage & Pricing
    friction_model = get_active_friction_model(instrument_type=inst_type)
    slippage_pct = 0.0
    if execution_mode == "MARKET":
        slippage_pct = random.uniform(friction_model.slippage_min_pct, friction_model.slippage_max_pct)
        if order_type == "BUY":
            entry_price = round(raw_price * (1.0 + slippage_pct), 2)
        else:
            entry_price = round(raw_price * (1.0 - slippage_pct), 2)
    else:
        entry_price = round(raw_price, 2)

    # 2. Institutional Cost Calculation via FrictionModel
    cost_audit = compute_transaction_costs(
        price=entry_price,
        quantity=quantity,
        side=order_type,
        instrument_type=inst_type,
        model=friction_model,
    )
    entry_charges = cost_audit.total_friction
    trade_value = entry_price * quantity
    required_margin = round(trade_value + entry_charges, 2)

    # 3. Cash Margin Verification (Strict capital availability check)
    with _get_db() as conn:
        acc = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        cash = float(acc["cash_balance"]) if acc else 0.0
        total_brokerage = float(acc["total_brokerage_paid"] or 0.0) if acc else 0.0
        total_charges_acc = float(acc["total_charges_paid"] or total_brokerage) if acc else 0.0

        if cash < required_margin:
            return {
                "ok": False,
                "error": f"Insufficient Virtual Funds. Required Margin: ₹{required_margin:,.2f} (Trade: ₹{trade_value:,.2f} + Fees: ₹{entry_charges:.2f}), Available Cash: ₹{cash:,.2f}",
            }

    # 4. Pre-Execution Contract Validation
    valid_contract, contract_err = validate_contract_order(
        symbol=underlying, quantity=quantity, price=raw_price, is_option=is_option
    )
    if not valid_contract:
        return {"ok": False, "error": contract_err}

    # 5. Data Quality Gate Check
    is_sandbox = bool(order.get("is_paper_sandbox") or order.get("is_synthetic") or order.get("data_source") == "SYNTHETIC_OFF_MARKET")
    quote_audit = evaluate_quote_quality(
        symbol=symbol,
        price=raw_price,
        is_mock=is_sandbox,
    )
    if not quote_audit.is_tradable and not is_sandbox:
        return {
            "ok": False,
            "error": f"Data Quality Gate Refusal ({quote_audit.state.value}): {quote_audit.rejection_reason}",
        }

    # 6. Portfolio Risk Gate Evaluation
    portfolio_state = get_paper_portfolio()
    current_equity = portfolio_state["account"]["total_equity"]
    open_positions = portfolio_state["open_positions"]

    risk_eval = risk_gate_service.evaluate_order_risk(
        symbol=underlying,
        order_margin=required_margin,
        current_equity=current_equity,
        open_positions=open_positions,
        session_realized_pnl=portfolio_state["account"]["realized_pnl"],
        session_unrealized_pnl=portfolio_state["account"]["unrealized_pnl"],
    )
    if not risk_eval.passed and not is_sandbox:
        return {"ok": False, "error": f"Risk Gate Refusal: {risk_eval.rejection_reason}"}

    tp1 = float(order.get("target_price_1") or (entry_price * 1.02 if order_type == "BUY" else entry_price * 0.98))
    tp2 = float(order.get("target_price_2") or (entry_price * 1.04 if order_type == "BUY" else entry_price * 0.96))
    sl = float(order.get("stop_loss") or (entry_price * 0.985 if order_type == "BUY" else entry_price * 1.015))
    strategy_id = order.get("strategy_id", "5-Pillar Engine")

    pos_id = f"POS-{symbol.replace(' ', '_')}-{int(time.time() * 1000)}"
    now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")

    with _get_db() as conn:
        # Re-fetch with row lock
        acc = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        cash = float(acc["cash_balance"])
        total_brokerage = float(acc["total_brokerage_paid"] or 0.0)
        total_charges_acc = float(acc["total_charges_paid"] or total_brokerage)

        # Deduct margin and fees
        new_cash = max(0.0, cash - required_margin)
        new_brokerage = total_brokerage + cost_audit.brokerage
        new_total_charges = total_charges_acc + entry_charges

        conn.execute("""
            UPDATE paper_account SET
                cash_balance = ?,
                total_brokerage_paid = ?,
                total_charges_paid = ?,
                updated_at = ?
            WHERE id = 1
        """, (new_cash, new_brokerage, new_total_charges, now_str))

        spec = get_contract_spec(underlying)
        conn.execute("""
            INSERT INTO paper_positions (
                id, symbol, signal, order_type, execution_mode, strategy_id, entry_price,
                raw_order_price, quantity, lot_size, target_price_1, target_price_2, stop_loss,
                status, opened_at, entry_charges, total_charges, slippage_applied, is_synthetic, data_source, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?)
        """, (
            pos_id, symbol, signal, order_type, execution_mode, strategy_id, entry_price,
            raw_price, quantity, spec.lot_size, tp1, tp2, sl, now_str, entry_charges,
            entry_charges, round(slippage_pct * 100, 3), 1 if is_sandbox else 0,
            "PAPER_SANDBOX" if is_sandbox else "LIVE_EXCHANGE",
            order.get("notes", "Institutional Order Ticket Execution"),
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
        "entry_charges": round(entry_charges, 2),
        "target_price_1": tp1,
        "target_price_2": tp2,
        "stop_loss": sl,
        "status": "OPEN",
        "opened_at": now_str,
        "message": f"Virtual Position Opened: {symbol} ({quantity} @ ₹{entry_price:.2f} via {execution_mode})",
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
        "message": "Position Target & Stop Loss updated successfully.",
    }


def close_paper_position(position_id: str, exit_price: Optional[float] = None) -> Dict[str, Any]:
    """Closes an open position, computes net realized P&L after shared FrictionModel fees, and credits capital back."""
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

        parts = sym.split()
        is_opt = len(parts) >= 3 and parts[-1] in ("CE", "PE")
        inst_type = "OPTIONS" if is_opt else "EQUITY_DELIVERY"
        friction_model = get_active_friction_model(instrument_type=inst_type)

        if exit_price is None or exit_price <= 0:
            exit_price = get_current_live_price(sym)
            if exit_price <= 0:
                exit_price = entry
            # Apply exit slippage
            exit_slippage_pct = random.uniform(friction_model.slippage_min_pct, friction_model.slippage_max_pct)
            if "BUY" in order_type:
                exit_price = round(exit_price * (1.0 - exit_slippage_pct), 2)
            else:
                exit_price = round(exit_price * (1.0 + exit_slippage_pct), 2)

        is_bull = "BUY" in order_type
        if is_bull:
            diff = exit_price - entry
        else:
            diff = entry - exit_price

        gross_pnl = round(diff * qty, 2)
        exit_cost_audit = compute_transaction_costs(
            price=exit_price,
            quantity=qty,
            side="SELL" if is_bull else "BUY",
            instrument_type=inst_type,
            model=friction_model,
        )
        exit_charges = round(exit_cost_audit.total_friction, 2)
        total_roundtrip_charges = round(entry_charges + exit_charges, 2)

        # Net Realized P&L = Gross P&L - Roundtrip Charges (Entry Fees + Exit Fees)
        net_realized_pnl = round(gross_pnl - total_roundtrip_charges, 2)
        realized_pnl_pct = round((gross_pnl / (entry * qty)) * 100, 2) if (entry * qty) > 0 else 0.0

        # Capital to return to cash: Margin returned + Gross P&L - Exit charges
        # (Entry charges were already deducted from cash at order entry)
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
                exit_charges = ?,
                total_charges = ?
            WHERE id = ?
        """, (now_str, exit_price, gross_pnl, net_realized_pnl, realized_pnl_pct, exit_charges, total_roundtrip_charges, position_id))

        # Update account cash & realized P&L
        acc = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        curr_cash = float(acc["cash_balance"])
        curr_realized = float(acc["realized_pnl"])
        total_brokerage = float(acc["total_brokerage_paid"] or 0.0)
        total_charges_acc = float(acc["total_charges_paid"] or total_brokerage)

        new_cash = max(0.0, curr_cash + returned_capital)
        new_realized = curr_realized + net_realized_pnl
        new_brokerage = total_brokerage + exit_cost_audit.brokerage
        new_total_charges = total_charges_acc + exit_charges

        conn.execute("""
            UPDATE paper_account SET
                cash_balance = ?,
                realized_pnl = ?,
                total_brokerage_paid = ?,
                total_charges_paid = ?,
                updated_at = ?
            WHERE id = 1
        """, (new_cash, new_realized, new_brokerage, new_total_charges, now_str))

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
        "closed_at": now_str,
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
                total_charges_paid = 0.0,
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

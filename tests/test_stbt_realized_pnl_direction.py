import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from evaluation_engine import evaluate_trade_outcome, enforce_direction_sanity
import app as appmod
from starlette.testclient import TestClient

def test_evaluation_engine_stbt_loss_pnl_direction():
    """When a stock under STBT (SELL) rises in price, realized_pnl_pct must be negative and outcome LOSS."""
    res = evaluate_trade_outcome(
        signal="STBT (SELL)",
        close_price_325=1837.30,
        open_price_915=1868.00,
        predicted_gap_pct=-1.5,
        symbol="SUNPHARMA",
    )
    assert res["gap_pct"] == 1.67
    assert res["realized_pnl_pct"] == -1.67
    assert res["outcome"] == "LOSS"

def test_evaluation_engine_stbt_win_pnl_direction():
    """When a stock under STBT (SELL) drops in price, realized_pnl_pct must be positive and outcome WIN/JACKPOT WIN."""
    res = evaluate_trade_outcome(
        signal="STBT (SELL)",
        close_price_325=36425.0,
        open_price_915=35655.0,
        predicted_gap_pct=-2.0,
        symbol="PAGEIND",
    )
    assert res["gap_pct"] == -2.11
    assert res["realized_pnl_pct"] == 2.11
    assert res["outcome"] == "JACKPOT WIN"

def test_evaluation_engine_btst_pnl_direction():
    """When a stock under BTST (BUY) rises, realized_pnl_pct is positive; when it falls, negative."""
    res_win = evaluate_trade_outcome(
        signal="BTST (BUY)",
        close_price_325=100.0,
        open_price_915=102.0,
        predicted_gap_pct=1.5,
        symbol="TESTWIN",
    )
    assert res_win["gap_pct"] == 2.0
    assert res_win["realized_pnl_pct"] == 2.0
    assert "WIN" in res_win["outcome"]

    res_loss = evaluate_trade_outcome(
        signal="BTST (BUY)",
        close_price_325=100.0,
        open_price_915=98.0,
        predicted_gap_pct=1.5,
        symbol="TESTLOSS",
    )
    assert res_loss["gap_pct"] == -2.0
    assert res_loss["realized_pnl_pct"] == -2.0
    assert res_loss["outcome"] == "LOSS"

def test_live_trades_api_returns_direction_adjusted_stbt_pnl():
    """Test that /api/live_trades returns direction-adjusted pnl_pct for closed trades."""
    client = TestClient(appmod.app)
    resp = client.get("/api/live_trades")
    assert resp.status_code == 200
    data = resp.json()
    closed = data.get("closed_trades", [])
    assert len(closed) > 0

    # Find the 5 STBT LOSS trades mentioned in the prompt
    target_symbols = {"SUNPHARMA", "ITC", "TCS", "NTPC", "RELIANCE"}
    found_targets = [t for t in closed if t["symbol"] in target_symbols and "STBT" in t["signal"] and t["outcome"] == "LOSS"]
    
    assert len(found_targets) >= 5, f"Expected at least 5 STBT LOSS trades, found {len(found_targets)}"
    
    for t in found_targets:
        sym = t["symbol"]
        pnl = t["pnl_pct"]
        entry = t["entry_price"]
        exit_p = t["exit_price"]
        assert exit_p > entry, f"{sym} exit ({exit_p}) should be greater than entry ({entry}) for a loss"
        assert pnl < 0, f"{sym} STBT LOSS must have negative realized P&L, got {pnl}%"

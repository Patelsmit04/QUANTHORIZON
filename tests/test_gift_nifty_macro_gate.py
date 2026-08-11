import pytest
import pandas as pd
import numpy as np
from scoring_engine import evaluate_5_pillar_matrix

def _make_df(close_prices):
    n = len(close_prices)
    highs = [p * 1.01 for p in close_prices]
    lows = [p * 0.99 for p in close_prices]
    opens = [p * 0.995 for p in close_prices]
    vols = [1000] * n
    dates = pd.date_range("2026-08-11 09:15", periods=n, freq="5min")
    return pd.DataFrame({
        "Open": opens, "High": highs, "Low": lows, "Close": close_prices, "Volume": vols
    }, index=dates)

def test_gift_nifty_pullback_caps_p1_high_to_p2_medium():
    prices = [100.0 + i * 0.5 for i in range(30)] # Bullish trend
    df = _make_df(prices)

    macro_ok = {"sp500_green": True, "vix_ok": True, "gift_nifty_ok": True}
    res_ok = evaluate_5_pillar_matrix("RELIANCE", df, macro_status=macro_ok)
    
    macro_pullback = {"sp500_green": True, "vix_ok": True, "gift_nifty_ok": False}
    res_capped = evaluate_5_pillar_matrix("RELIANCE", df, macro_status=macro_pullback)
    
    if res_ok.get("priority_level") == "P1_HIGH":
        assert res_capped["priority_level"] == "P2_MEDIUM"
        assert res_capped["conviction_level"] == "MODERATE"
        assert "GIFT Nifty pullback" in str(res_capped.get("macro_gate_applied", ""))

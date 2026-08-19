import pandas as pd
import numpy as np
from scoring_engine import evaluate_5_pillar_matrix
from block_deal_provider import aggregate_symbol_flows

def test_pillar1_short_buildup_requires_rising_oi():
    # Construct mock stock dataframe
    dates = pd.date_range("2026-08-10 09:15", periods=50, freq="5min")
    date_strings = [d.strftime("%Y-%m-%d") for d in dates]
    closes = np.linspace(100, 90, 50)  # Price dropping: ltp < vwap
    df_stock = pd.DataFrame({
        "Date": date_strings,
        "Open": closes + 0.1,
        "High": closes + 0.5,
        "Low": closes - 0.5,
        "Close": closes,
        "Volume": [1000] * 50
    }, index=dates)

    # 1. Rising OI (+5.0%) -> True Short Buildup (Must Confirm Pillar 1)
    oi_data_rising = {
        "source": "MOCK",
        "oi_pct_change": 5.0,
        "avg_10d_oi_pct": 2.0
    }
    res_rising = evaluate_5_pillar_matrix("RELIANCE", df_stock, oi_data=oi_data_rising)
    assert res_rising["pillar_weights"]["Pillar 1: Futures OI"] > 0
    assert any("OI Short Buildup" in p for p in res_rising["confirmed_pillars"])

    # 2. Falling OI (-5.0%) -> Long Unwinding (Must NOT Confirm Pillar 1)
    oi_data_falling = {
        "source": "MOCK",
        "oi_pct_change": -5.0,
        "avg_10d_oi_pct": 2.0
    }
    res_falling = evaluate_5_pillar_matrix("RELIANCE", df_stock, oi_data=oi_data_falling)
    assert res_falling["pillar_weights"]["Pillar 1: Futures OI"] == 0.0


def test_bulk_deal_10cr_threshold_triggers_weak_tier(monkeypatch):
    import block_deal_provider as bdp
    monkeypatch.setattr(bdp, "MIN_VALUE_CR", 10.0)
    records = [{
        "symbol": "RELIANCE",
        "side": "BUY",
        "value_cr": 12.5,
        "deal_type": "block"
    }]
    aggregated = aggregate_symbol_flows(records)
    assert "RELIANCE" in aggregated
    assert aggregated["RELIANCE"]["tier"] == "WEAK"
    assert aggregated["RELIANCE"]["net_value_cr"] == 12.5


def test_marubozu_85_pct_threshold():
    dates = pd.date_range("2026-08-10 09:15", periods=50, freq="5min")
    date_strings = [d.strftime("%Y-%m-%d") for d in dates]
    closes = np.linspace(100, 108.5, 50)  # Range position ~85%
    df_stock = pd.DataFrame({
        "Date": date_strings,
        "Open": closes - 0.1,
        "High": [110.0] * 50,
        "Low": [100.0] * 50,
        "Close": closes,
        "Volume": [1000] * 50
    }, index=dates)

    res = evaluate_5_pillar_matrix("RELIANCE", df_stock)
    assert res["pillar_weights"]["Pillar 5: Marubozu Close"] > 0
    assert any("Marubozu Close" in p for p in res["confirmed_pillars"])

import pandas as pd
import numpy as np
from scoring_engine import evaluate_5_pillar_matrix

def test_priority1_assigned_when_confidence_clears_85_and_weight_clears_required():
    dates = pd.date_range("2026-08-10 09:15", periods=50, freq="5min")
    date_strings = [d.strftime("%Y-%m-%d") for d in dates]
    closes = np.linspace(90, 100, 50)
    highs = closes.copy()
    highs[-1] = 100.0  # Close equals High -> Range position 100% (Marubozu Pillar 5 confirmed)
    lows = closes - 0.5
    lows[0] = 90.0

    vols = [1000] * 40 + [3000] * 10  # Late volume surge -> Volume surge Pillar 4 confirmed

    df_stock = pd.DataFrame({
        "Date": date_strings,
        "Open": closes - 0.1,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": vols
    }, index=dates)

    oi_data = {"source": "MOCK", "oi_pct_change": 5.0, "avg_10d_oi_pct": 2.0}
    delivery_data = {"source": "MOCK", "delivery_pct": 60.0, "avg_10d_delivery_pct": 40.0}

    # Clears P1_HIGH because weight >= required_pillars (3.0/3.0) AND confidence >= 85
    res = evaluate_5_pillar_matrix("RELIANCE", df_stock, oi_data=oi_data, delivery_data=delivery_data)
    assert res["confirmed_pillars_weight"] >= res["required_pillars"]
    assert res["confidence_score"] >= 85
    assert res["priority_level"] == "P1_HIGH"
    assert "priority_reason" in res
    assert "Priority 1" in res["priority_reason"]


def test_estimated_gap_is_clamped_to_max_3_5_pct():
    dates = pd.date_range("2026-08-10 09:15", periods=50, freq="5min")
    date_strings = [d.strftime("%Y-%m-%d") for d in dates]
    closes = np.linspace(90, 100, 50)
    df_stock = pd.DataFrame({
        "Date": date_strings,
        "Open": closes - 0.1,
        "High": closes + 0.5,
        "Low": closes - 0.5,
        "Close": closes,
        "Volume": [10000] * 50  # Extreme volume spike
    }, index=dates)

    res = evaluate_5_pillar_matrix("RELIANCE", df_stock)
    assert abs(res["predicted_gap_pct"]) <= 3.5
    assert abs(res["predicted_gap_pct"]) >= 0.5

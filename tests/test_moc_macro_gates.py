import pandas as pd
from scoring_engine import evaluate_5_pillar_matrix

SYMBOL = "RELIANCE"

def test_moc_single_spike_rejected():
    closes = [100.0 + i * 0.5 for i in range(20)]
    df = pd.DataFrame([
        {"Open": closes[i-1] if i > 0 else closes[0], "High": c + 0.3, "Low": c - 0.3, "Close": c, "Volume": 100000 if i == 19 else 50000}
        for i, c in enumerate(closes)
    ])
    result = evaluate_5_pillar_matrix(SYMBOL, df)
    # Single-bar 2.0x spike with persistence count 1 < 2 should be rejected from Pillar 4
    assert result["pillar_weights"]["Pillar 4: Volume Spike"] == 0.0


def test_moc_multi_bar_surge_confirmed():
    closes = [100.0 + i * 0.5 for i in range(20)]
    df = pd.DataFrame([
        {"Open": closes[i-1] if i > 0 else closes[0], "High": c + 0.3, "Low": c - 0.3, "Close": c, "Volume": 100000 if i >= 17 else 50000}
        for i, c in enumerate(closes)
    ])
    result = evaluate_5_pillar_matrix(SYMBOL, df)
    assert result["pillar_weights"]["Pillar 4: Volume Spike"] == 1.0


def test_global_macro_gate_caps_p1_high():
    closes = [100.0 + i * 0.5 for i in range(20)]
    df = pd.DataFrame([
        {"Open": closes[i-1] if i > 0 else closes[0], "High": c + 0.3, "Low": c - 0.3, "Close": c, "Volume": 100000 if i >= 17 else 50000}
        for i, c in enumerate(closes)
    ])
    macro_status = {"vix_ok": False, "sp500_green": False}
    result = evaluate_5_pillar_matrix(SYMBOL, df, required_weight_override=1.0, macro_status=macro_status)
    assert result["fundamental_quality"]["macro_gate_applied"] is not None
    assert result["priority_level"] == "P2_MEDIUM"

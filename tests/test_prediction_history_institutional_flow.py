"""
GET /api/history/predictions previously selected no pillar-level columns at all (see
signal_journal.get_prediction_history's SQL), even though pillar_1..6_confirmed are captured
per-signal — the History page had no way to filter "did Institutional Flow contribute to this
setup's score". Verifies pillar_6_confirmed now round-trips through as
institutional_flow_contributed.
"""
import os

import pytest

import signal_journal


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    data_dir = str(tmp_path / "data")
    db_file = os.path.join(data_dir, "signal_journal.db")
    monkeypatch.setattr(signal_journal, "DATA_DIR", data_dir)
    monkeypatch.setattr(signal_journal, "DB_FILE", db_file)
    signal_journal.init_journal_db()
    return db_file


def _fake_stock(symbol, pillar6_weight):
    return {
        "symbol": symbol, "raw_ticker": f"{symbol}.NS", "liquidity_tier": "TIER_1",
        "priority_level": "P1_HIGH", "signal": "BTST (BUY)", "option_type": "CALL (CE)",
        "confidence_score": 90, "ltp": 100.0, "predicted_gap_pct": 1.5, "vwap": 99.0,
        "volume_spike": 2.0, "rsi": 60.0, "range_position_pct": 98.0,
        "pillar_weights": {
            "Pillar 1: Futures OI": 1.0, "Pillar 2: Vol Persistence": 1.0,
            "Pillar 3: Relative Strength": 1.0, "Pillar 4: Volume Spike": 1.0,
            "Pillar 5: Marubozu Close": 1.0, "Pillar 6: Institutional Flow": pillar6_weight,
        },
        "confirmed_pillars_weight": 5.0 + pillar6_weight,
        "expiry_discount_applied": False,
    }


def test_prediction_history_reports_institutional_flow_contribution(isolated_db):
    signal_journal.log_signal_entry(_fake_stock("RELIANCE", pillar6_weight=1.5), strategy_id="default-5-pillar")
    signal_journal.log_signal_entry(_fake_stock("TCS", pillar6_weight=0.0), strategy_id="default-5-pillar")

    history = signal_journal.get_prediction_history(limit=10)
    by_symbol = {h["instrument"]: h for h in history}

    assert by_symbol["RELIANCE"]["institutional_flow_contributed"] is True
    assert by_symbol["TCS"]["institutional_flow_contributed"] is False

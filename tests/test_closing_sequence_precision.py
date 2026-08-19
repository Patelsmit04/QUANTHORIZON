import closing_sequence

def test_closing_sequence_auto_lock_325_and_market_lock_330_triggers(tmp_path, monkeypatch):
    monkeypatch.setattr(closing_sequence, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(closing_sequence, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(closing_sequence, "is_trading_holiday", lambda date: False)

    today = "2026-08-10"
    notifications = []

    import json
    scan_file = tmp_path / "last_market_scan.json"
    scan_file.write_text(json.dumps({"timestamp": f"{today} 15:10:00", "stocks": [{"symbol": "RELIANCE", "signal": "BTST (BUY)"}]}))

    import pandas as pd
    dummy_df = pd.DataFrame({"Close": [2500.0]}, index=pd.date_range("2026-08-10", periods=1))
    monkeypatch.setattr(closing_sequence.yf, "download", lambda *a, **k: dummy_df)

    def mock_broadcast(msg):
        notifications.append(msg)

    # 1. 3:14 PM IST -> Snapshot
    res_14 = closing_sequence.run_step_if_due(15 * 60 + 14, today, lambda: [{"symbol": "RELIANCE"}], lambda p: {}, mock_broadcast)
    assert res_14 == "snapshot"

    # 2. 3:25 PM IST -> Auto-lock picks snapshot
    res_25 = closing_sequence.run_step_if_due(15 * 60 + 25, today, lambda: [{"symbol": "RELIANCE"}], lambda p: {}, mock_broadcast)
    assert res_25 == "auto_lock_325"
    assert any(n.get("type") == "auto_lock_325_picks" for n in notifications)

    # 3. 3:30 PM IST -> Sharp 3:30 PM Market Bell Lock
    res_30 = closing_sequence.run_step_if_due(15 * 60 + 30, today, lambda: [{"symbol": "RELIANCE"}], lambda p: {}, mock_broadcast)
    assert res_30 == "market_lock_330"
    assert any(n.get("type") == "market_lock" and n.get("btst_status") == "confirmed" for n in notifications)

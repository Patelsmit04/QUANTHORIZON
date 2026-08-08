"""
Verifies app.py's institutional-flow notification wiring: the message format, that it flows
through the same log_notification()/ws_broadcast.broadcast_sync() path as the other 3
notification call sites, and that it's idempotent within a day (block_deal_provider.py's
get_newly_notifiable_flows/get_newly_notifiable_index_flow do the actual dedup — see
test_block_deal_provider.py — this file checks app.py wires them correctly).
"""
from unittest.mock import MagicMock

import pytest

import app as appmod
import block_deal_provider as bdp


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(bdp, "DAILY_FLOW_FILE", str(tmp_path / "institutional_flow_daily.json"))
    monkeypatch.setattr(bdp, "NOTIFIED_FLOWS_FILE", str(tmp_path / "institutional_flow_notified.json"))
    yield


@pytest.fixture
def fake_notification(monkeypatch):
    logged = []
    broadcast = []
    monkeypatch.setattr(appmod, "log_notification", lambda **kw: (logged.append(kw), {"id": "x", **kw})[1])
    monkeypatch.setattr(appmod.ws_broadcast, "broadcast_sync", lambda payload: broadcast.append(payload))
    return logged, broadcast


def test_notify_new_institutional_flows_fires_for_moderate_and_strong_only(fake_notification):
    logged, broadcast = fake_notification
    today_str = bdp.date.today().isoformat()
    aggregated = {
        "RELIANCE": {"symbol": "RELIANCE", "tier": "STRONG", "dominant_side": "BUY", "net_value_cr": 120.0},
        "TCS": {"symbol": "TCS", "tier": "WEAK", "dominant_side": "BUY", "net_value_cr": 30.0},
    }
    bdp._persist_snapshot(today_str, "live_trigger", aggregated, deals=[])

    appmod._notify_new_institutional_flows("live_trigger")

    assert len(logged) == 1
    assert logged[0]["title"] == "RELIANCE — Institutional Flow"
    assert logged[0]["message"] == "Strong Buy ₹120.0cr"
    assert logged[0]["notif_type"] == "institutional_flow"
    assert len(broadcast) == 1
    assert broadcast[0]["type"] == "notification"


def test_notify_new_institutional_flows_does_not_repeat_same_symbol(fake_notification):
    logged, broadcast = fake_notification
    today_str = bdp.date.today().isoformat()
    aggregated = {"RELIANCE": {"symbol": "RELIANCE", "tier": "STRONG", "dominant_side": "BUY", "net_value_cr": 120.0}}
    bdp._persist_snapshot(today_str, "live_trigger", aggregated, deals=[])

    appmod._notify_new_institutional_flows("live_trigger")
    appmod._notify_new_institutional_flows("live_trigger")  # same checkpoint checked again

    assert len(logged) == 1


def test_notify_new_index_institutional_flow_fires_for_directional_verdict_only(fake_notification):
    logged, broadcast = fake_notification

    appmod._notify_new_index_institutional_flow({"index_name": "NIFTY50", "status": "OK", "verdict": "NEUTRAL", "total_net_value_cr": 5.0})
    assert logged == []

    appmod._notify_new_index_institutional_flow({"index_name": "NIFTY50", "status": "OK", "verdict": "BEARISH", "total_net_value_cr": -85.0})
    assert len(logged) == 1
    assert logged[0]["title"] == "NIFTY50 — Institutional Flow"
    assert logged[0]["message"] == "Net Bearish ₹85.0cr across constituents"


def test_notify_new_institutional_flows_swallows_errors_without_raising(fake_notification, monkeypatch):
    monkeypatch.setattr(appmod, "get_aggregated_flow_for_today", lambda checkpoint: (_ for _ in ()).throw(RuntimeError("boom")))
    appmod._notify_new_institutional_flows("live_trigger")  # must not raise

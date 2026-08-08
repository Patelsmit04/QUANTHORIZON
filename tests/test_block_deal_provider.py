"""
Tests for block_deal_provider.py — tiering, aggregation, defensive parsing, disk-backed
checkpoint scheduling (idempotent per day, retries on failure instead of giving up), and
reconciliation classification.
"""
from datetime import date, datetime, timedelta

import pytest

import block_deal_provider as bdp


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(bdp, "DAILY_FLOW_FILE", str(tmp_path / "institutional_flow_daily.json"))
    monkeypatch.setattr(bdp, "RECONCILIATION_FILE", str(tmp_path / "institutional_flow_reconciliation.json"))
    monkeypatch.setattr(bdp, "CHECKPOINTS_META_FILE", str(tmp_path / "institutional_flow_checkpoints.json"))
    monkeypatch.setattr(bdp, "MIN_VALUE_CR", 25.0)
    monkeypatch.setattr(bdp, "TIER_MODERATE_CR", 50.0)
    monkeypatch.setattr(bdp, "TIER_STRONG_CR", 150.0)
    yield


# =========================================================================
# TIERING
# =========================================================================
def test_classify_tier_boundaries():
    assert bdp._classify_tier(24.99) == "BELOW_THRESHOLD"
    assert bdp._classify_tier(25.0) == "WEAK"
    assert bdp._classify_tier(49.99) == "WEAK"
    assert bdp._classify_tier(50.0) == "MODERATE"
    assert bdp._classify_tier(149.99) == "MODERATE"
    assert bdp._classify_tier(150.0) == "STRONG"


# =========================================================================
# DEFENSIVE KEY MATCHING
# =========================================================================
def test_pick_matches_regardless_of_case_and_punctuation():
    row = {"Buy/Sell": "BUY", "Quantity Traded": "1000", "Trade Price / Wtd. Avg. Price": "250.5"}
    assert bdp._pick(row, bdp._SIDE_KEYS) == "BUY"
    assert bdp._pick(row, bdp._QTY_KEYS) == "1000"
    assert bdp._pick(row, bdp._PRICE_KEYS) == "250.5"


def test_pick_returns_none_when_no_candidate_matches():
    row = {"SomeUnrelatedField": "x"}
    assert bdp._pick(row, bdp._SYMBOL_KEYS) is None


# =========================================================================
# PARSING — archive CSV shape (qty * price) and live JSON shape (direct value)
# =========================================================================
def test_parse_deal_records_computes_value_from_qty_and_price():
    rows = [{"Symbol": "RELIANCE", "Buy/Sell": "BUY", "Quantity Traded": "1000000", "Trade Price": "300"}]
    records = bdp._parse_deal_records(rows, "block")
    assert len(records) == 1
    # 1,000,000 * 300 = 30,00,00,000 = Rs 30 crore
    assert records[0] == {"symbol": "RELIANCE", "side": "BUY", "value_cr": 30.0, "deal_type": "block"}


def test_parse_deal_records_prefers_direct_value_field_when_present():
    rows = [{"symbol": "TCS", "buySell": "SELL", "tradeValue": "500000000"}]  # Rs 50cr, no qty/price needed
    records = bdp._parse_deal_records(rows, "bulk")
    assert records[0]["value_cr"] == 50.0
    assert records[0]["side"] == "SELL"


def test_parse_deal_records_skips_rows_missing_required_fields():
    rows = [{"symbol": "TCS"}, {"symbol": "INFY", "buySell": "BUY", "qty": "100"}]  # first missing side, second missing price
    records = bdp._parse_deal_records(rows, "bulk")
    assert records == []


def test_parse_deal_records_skips_unrecognized_side_value():
    rows = [{"symbol": "TCS", "buySell": "HOLD", "qty": "1000", "price": "100"}]
    assert bdp._parse_deal_records(rows, "bulk") == []


def test_extract_deal_rows_handles_plain_list_and_wrapped_dict():
    assert bdp._extract_deal_rows([{"symbol": "TCS"}]) == [{"symbol": "TCS"}]
    assert bdp._extract_deal_rows({"data": [{"symbol": "TCS"}]}) == [{"symbol": "TCS"}]
    assert bdp._extract_deal_rows({"unexpectedKey": [{"symbol": "TCS"}]}) == [{"symbol": "TCS"}]
    assert bdp._extract_deal_rows({"onlyScalars": 1}) is None
    assert bdp._extract_deal_rows("not a list or dict") is None


# =========================================================================
# DEDUPLICATION — found necessary via a live smoke test (Aug 2026): merging the bulk_deals and
# block_deals bandtype fetches produced exact-duplicate rows off-market.
# =========================================================================
def test_dedupe_records_collapses_exact_symbol_side_value_duplicates():
    records = [
        {"symbol": "EMIL", "side": "BUY", "value_cr": 40.0, "deal_type": "bulk"},
        {"symbol": "EMIL", "side": "BUY", "value_cr": 40.0, "deal_type": "block"},  # duplicate of the row above
        {"symbol": "EMIL", "side": "SELL", "value_cr": 15.0, "deal_type": "bulk"},
    ]
    deduped = bdp._dedupe_records(records)
    assert len(deduped) == 2
    assert {"symbol": "EMIL", "side": "BUY", "value_cr": 40.0, "deal_type": "bulk"} in deduped
    assert {"symbol": "EMIL", "side": "SELL", "value_cr": 15.0, "deal_type": "bulk"} in deduped


def test_dedupe_records_keeps_distinct_deals_with_different_values():
    records = [
        {"symbol": "EMIL", "side": "BUY", "value_cr": 40.0, "deal_type": "bulk"},
        {"symbol": "EMIL", "side": "BUY", "value_cr": 41.5, "deal_type": "block"},
    ]
    assert len(bdp._dedupe_records(records)) == 2


# =========================================================================
# AGGREGATION — same-day, same-symbol, net direction
# =========================================================================
def test_aggregate_symbol_flows_nets_buy_and_sell_and_picks_dominant_side():
    records = [
        {"symbol": "RELIANCE", "side": "BUY", "value_cr": 80.0, "deal_type": "block"},
        {"symbol": "RELIANCE", "side": "SELL", "value_cr": 30.0, "deal_type": "bulk"},
    ]
    agg = bdp.aggregate_symbol_flows(records, as_of="2026-08-07T14:30:00+05:30")
    entry = agg["RELIANCE"]
    assert entry["buy_value_cr"] == 80.0
    assert entry["sell_value_cr"] == 30.0
    assert entry["net_value_cr"] == 50.0
    assert entry["dominant_side"] == "BUY"
    assert entry["tier"] == "MODERATE"  # abs(net) = 50cr
    assert sorted(entry["deal_types"]) == ["block", "bulk"]


def test_aggregate_symbol_flows_excludes_symbols_below_threshold():
    records = [{"symbol": "SMALLCO", "side": "BUY", "value_cr": 10.0, "deal_type": "bulk"}]
    agg = bdp.aggregate_symbol_flows(records)
    assert "SMALLCO" not in agg


def test_aggregate_symbol_flows_dominant_side_none_when_net_is_zero():
    records = [
        {"symbol": "RELIANCE", "side": "BUY", "value_cr": 50.0, "deal_type": "block"},
        {"symbol": "RELIANCE", "side": "SELL", "value_cr": 50.0, "deal_type": "block"},
    ]
    agg = bdp.aggregate_symbol_flows(records)
    assert agg["RELIANCE"]["dominant_side"] == "NONE"


# =========================================================================
# PERSISTENCE / LOOKUP — same-day only, FAIL LOUD otherwise
# =========================================================================
def test_get_institutional_flow_data_returns_none_when_nothing_captured_today():
    assert bdp.get_institutional_flow_data("RELIANCE") is None


def test_get_institutional_flow_data_returns_todays_last_checkpoint():
    today_str = date.today().isoformat()
    aggregated = {"RELIANCE": {"symbol": "RELIANCE", "net_value_cr": 80.0, "dominant_side": "BUY", "tier": "MODERATE"}}
    bdp._persist_snapshot(today_str, "live_trigger", aggregated)

    result = bdp.get_institutional_flow_data("RELIANCE.NS")  # .NS suffix must be stripped
    assert result is not None
    assert result["net_value_cr"] == 80.0


def test_get_institutional_flow_data_ignores_stale_prior_day_entries():
    stale_date = (date.today() - timedelta(days=3)).isoformat()
    aggregated = {"RELIANCE": {"symbol": "RELIANCE", "net_value_cr": 80.0, "dominant_side": "BUY", "tier": "MODERATE"}}
    bdp._persist_snapshot(stale_date, "live_trigger", aggregated)

    assert bdp.get_institutional_flow_data("RELIANCE") is None


# =========================================================================
# RECONCILIATION
# =========================================================================
def test_run_eod_reconciliation_reports_archive_unavailable(monkeypatch):
    monkeypatch.setattr(bdp, "fetch_eod_archive_deals", lambda: None)
    result = bdp.run_eod_reconciliation()
    assert result["status"] == "ARCHIVE_UNAVAILABLE"


def test_run_eod_reconciliation_clean_when_live_and_archive_agree(monkeypatch):
    today_str = date.today().isoformat()
    live = {"RELIANCE": {"symbol": "RELIANCE", "net_value_cr": 80.0, "dominant_side": "BUY", "tier": "MODERATE"}}
    bdp._persist_snapshot(today_str, "live_trigger", live)
    monkeypatch.setattr(bdp, "fetch_eod_archive_deals", lambda: {
        "RELIANCE": {"symbol": "RELIANCE", "net_value_cr": 80.0, "dominant_side": "BUY", "tier": "MODERATE"}
    })

    result = bdp.run_eod_reconciliation()
    assert result["status"] == "CLEAN"


def test_run_eod_reconciliation_flags_value_mismatch(monkeypatch):
    today_str = date.today().isoformat()
    live = {"RELIANCE": {"symbol": "RELIANCE", "net_value_cr": 80.0, "dominant_side": "BUY", "tier": "MODERATE"}}
    bdp._persist_snapshot(today_str, "live_trigger", live)
    monkeypatch.setattr(bdp, "fetch_eod_archive_deals", lambda: {
        "RELIANCE": {"symbol": "RELIANCE", "net_value_cr": 200.0, "dominant_side": "BUY", "tier": "STRONG"}
    })

    result = bdp.run_eod_reconciliation()
    assert result["status"] == "DISCREPANCIES_FOUND"
    assert result["value_mismatches"][0]["symbol"] == "RELIANCE"


# =========================================================================
# SCHEDULING — no-op outside windows, idempotent per day, retries on failure
# =========================================================================
def _set_ist_now(monkeypatch, dt):
    monkeypatch.setattr(bdp, "_ist_now", lambda: dt)


def test_checkpoint_noop_before_any_trigger_time(monkeypatch):
    _set_ist_now(monkeypatch, datetime(2026, 8, 7, 10, 0))  # Friday, 10 AM — before 14:30
    monkeypatch.setattr(bdp, "fetch_live_large_deals", lambda: (_ for _ in ()).throw(AssertionError("should not fetch yet")))
    assert bdp.maybe_run_institutional_flow_checkpoints() is None


def test_checkpoint_noop_on_weekend(monkeypatch):
    _set_ist_now(monkeypatch, datetime(2026, 8, 8, 15, 0))  # Saturday
    assert bdp.maybe_run_institutional_flow_checkpoints() is None


def test_live_trigger_checkpoint_fires_once_after_window(monkeypatch):
    _set_ist_now(monkeypatch, datetime(2026, 8, 7, 14, 35))  # Friday, past 14:30
    calls = {"n": 0}

    def fake_fetch():
        calls["n"] += 1
        return {"RELIANCE": {"symbol": "RELIANCE", "net_value_cr": 80.0, "dominant_side": "BUY", "tier": "MODERATE"}}

    monkeypatch.setattr(bdp, "fetch_live_large_deals", fake_fetch)

    ran = bdp.maybe_run_institutional_flow_checkpoints()
    assert ran == "live_trigger"
    assert calls["n"] == 1

    # Second tick at the same time: live_trigger is already done today, and final_check (15:15)
    # isn't due yet at 14:35 — must be a no-op, not a re-fetch.
    ran_again = bdp.maybe_run_institutional_flow_checkpoints()
    assert ran_again is None
    assert calls["n"] == 1


def test_failed_fetch_is_not_marked_done_and_retries_next_tick(monkeypatch):
    _set_ist_now(monkeypatch, datetime(2026, 8, 7, 14, 35))
    monkeypatch.setattr(bdp, "fetch_live_large_deals", lambda: None)  # simulated total failure

    ran = bdp.maybe_run_institutional_flow_checkpoints()
    assert ran is None  # nothing succeeded this tick
    assert bdp._checkpoint_done_today("live_trigger", "2026-08-07") is False

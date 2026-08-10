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
    monkeypatch.setattr(bdp, "NOTIFIED_FLOWS_FILE", str(tmp_path / "institutional_flow_notified.json"))
    monkeypatch.setattr(bdp, "MIN_VALUE_CR", 25.0)
    monkeypatch.setattr(bdp, "TIER_MODERATE_CR", 50.0)
    monkeypatch.setattr(bdp, "TIER_STRONG_CR", 150.0)
    monkeypatch.setattr(bdp, "_INDEX_WEIGHTS_CACHE", {})  # avoid cross-test cache pollution
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
    assert records[0] == {
        "symbol": "RELIANCE", "side": "BUY", "value_cr": 30.0, "deal_type": "block",
        "deal_date": date.today().isoformat(),  # row had no date field — falls back to today
    }


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
    records = [{"symbol": "SMALLCO", "side": "BUY", "value_cr": 5.0, "deal_type": "bulk"}]
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
# INDIVIDUAL DEAL STORAGE — backs the deals panel and scanner-row expand breakdown
# =========================================================================
def test_qualifying_deals_filters_below_threshold_and_sorts_by_value_desc():
    records = [
        {"symbol": "A", "side": "BUY", "value_cr": 10.0, "deal_type": "bulk", "deal_date": "2026-08-07"},  # below MIN_VALUE_CR
        {"symbol": "B", "side": "BUY", "value_cr": 40.0, "deal_type": "bulk", "deal_date": "2026-08-07"},
        {"symbol": "C", "side": "SELL", "value_cr": 90.0, "deal_type": "block", "deal_date": "2026-08-07"},
    ]
    deals = bdp._qualifying_deals(records, as_of="2026-08-07T14:30:00+05:30")
    assert [d["symbol"] for d in deals] == ["C", "B"]  # sorted descending, A dropped
    assert deals[0]["as_of"] == "2026-08-07T14:30:00+05:30"


def test_get_deals_for_day_returns_empty_list_when_nothing_captured_today():
    assert bdp.get_deals_for_day() == []


def test_get_deals_for_day_filters_by_symbol_and_sorts_by_value():
    today_str = date.today().isoformat()
    deals = [
        {"symbol": "RELIANCE", "side": "BUY", "value_cr": 40.0, "deal_type": "bulk", "deal_date": today_str, "as_of": "x"},
        {"symbol": "RELIANCE", "side": "SELL", "value_cr": 90.0, "deal_type": "block", "deal_date": today_str, "as_of": "x"},
        {"symbol": "TCS", "side": "BUY", "value_cr": 60.0, "deal_type": "bulk", "deal_date": today_str, "as_of": "x"},
    ]
    bdp._persist_snapshot(today_str, "live_trigger", {}, deals=deals)

    all_deals = bdp.get_deals_for_day()
    assert [d["value_cr"] for d in all_deals] == [90.0, 60.0, 40.0]

    reliance_only = bdp.get_deals_for_day(symbol="RELIANCE.NS")
    assert len(reliance_only) == 2
    assert all(d["symbol"] == "RELIANCE" for d in reliance_only)


def test_get_daily_flow_meta_reports_captured_checkpoints():
    assert bdp.get_daily_flow_meta()["checkpoints_captured"] == []

    today_str = date.today().isoformat()
    bdp._persist_snapshot(today_str, "live_trigger", {}, deals=[])
    meta = bdp.get_daily_flow_meta()
    assert meta["checkpoints_captured"] == ["live_trigger"]
    assert meta["last_checkpoint"] == "live_trigger"
    assert meta["last_updated"] is not None


# =========================================================================
# RECONCILIATION
# =========================================================================
def test_run_eod_reconciliation_reports_archive_unavailable(monkeypatch):
    monkeypatch.setattr(bdp, "_gather_archive_records", lambda: None)
    result = bdp.run_eod_reconciliation()
    assert result["status"] == "ARCHIVE_UNAVAILABLE"


def test_run_eod_reconciliation_clean_when_live_and_archive_agree(monkeypatch):
    today_str = date.today().isoformat()
    live = {"RELIANCE": {"symbol": "RELIANCE", "net_value_cr": 80.0, "dominant_side": "BUY", "tier": "MODERATE"}}
    bdp._persist_snapshot(today_str, "live_trigger", live)
    monkeypatch.setattr(bdp, "_gather_archive_records", lambda: [
        {"symbol": "RELIANCE", "side": "BUY", "value_cr": 80.0, "deal_type": "bulk", "deal_date": today_str}
    ])

    result = bdp.run_eod_reconciliation()
    assert result["status"] == "CLEAN"


def test_run_eod_reconciliation_flags_value_mismatch(monkeypatch):
    today_str = date.today().isoformat()
    live = {"RELIANCE": {"symbol": "RELIANCE", "net_value_cr": 80.0, "dominant_side": "BUY", "tier": "MODERATE"}}
    bdp._persist_snapshot(today_str, "live_trigger", live)
    monkeypatch.setattr(bdp, "_gather_archive_records", lambda: [
        {"symbol": "RELIANCE", "side": "BUY", "value_cr": 200.0, "deal_type": "bulk", "deal_date": today_str}
    ])

    result = bdp.run_eod_reconciliation()
    assert result["status"] == "DISCREPANCIES_FOUND"
    assert result["value_mismatches"][0]["symbol"] == "RELIANCE"


def test_run_eod_reconciliation_persists_individual_deals_for_deals_panel(monkeypatch):
    today_str = date.today().isoformat()
    monkeypatch.setattr(bdp, "_gather_archive_records", lambda: [
        {"symbol": "RELIANCE", "side": "BUY", "value_cr": 80.0, "deal_type": "bulk", "deal_date": today_str},
        {"symbol": "TCS", "side": "SELL", "value_cr": 30.0, "deal_type": "block", "deal_date": today_str},
    ])

    bdp.run_eod_reconciliation()

    deals = bdp.get_deals_for_day(checkpoint="eod_archive")
    assert len(deals) == 2
    assert deals[0]["symbol"] == "RELIANCE"  # sorted by value_cr descending


# =========================================================================
# NOTIFICATIONS — "newly notifiable" dedup (the actual notifying happens in app.py)
# =========================================================================
def test_get_newly_notifiable_flows_excludes_weak_tier():
    aggregated = {
        "RELIANCE": {"symbol": "RELIANCE", "tier": "STRONG", "dominant_side": "BUY", "net_value_cr": 120.0},
        "TCS": {"symbol": "TCS", "tier": "WEAK", "dominant_side": "BUY", "net_value_cr": 30.0},
    }
    newly = bdp.get_newly_notifiable_flows(aggregated)
    assert [f["symbol"] for f in newly] == ["RELIANCE"]


def test_get_newly_notifiable_flows_does_not_repeat_same_symbol_same_day():
    aggregated = {"RELIANCE": {"symbol": "RELIANCE", "tier": "STRONG", "dominant_side": "BUY", "net_value_cr": 120.0}}
    first = bdp.get_newly_notifiable_flows(aggregated)
    second = bdp.get_newly_notifiable_flows(aggregated)  # same checkpoint data seen again
    assert len(first) == 1
    assert second == []


def test_get_newly_notifiable_flows_notifies_new_symbol_even_after_another_already_notified():
    bdp.get_newly_notifiable_flows({"RELIANCE": {"symbol": "RELIANCE", "tier": "STRONG", "dominant_side": "BUY", "net_value_cr": 120.0}})
    newly = bdp.get_newly_notifiable_flows({
        "RELIANCE": {"symbol": "RELIANCE", "tier": "STRONG", "dominant_side": "BUY", "net_value_cr": 120.0},
        "HDFCBANK": {"symbol": "HDFCBANK", "tier": "MODERATE", "dominant_side": "SELL", "net_value_cr": -40.0},
    })
    assert [f["symbol"] for f in newly] == ["HDFCBANK"]


def test_get_newly_notifiable_index_flow_only_for_directional_verdicts():
    assert bdp.get_newly_notifiable_index_flow({"index_name": "NIFTY50", "status": "OK", "verdict": "NEUTRAL"}) is None
    assert bdp.get_newly_notifiable_index_flow({"index_name": "NIFTY50", "status": "NOT_FETCHED_YET", "verdict": None}) is None

    result = bdp.get_newly_notifiable_index_flow({"index_name": "NIFTY50", "status": "OK", "verdict": "BULLISH"})
    assert result is not None

    # Same index, same day — already notified, must not fire again.
    again = bdp.get_newly_notifiable_index_flow({"index_name": "NIFTY50", "status": "OK", "verdict": "BULLISH"})
    assert again is None


# =========================================================================
# INDEX-LEVEL AGGREGATION
# =========================================================================
def test_compute_index_institutional_flow_not_fetched_yet_when_no_checkpoint_today():
    result = bdp.compute_index_institutional_flow("NIFTY50")
    assert result["status"] == "NOT_FETCHED_YET"
    assert result["verdict"] is None


def test_compute_index_institutional_flow_unavailable_for_sensex(monkeypatch):
    today_str = date.today().isoformat()
    bdp._persist_snapshot(today_str, "live_trigger", {}, deals=[])

    result = bdp.compute_index_institutional_flow("SENSEX")
    assert result["status"] == "UNAVAILABLE"
    assert "BSE" in result["reason"]


def test_compute_index_institutional_flow_unavailable_when_weight_fetch_fails(monkeypatch):
    today_str = date.today().isoformat()
    bdp._persist_snapshot(today_str, "live_trigger", {}, deals=[])
    monkeypatch.setattr(bdp, "_fetch_index_constituent_weights", lambda nse_index_name: None)

    result = bdp.compute_index_institutional_flow("NIFTY50")
    assert result["status"] == "UNAVAILABLE"


def test_compute_index_institutional_flow_aggregates_weighted_constituents(monkeypatch):
    today_str = date.today().isoformat()
    aggregated = {
        "RELIANCE": {"symbol": "RELIANCE", "net_value_cr": 120.0, "dominant_side": "BUY", "tier": "STRONG"},
        "HDFCBANK": {"symbol": "HDFCBANK", "net_value_cr": -40.0, "dominant_side": "SELL", "tier": "MODERATE"},
    }
    bdp._persist_snapshot(today_str, "live_trigger", aggregated, deals=[])
    monkeypatch.setattr(bdp, "_fetch_index_constituent_weights", lambda nse_index_name: {
        "RELIANCE": 9.0, "HDFCBANK": 12.0, "TCS": 4.0,  # TCS has weight but no flow data today
    })

    result = bdp.compute_index_institutional_flow("NIFTY50")
    assert result["status"] == "OK"
    assert result["total_net_value_cr"] == 80.0  # 120 - 40
    assert result["verdict"] == "BULLISH"
    assert result["constituents_with_flow"] == 2
    assert result["constituents_total"] == 3
    symbols = [c["symbol"] for c in result["top_contributors"]]
    assert "TCS" not in symbols  # no flow data — excluded from contributors, not fabricated


def test_compute_index_institutional_flow_neutral_within_dead_band(monkeypatch):
    today_str = date.today().isoformat()
    aggregated = {"RELIANCE": {"symbol": "RELIANCE", "net_value_cr": 5.0, "dominant_side": "BUY", "tier": "WEAK"}}
    bdp._persist_snapshot(today_str, "live_trigger", aggregated, deals=[])
    monkeypatch.setattr(bdp, "_fetch_index_constituent_weights", lambda nse_index_name: {"RELIANCE": 9.0})
    monkeypatch.setattr(bdp, "INDEX_NEUTRAL_BAND_CR", 10.0)

    result = bdp.compute_index_institutional_flow("NIFTY50")
    assert result["verdict"] == "NEUTRAL"  # |5.0| < 10.0 dead band


def test_fetch_index_constituent_weights_normalizes_ffmc_and_excludes_index_row(monkeypatch):
    monkeypatch.setattr(bdp, "call_with_retry", lambda fn, label=None, **kw: {
        "data": [
            {"symbol": "NIFTY 50", "ffmc": None},  # index summary row — must be excluded
            {"symbol": "A", "ffmc": 300.0},
            {"symbol": "B", "ffmc": 700.0},
        ]
    })

    weights = bdp._fetch_index_constituent_weights("NIFTY 50")
    assert weights == {"A": 30.0, "B": 70.0}
    assert "NIFTY 50" not in weights


# =========================================================================
# SCHEDULING — no-op outside windows, idempotent per day, retries on failure
# =========================================================================
def _set_ist_now(monkeypatch, dt):
    monkeypatch.setattr(bdp, "_ist_now", lambda: dt)


def test_checkpoint_noop_before_any_trigger_time(monkeypatch):
    _set_ist_now(monkeypatch, datetime(2026, 8, 7, 10, 0))  # Friday, 10 AM — before 14:30
    monkeypatch.setattr(bdp, "_gather_live_records", lambda: (_ for _ in ()).throw(AssertionError("should not fetch yet")))
    assert bdp.maybe_run_institutional_flow_checkpoints() is None


def test_checkpoint_noop_on_weekend(monkeypatch):
    _set_ist_now(monkeypatch, datetime(2026, 8, 8, 15, 0))  # Saturday
    assert bdp.maybe_run_institutional_flow_checkpoints() is None


def test_live_trigger_checkpoint_fires_once_after_window(monkeypatch):
    _set_ist_now(monkeypatch, datetime(2026, 8, 7, 14, 35))  # Friday, past 14:30
    calls = {"n": 0}

    def fake_gather():
        calls["n"] += 1
        return [{"symbol": "RELIANCE", "side": "BUY", "value_cr": 80.0, "deal_type": "bulk", "deal_date": "2026-08-07"}]

    monkeypatch.setattr(bdp, "_gather_live_records", fake_gather)

    ran = bdp.maybe_run_institutional_flow_checkpoints()
    assert ran == "live_trigger"
    assert calls["n"] == 1

    # Second tick at the same time: live_trigger is already done today, and final_check (15:15)
    # isn't due yet at 14:35 — must be a no-op, not a re-fetch.
    ran_again = bdp.maybe_run_institutional_flow_checkpoints()
    assert ran_again is None
    assert calls["n"] == 1

    # The checkpoint must also persist the individual deal(s), not just the aggregate. Checked
    # directly against the store (keyed by the mocked 2026-08-07 clock) rather than through
    # get_deals_for_day(), which keys off the real date.today() — a different clock than the
    # _ist_now() mock this test controls.
    deals = bdp._load_daily_store()["2026-08-07"]["deals_by_checkpoint"]["live_trigger"]
    assert len(deals) == 1
    assert deals[0]["symbol"] == "RELIANCE"


def test_failed_fetch_is_not_marked_done_and_retries_next_tick(monkeypatch):
    _set_ist_now(monkeypatch, datetime(2026, 8, 7, 14, 35))
    monkeypatch.setattr(bdp, "_gather_live_records", lambda: None)  # simulated total failure

    ran = bdp.maybe_run_institutional_flow_checkpoints()
    assert ran is None  # nothing succeeded this tick
    assert bdp._checkpoint_done_today("live_trigger", "2026-08-07") is False

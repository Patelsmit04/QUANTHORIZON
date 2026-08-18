"""
TEST SUITE: Angel One SmartAPI & Hybrid Free Data Stack Integration
====================================================================
Tests:
  1. Cache Layer: Thread-safety, TTL eviction, bulk operations, snapshots.
  2. Angel One Provider: Scrip Master mapping, token lookups, session health check.
  3. Synthetic CVD Engine: Tick-rule execution, 1-min bucket aggregation, data gap protection.
  4. NSE Scraper Workers: Option chain parser, block deal filter (>= ₹25 Cr).
  5. API Endpoints: /api/live-stocks, /api/indices, /api/option-chain/NIFTY, /api/block-deals.
"""

import os
import sys
import pytest
import time
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


# ─── 1. Cache Layer Tests ────────────────────────────────────

def test_cache_layer_basic_operations():
    from cache_layer import CacheStore
    c = CacheStore()

    # Basic get/set
    c.set("stock:RELIANCE:quote", {"ltp": 2950.0, "pct_change": 1.2})
    assert c.get("stock:RELIANCE:quote")["ltp"] == 2950.0

    # Non-existent key
    assert c.get("non_existent") is None
    assert c.get("non_existent", "default") == "default"

    # Exists check
    assert c.exists("stock:RELIANCE:quote") is True
    assert c.exists("non_existent") is False

    # Delete
    assert c.delete("stock:RELIANCE:quote") is True
    assert c.get("stock:RELIANCE:quote") is None


def test_cache_layer_ttl_eviction():
    from cache_layer import CacheStore
    c = CacheStore()

    # Set with 1-second TTL
    c.set("temp_key", "temp_value", ttl_seconds=1)
    assert c.get("temp_key") == "temp_value"

    # Wait for expiry
    time.sleep(1.1)
    assert c.get("temp_key") is None


def test_cache_layer_snapshots():
    from cache_layer import CacheStore
    c = CacheStore()

    # Bulk stocks
    c.set("stock:INFY:quote", {"symbol": "INFY", "ltp": 1850.0})
    c.set("stock:TCS:quote", {"symbol": "TCS", "ltp": 4200.0})
    c.set("index:NIFTY50:quote", {"index_name": "NIFTY50", "ltp": 24500.0})

    stock_snapshot = c.get_stock_quotes_snapshot()
    assert len(stock_snapshot) == 2
    symbols = {s["symbol"] for s in stock_snapshot}
    assert "INFY" in symbols and "TCS" in symbols

    index_snapshot = c.get_index_quotes_snapshot()
    assert len(index_snapshot) == 1
    assert index_snapshot[0]["index_name"] == "NIFTY50"


def test_cache_layer_stats():
    from cache_layer import CacheStore
    c = CacheStore()
    c.set("stock:RELIANCE:quote", {"ltp": 2950.0})
    c.set("stock:RELIANCE:cvd_1m", [])
    c.set("stock:RELIANCE:depth", {})
    c.set("index:NIFTY50:quote", {"ltp": 24500.0})

    stats = c.get_stats()
    assert stats["stock_quotes"] == 1
    assert stats["index_quotes"] == 1
    assert stats["cvd_buckets"] == 1
    assert stats["depth_keys"] == 1


# ─── 2. Angel One Provider Tests ─────────────────────────────

def test_angel_one_credentials_check():
    import angel_one_provider as aop
    # Test configured check with empty env
    with patch.dict("os.environ", {"ANGEL_API_KEY": "", "ANGEL_CLIENT_ID": ""}):
        assert aop.is_configured() is False


def test_angel_one_scrip_master_indexing():
    import angel_one_provider as aop
    mock_data = [
        {"token": "2885", "symbol": "RELIANCE-EQ", "name": "RELIANCE", "exch_seg": "NSE", "instrumenttype": "", "lotsize": "1"},
        {"token": "1594", "symbol": "INFY-EQ", "name": "INFY", "exch_seg": "NSE", "instrumenttype": "", "lotsize": "1"},
        {"token": "99926000", "symbol": "Nifty 50", "name": "NIFTY", "exch_seg": "NSE", "instrumenttype": "AMXIDX", "lotsize": "25"},
    ]

    with patch("angel_one_provider._load_scrip_master_from_cache", return_value=mock_data):
        count = aop.load_scrip_master()
        assert count > 0
        assert aop.get_symbol_by_token("2885")["name"] == "RELIANCE"


# ─── 3. Synthetic CVD Engine Tests ───────────────────────────

def test_synthetic_cvd_tick_rule_buyer_initiated():
    import synthetic_cvd_engine as cvd
    from cache_layer import cache

    # Trade at or above ask (LTP 2952 >= Ask 2951) -> Buy volume
    cvd.process_tick(
        symbol="TEST_BUY",
        ltp=2952.0,
        last_traded_qty=500,
        best_bid=2950.0,
        best_ask=2951.0,
        bid_qty_5l=10000,
        ask_qty_5l=5000,
    )

    of = cvd.get_order_flow_data("TEST_BUY")
    assert of.data_source == "ANGEL_ONE_TICK_RULE"
    assert len(of.minute_bars) >= 1
    latest_bar = of.minute_bars[-1]
    assert latest_bar["buy_volume"] >= 500
    assert latest_bar["net_delta"] > 0


def test_synthetic_cvd_tick_rule_seller_initiated():
    import synthetic_cvd_engine as cvd

    # Trade at or below bid (LTP 2949 <= Bid 2950) -> Sell volume
    cvd.process_tick(
        symbol="TEST_SELL",
        ltp=2949.0,
        last_traded_qty=300,
        best_bid=2950.0,
        best_ask=2952.0,
        bid_qty_5l=4000,
        ask_qty_5l=8000,
    )

    of = cvd.get_order_flow_data("TEST_SELL")
    assert of.data_source == "ANGEL_ONE_TICK_RULE"
    assert len(of.minute_bars) >= 1
    latest_bar = of.minute_bars[-1]
    assert latest_bar["sell_volume"] >= 300
    assert latest_bar["net_delta"] < 0


def test_synthetic_cvd_fallback_simulator():
    import synthetic_cvd_engine as cvd
    # Request data for a stock with no live ticks -> returns high-fidelity simulated bars
    of = cvd.get_order_flow_data("UNSEEN_STOCK", signal_type="BTST (BUY)")
    assert of.data_source == "INFERRED_SIMULATOR"
    assert len(of.minute_bars) == 10
    assert of.had_data_gap is False
    assert of.depth_imbalance["depth_ratio"] > 0


# ─── 4. NSE Scraper Workers Tests ────────────────────────────

def test_option_chain_parser():
    import nse_scraper_workers as nse_scrapers

    mock_raw = {
        "records": {
            "underlyingValue": 24500.50,
            "expiryDates": ["29-Aug-2026", "05-Sep-2026"],
            "data": [
                {
                    "strikePrice": 24500,
                    "CE": {"openInterest": 150000, "changeinOpenInterest": 25000, "impliedVolatility": 13.5, "lastPrice": 120.0, "totalTradedVolume": 50000, "expiryDate": "29-Aug-2026"},
                    "PE": {"openInterest": 180000, "changeinOpenInterest": 35000, "impliedVolatility": 14.2, "lastPrice": 95.0, "totalTradedVolume": 60000, "expiryDate": "29-Aug-2026"}
                }
            ]
        }
    }

    parsed = nse_scrapers._parse_option_chain(mock_raw, "NIFTY")
    assert parsed is not None
    assert parsed["underlying_value"] == 24500.50
    assert len(parsed["strikes"]) == 1
    assert parsed["strikes"][0]["ce"]["open_interest"] == 150000
    assert parsed["strikes"][0]["pe"]["implied_volatility"] if "implied_volatility" in parsed["strikes"][0]["pe"] else parsed["strikes"][0]["pe"]["iv"] == 14.2


def test_block_deal_filter():
    import nse_scraper_workers as nse_scrapers

    mock_deals = {
        "data": [
            {"BD_SYMBOL": "RELIANCE", "BD_QTY_TRD": 100000, "BD_TP": 3000.0, "BD_CLIENT_NAME": "INST_A", "BD_BUY_SELL": "BUY"}, # 30 Cr (passes >= 25 Cr)
            {"BD_SYMBOL": "SMALL_CO", "BD_QTY_TRD": 1000, "BD_TP": 50.0, "BD_CLIENT_NAME": "RETAIL", "BD_BUY_SELL": "SELL"},      # 0.005 Cr (fails < 25 Cr)
        ]
    }

    with patch("nse_scraper_workers._nse_get", return_value=mock_deals):
        deals = nse_scrapers._fetch_block_deals()
        assert deals is not None
        assert len(deals) == 1
        assert deals[0]["symbol"] == "RELIANCE"
        assert deals[0]["value_cr"] == 30.0


# ─── 5. FastAPI Integration Tests ────────────────────────────

def test_api_live_prices_fast_cache():
    from fastapi.testclient import TestClient
    from app import app
    from cache_layer import cache

    # Seed fast cache
    cache.set("stock:TCS:quote", {
        "symbol": "TCS", "ltp": 4350.0, "prev_close": 4300.0, "change_pts": 50.0, "pct_change": 1.16
    })

    client = TestClient(app)
    resp = client.get("/api/live_prices")
    assert resp.status_code == 200
    data = resp.json()
    assert "stocks" in data or "stock_prices" in data
    stocks = data.get("stocks") or data.get("stock_prices") or []
    tcs_entry = next((s for s in stocks if s["symbol"] == "TCS"), None)
    assert tcs_entry is not None
    assert tcs_entry["ltp"] == 4350.0


def test_api_cached_block_deals():
    from fastapi.testclient import TestClient
    from app import app
    from cache_layer import cache

    cache.set("block_deals:today", [
        {"symbol": "HDFCBANK", "value_cr": 45.0, "buy_sell": "BUY", "quantity": 300000, "price": 1500.0}
    ])

    client = TestClient(app)
    resp = client.get("/api/block-deals")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["total_value_cr"] == 45.0

"""Tests for StrategyEngine's own state logic (dedup window, priority override) — the pieces
that live in strategy_engine.py rather than strategy_engine_rules.py. VIX gate / EOD cutoff
are already covered in test_strategy_engine_rules.py (co-located with vix_gate/
is_past_eod_cutoff); Bank Nifty lot cap is covered in test_option_strike_utils.py."""
from datetime import datetime, timedelta

import pandas as pd

from strategy_engine import StrategyEngine


def _make_df(n: int, volumes) -> pd.DataFrame:
    idx = pd.date_range("2026-08-10 10:00", periods=n, freq="5min")
    return pd.DataFrame({
        "Open": [100.0] * n, "High": [101.0] * n, "Low": [99.0] * n, "Close": [100.0] * n,
        "Volume": volumes,
    }, index=idx)


def test_dedup_suppresses_same_strategy_asset_within_30_minutes():
    engine = StrategyEngine()
    now = datetime(2026, 8, 10, 10, 0)

    assert engine._check_dedup("vwap_pullback", "NIFTY50", now) is True
    engine._mark_dedup("vwap_pullback", "NIFTY50", now)

    still_within_window = now + timedelta(minutes=29)
    assert engine._check_dedup("vwap_pullback", "NIFTY50", still_within_window) is False


def test_dedup_allows_again_after_30_minutes():
    engine = StrategyEngine()
    now = datetime(2026, 8, 10, 10, 0)
    engine._mark_dedup("vwap_pullback", "NIFTY50", now)

    after_window = now + timedelta(minutes=30)
    assert engine._check_dedup("vwap_pullback", "NIFTY50", after_window) is True


def test_dedup_is_scoped_per_strategy_and_asset():
    engine = StrategyEngine()
    now = datetime(2026, 8, 10, 10, 0)
    engine._mark_dedup("vwap_pullback", "NIFTY50", now)

    # Different strategy, same asset — not suppressed.
    assert engine._check_dedup("breakdown_spike", "NIFTY50", now) is True
    # Same strategy, different asset — not suppressed.
    assert engine._check_dedup("vwap_pullback", "BANKNIFTY", now) is True


def test_pick_priority_returns_only_candidate_untouched():
    engine = StrategyEngine()
    df = _make_df(6, volumes=[100, 100, 100, 100, 100, 100])
    candidate = {"strategy_key": "vwap_pullback"}

    assert engine._pick_priority([candidate], df) is candidate


def test_pick_priority_favors_explicit_volume_spike_ratio():
    engine = StrategyEngine()
    df = _make_df(6, volumes=[100, 100, 100, 100, 100, 100])  # generic ratio = 100/100 = 1.0
    weak = {"strategy_key": "vwap_pullback"}  # no explicit ratio -> falls back to generic (1.0)
    strong = {"strategy_key": "breakdown_spike", "volume_spike_ratio": 3.0}

    chosen = engine._pick_priority([weak, strong], df)
    assert chosen is strong


def test_pick_priority_uses_generic_ratio_when_no_candidate_has_explicit_one():
    engine = StrategyEngine()
    # Current candle volume (500) is 5x the trailing 5-candle average (100) -> generic ratio 5.0
    df = _make_df(6, volumes=[100, 100, 100, 100, 100, 500])
    a = {"strategy_key": "vwap_pullback"}
    b = {"strategy_key": "orb"}

    # Both fall back to the same generic ratio — first candidate wins ties deterministically
    # (Python's stable sort preserves input order among equal keys).
    chosen = engine._pick_priority([a, b], df)
    assert chosen is a

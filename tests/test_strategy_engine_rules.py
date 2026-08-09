"""Tests for strategy_engine_rules.py's 6 condition chains, against synthetic OHLCV
DataFrames. Strategies that depend on indicator_utils (EMA/RSI/VWAP/Bollinger) monkeypatch
those functions directly, since their correctness is already covered by
test_indicator_utils.py — this file tests the rule/condition logic in isolation."""
from datetime import datetime, timedelta

import pandas as pd
import pytest

import strategy_engine_rules as rules


def _make_df(n: int, start="2026-08-10 09:15", freq="5min", price=24500.0) -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=n, freq=freq)
    return pd.DataFrame({
        "Open": [price] * n,
        "High": [price + 5] * n,
        "Low": [price - 5] * n,
        "Close": [price] * n,
        "Volume": [1000.0] * n,
    }, index=idx)


# ---------------------------------------------------------------------------
# Global filters
# ---------------------------------------------------------------------------

def test_vix_gate_call_blocked_above_18():
    assert rules.vix_gate(18.0, "BULLISH") is True
    assert rules.vix_gate(18.01, "BULLISH") is False


def test_vix_gate_put_allowed_only_below_14():
    assert rules.vix_gate(13.99, "BEARISH") is True
    assert rules.vix_gate(14.0, "BEARISH") is False


def test_vix_gate_both_requires_stricter_put_threshold():
    assert rules.vix_gate(13.99, "BOTH") is True
    assert rules.vix_gate(15.0, "BOTH") is False  # passes call gate, fails put gate


def test_vix_gate_none_fails_closed():
    assert rules.vix_gate(None, "BULLISH") is False
    assert rules.vix_gate(None, "BEARISH") is False


def test_is_past_eod_cutoff():
    assert rules.is_past_eod_cutoff(datetime(2026, 8, 10, 14, 44)) is False
    assert rules.is_past_eod_cutoff(datetime(2026, 8, 10, 14, 45)) is True
    assert rules.is_past_eod_cutoff(datetime(2026, 8, 10, 15, 0)) is True


# ---------------------------------------------------------------------------
# Strategy A: VWAP Pullback
# ---------------------------------------------------------------------------

def test_evaluate_vwap_pullback_fires_on_trend_pullback_reversal(monkeypatch):
    df = _make_df(25)
    df.loc[df.index[-1], "Close"] = 24520.0
    df.loc[df.index[-2], "Low"] = 24470.0  # touches below VWAP/EMA

    ema_series = pd.Series([24500.0] * 25, index=df.index)
    vwap_series = pd.Series([24480.0] * 25, index=df.index)
    rsi_series = pd.Series([55.0] * 23 + [45.0, 55.0], index=df.index)  # prev<50, now>50
    bb = (pd.Series([24550.0] * 25, index=df.index),
          pd.Series([24700.0] * 25, index=df.index),
          pd.Series([24400.0] * 25, index=df.index))

    monkeypatch.setattr(rules, "compute_ema", lambda series, span: ema_series)
    monkeypatch.setattr(rules, "compute_vwap", lambda d: vwap_series)
    monkeypatch.setattr(rules, "compute_rsi", lambda series, period=14: rsi_series)
    monkeypatch.setattr(rules, "compute_bollinger_bands", lambda series, period=20, std_mult=2: bb)

    result = rules.evaluate_vwap_pullback(df)

    assert result is not None
    assert result["direction"] == "BULLISH"
    assert result["option_type"] == "CE"
    assert result["target"] == 24700.0
    assert result["stop_loss"] == 24500.0  # max(vwap, ema)


def test_evaluate_vwap_pullback_no_fire_without_trend(monkeypatch):
    df = _make_df(25)
    df.loc[df.index[-1], "Close"] = 24400.0  # below EMA — trend filter fails

    ema_series = pd.Series([24500.0] * 25, index=df.index)
    vwap_series = pd.Series([24480.0] * 25, index=df.index)
    rsi_series = pd.Series([55.0] * 25, index=df.index)
    bb = (pd.Series([24550.0] * 25, index=df.index),
          pd.Series([24700.0] * 25, index=df.index),
          pd.Series([24400.0] * 25, index=df.index))

    monkeypatch.setattr(rules, "compute_ema", lambda series, span: ema_series)
    monkeypatch.setattr(rules, "compute_vwap", lambda d: vwap_series)
    monkeypatch.setattr(rules, "compute_rsi", lambda series, period=14: rsi_series)
    monkeypatch.setattr(rules, "compute_bollinger_bands", lambda series, period=20, std_mult=2: bb)

    assert rules.evaluate_vwap_pullback(df) is None


# ---------------------------------------------------------------------------
# Strategy B: Breakdown Spike
# ---------------------------------------------------------------------------

def test_evaluate_breakdown_spike_fires_on_tight_range_breakdown_with_volume():
    df = _make_df(21, price=24500.0)
    # 15-candle range window (iloc[-16:-1]) stays tight around 24500
    for i in range(5, 20):
        df.iloc[i, df.columns.get_loc("High")] = 24505.0
        df.iloc[i, df.columns.get_loc("Low")] = 24495.0
        df.iloc[i, df.columns.get_loc("Volume")] = 1000.0
    # Current candle breaks below the range low with a volume spike
    df.iloc[-1, df.columns.get_loc("Close")] = 24480.0
    df.iloc[-1, df.columns.get_loc("Volume")] = 2000.0

    result = rules.evaluate_breakdown_spike(df)

    assert result is not None
    assert result["direction"] == "BEARISH"
    assert result["option_type"] == "PE"
    assert result["stop_loss"] == 24495.0
    assert result["target"] == pytest.approx(24495.0 - (24505.0 - 24495.0))
    assert result["volume_spike_ratio"] == pytest.approx(2.0)


def test_evaluate_breakdown_spike_no_fire_without_volume_confirmation():
    df = _make_df(21, price=24500.0)
    for i in range(5, 20):
        df.iloc[i, df.columns.get_loc("High")] = 24505.0
        df.iloc[i, df.columns.get_loc("Low")] = 24495.0
        df.iloc[i, df.columns.get_loc("Volume")] = 1000.0
    df.iloc[-1, df.columns.get_loc("Close")] = 24480.0
    df.iloc[-1, df.columns.get_loc("Volume")] = 1000.0  # no spike

    assert rules.evaluate_breakdown_spike(df) is None


def test_evaluate_breakdown_spike_no_fire_on_zero_volume_index_data():
    """Indices report zero volume via yfinance — this must fail closed, not divide by zero."""
    df = _make_df(21, price=24500.0)
    for i in range(5, 20):
        df.iloc[i, df.columns.get_loc("High")] = 24505.0
        df.iloc[i, df.columns.get_loc("Low")] = 24495.0
        df.iloc[i, df.columns.get_loc("Volume")] = 0.0
    df.iloc[-1, df.columns.get_loc("Close")] = 24480.0
    df.iloc[-1, df.columns.get_loc("Volume")] = 0.0

    assert rules.evaluate_breakdown_spike(df) is None


# ---------------------------------------------------------------------------
# Strategy C: ORB
# ---------------------------------------------------------------------------

def test_compute_orb_levels_reads_first_30_minutes():
    # 09:15..09:40 (6 candles) is the opening range; 09:45 onward must NOT affect the result.
    idx = pd.date_range("2026-08-10 09:15", periods=10, freq="5min")
    df = pd.DataFrame({
        "Open": range(10), "Close": range(10),
        "High": [100, 110, 90, 105, 95, 102, 200, 200, 200, 200],
        "Low": [95, 100, 80, 100, 90, 98, 50, 50, 50, 50],
    }, index=idx)

    levels = rules.compute_orb_levels(df, idx[0].date())

    assert levels == {"orb_high": 110, "orb_low": 80}


def test_evaluate_orb_fires_bullish_breakout():
    idx = pd.date_range("2026-08-10 10:00", periods=2, freq="5min")
    df = pd.DataFrame({
        "Open": [24600, 24610], "Close": [24600, 24630],
        "High": [24600, 24650], "Low": [24580, 24620],
    }, index=idx)

    result = rules.evaluate_orb(df, orb_high=24640, orb_low=24500)

    assert result is not None
    assert result["direction"] == "BULLISH"
    assert result["stop_loss"] == 24580  # previous candle's Low


def test_evaluate_orb_fires_bearish_breakdown():
    idx = pd.date_range("2026-08-10 10:00", periods=2, freq="5min")
    df = pd.DataFrame({
        "Open": [24500, 24480], "Close": [24500, 24460],
        "High": [24520, 24490], "Low": [24490, 24440],
    }, index=idx)

    result = rules.evaluate_orb(df, orb_high=24640, orb_low=24470)

    assert result is not None
    assert result["direction"] == "BEARISH"
    assert result["stop_loss"] == 24520  # previous candle's High


def test_evaluate_orb_no_fire_inside_range():
    idx = pd.date_range("2026-08-10 10:00", periods=2, freq="5min")
    df = pd.DataFrame({
        "Open": [24550, 24560], "Close": [24550, 24560],
        "High": [24560, 24570], "Low": [24540, 24550],
    }, index=idx)

    assert rules.evaluate_orb(df, orb_high=24640, orb_low=24470) is None


# ---------------------------------------------------------------------------
# Strategy D: OI Surge
# ---------------------------------------------------------------------------

def test_evaluate_oi_surge_fires_on_surge_with_long_buildup(monkeypatch):
    idx = pd.date_range("2026-08-10 10:00", periods=4, freq="5min")
    df = pd.DataFrame({
        "Open": [1000, 1005, 1010, 1020], "Close": [1000, 1005, 1010, 1025],
        "High": [1002, 1007, 1012, 1027], "Low": [998, 1003, 1008, 1018],
        "Volume": [100, 100, 100, 100],
    }, index=idx)
    monkeypatch.setattr(rules, "compute_rsi", lambda series, period=14: pd.Series([60.0] * 4, index=idx))

    result = rules.evaluate_oi_surge(df, oi_change_15min=5.0)

    assert result is not None
    assert result["otm_steps"] == 1
    assert result["stop_loss"] == 1000  # open of the breakout candle (3 bars back)


def test_evaluate_oi_surge_no_fire_without_oi_buildup(monkeypatch):
    idx = pd.date_range("2026-08-10 10:00", periods=4, freq="5min")
    df = pd.DataFrame({
        "Open": [1000, 1005, 1010, 1020], "Close": [1000, 1005, 1010, 1025],
        "High": [1002, 1007, 1012, 1027], "Low": [998, 1003, 1008, 1018],
        "Volume": [100, 100, 100, 100],
    }, index=idx)
    monkeypatch.setattr(rules, "compute_rsi", lambda series, period=14: pd.Series([60.0] * 4, index=idx))

    assert rules.evaluate_oi_surge(df, oi_change_15min=-2.0) is None
    assert rules.evaluate_oi_surge(df, oi_change_15min=None) is None


# ---------------------------------------------------------------------------
# Strategy E: Death Cross
# ---------------------------------------------------------------------------

def test_evaluate_death_cross_fires_on_cross_with_short_buildup(monkeypatch):
    df = _make_df(22, freq="15min", price=1000.0)
    df.loc[df.index[-2], "Close"] = 1010.0
    df.loc[df.index[-1], "Close"] = 995.0  # price down vs previous candle

    ema5 = pd.Series([1005.0] * 20 + [1005.0, 995.0], index=df.index)   # crosses below on last candle
    ema20 = pd.Series([1000.0] * 22, index=df.index)

    monkeypatch.setattr(rules, "compute_ema", lambda series, span: ema5 if span == 5 else ema20)

    result = rules.evaluate_death_cross(df, oi_change_15min=3.0)

    assert result is not None
    assert result["direction"] == "BEARISH"
    assert result["option_type"] == "PE"
    assert result["stop_loss"] == 995.0  # current 5-EMA


def test_evaluate_death_cross_no_fire_without_short_buildup(monkeypatch):
    df = _make_df(22, freq="15min", price=1000.0)
    df.loc[df.index[-2], "Close"] = 1010.0
    df.loc[df.index[-1], "Close"] = 995.0

    ema5 = pd.Series([1005.0] * 20 + [1005.0, 995.0], index=df.index)
    ema20 = pd.Series([1000.0] * 22, index=df.index)
    monkeypatch.setattr(rules, "compute_ema", lambda series, span: ema5 if span == 5 else ema20)

    # OI change <= 0 — no short build-up despite the cross + falling price
    assert rules.evaluate_death_cross(df, oi_change_15min=-1.0) is None


# ---------------------------------------------------------------------------
# Strategy F: Volatility Straddle
# ---------------------------------------------------------------------------

def test_evaluate_volatility_straddle_fires_on_low_iv_and_event():
    result = rules.evaluate_volatility_straddle(is_in_lower_iv_percentile=True, has_event_within_48h=True)
    assert result is not None
    assert result["option_type"] == "BOTH"
    assert result["direction"] == "NEUTRAL"


@pytest.mark.parametrize("iv_flag,event_flag", [
    (False, True), (True, False), (None, True), (None, False),
])
def test_evaluate_volatility_straddle_no_fire_unless_both_conditions(iv_flag, event_flag):
    assert rules.evaluate_volatility_straddle(iv_flag, event_flag) is None

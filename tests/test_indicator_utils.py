"""Tests for indicator_utils.py's VWAP/EMA/RSI/Bollinger — shared indicators for the
intraday Strategy Engine."""
import numpy as np
import pandas as pd
import pytest

import indicator_utils as iu


def test_compute_vwap_matches_manual_calc():
    df = pd.DataFrame({
        "Close": [100.0, 101.0, 102.0],
        "Volume": [10.0, 20.0, 30.0],
    })
    vwap = iu.compute_vwap(df)

    expected_0 = (100.0 * 10.0) / 10.0
    expected_1 = (100.0 * 10.0 + 101.0 * 20.0) / (10.0 + 20.0)
    expected_2 = (100.0 * 10.0 + 101.0 * 20.0 + 102.0 * 30.0) / (10.0 + 20.0 + 30.0)

    assert vwap.iloc[0] == pytest.approx(expected_0)
    assert vwap.iloc[1] == pytest.approx(expected_1)
    assert vwap.iloc[2] == pytest.approx(expected_2)


def test_compute_vwap_falls_back_to_close_when_zero_volume():
    """Indices report zero volume via yfinance (documented elsewhere in this codebase) — VWAP
    must not divide by zero or return NaN in that case."""
    df = pd.DataFrame({"Close": [24500.0, 24510.0], "Volume": [0.0, 0.0]})
    vwap = iu.compute_vwap(df)
    assert vwap.iloc[0] == 24500.0
    assert vwap.iloc[1] == 24510.0


def test_compute_ema_matches_pandas_ewm():
    series = pd.Series([10.0, 11.0, 12.0, 11.5, 13.0, 14.0])
    ema = iu.compute_ema(series, span=3)
    expected = series.ewm(span=3, adjust=False).mean()
    pd.testing.assert_series_equal(ema, expected)


def test_compute_rsi_all_gains_is_100():
    series = pd.Series([float(i) for i in range(1, 20)])  # strictly increasing
    rsi = iu.compute_rsi(series, period=14)
    assert rsi.iloc[-1] == pytest.approx(100.0)


def test_compute_rsi_all_losses_is_0():
    series = pd.Series([float(i) for i in range(20, 1, -1)])  # strictly decreasing
    rsi = iu.compute_rsi(series, period=14)
    assert rsi.iloc[-1] == pytest.approx(0.0)


def test_compute_rsi_neutral_default_on_insufficient_history():
    series = pd.Series([10.0, 11.0, 10.5])
    rsi = iu.compute_rsi(series, period=14)
    assert (rsi == 50.0).all()


def test_compute_bollinger_bands_shape_and_ordering():
    series = pd.Series(np.linspace(100, 120, 25))
    middle, upper, lower = iu.compute_bollinger_bands(series, period=20, std_mult=2)
    assert upper.iloc[-1] > middle.iloc[-1] > lower.iloc[-1]

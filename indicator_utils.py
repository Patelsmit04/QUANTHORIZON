"""
SHARED INTRADAY INDICATOR UTILITIES
====================================
Pure, stateless functions on a pandas DataFrame/Series: VWAP, EMA, RSI(14), Bollinger Bands.

VWAP and RSI already exist inline (and duplicated between scoring_engine.py and
index_scoring.py) for the overnight BTST/STBT model. This module is a separate, single
shared copy for the intraday Strategy Engine (strategy_engine.py / strategy_engine_rules.py)
— it deliberately does not touch those existing call sites.
"""

import numpy as np
import pandas as pd
from typing import Tuple


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """Session-cumulative VWAP: cumsum(Close*Volume) / cumsum(Volume). Falls back to Close
    for any row with zero cumulative volume so far (e.g. index data with no volume)."""
    cum_vol = df["Volume"].cumsum()
    cum_vol_price = (df["Close"] * df["Volume"]).cumsum()
    return pd.Series(
        np.where(cum_vol > 0, cum_vol_price / cum_vol, df["Close"]),
        index=df.index,
    )


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder-style RSI. Neutral 50.0 default only where the rolling window can't yet
    compute (insufficient history) or price was genuinely flat (gain == loss == 0) — a window
    with real gains and zero losses is a real RSI of 100, not an unknown value, so that case
    is handled explicitly rather than falling into the same NaN bucket as "not enough data"."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()

    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    all_gain_no_loss = (loss == 0) & (gain > 0)
    rsi = rsi.where(~all_gain_no_loss, 100.0)

    return rsi.fillna(50.0)


def compute_bollinger_bands(series: pd.Series, period: int = 20, std_mult: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (middle_band, upper_band, lower_band) — SMA(period) +/- std_mult * rolling std."""
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    return middle, upper, lower

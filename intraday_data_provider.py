"""
SHARED INTRADAY OHLCV FETCH HELPER
====================================
fetch_intraday_ohlc() wraps the yf.download + MultiIndex-flatten + dropna boilerplate that's
independently duplicated across smc_scanner.py, app.py's fetch_raw_stock_universe()/
fetch_index_ohlc_dict(), btst_engine.py, and vix_provider.py — one shared copy for the new
intraday Strategy Engine, wired through net_utils.call_with_retry for the timeout/retry
discipline every other network-touching provider in this codebase uses.

FAIL LOUD: returns None on any failure, empty payload, or too-few-rows result — never a
partial/fabricated candle set.
"""

import logging
from typing import Optional

import pandas as pd
import yfinance as yf

from net_utils import call_with_retry

logger = logging.getLogger("IntradayDataProvider")

MIN_ROWS_DEFAULT = 10


def fetch_intraday_ohlc(ticker: str, interval: str, period: str, min_rows: int = MIN_ROWS_DEFAULT) -> Optional[pd.DataFrame]:
    """Fetch OHLCV candles for one ticker at the given yfinance interval/period.

    Index is left as the datetime index yfinance returns (not reset) so callers can read
    candle-close timestamps directly for candle-close detection and ORB/session-window logic.
    """
    df = call_with_retry(
        lambda: yf.download(tickers=ticker, period=period, interval=interval, progress=False),
        label=f"intraday OHLC [{ticker} {interval}]",
    )
    if df is None or df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if df.empty or len(df) < min_rows:
        return None

    return df

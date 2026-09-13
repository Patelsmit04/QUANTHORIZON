"""
Shared "fetch next-session candles after a lock date" helper — the identical ~15-line block
(download, flatten MultiIndex columns, dropna, reset_index, derive DateStr, filter to candles
strictly after the lock date) was independently duplicated three times: app.py's
TradeHistoryManager.evaluate_pending_trades(), signal_journal.py's evaluate_pending_signals(),
and evaluate_pending_index_verdicts() (Phase-1 audit finding #9). One copy here, all three use
it — the outcome-classification / P&L-simulation logic downstream of this stays in each caller,
since that part genuinely differs between them.
"""

import logging
from typing import Optional

import pandas as pd
import yfinance as yf

from net_utils import call_with_retry

logger = logging.getLogger("CandleUtils")


def _download_candles(ticker: str, period: str, interval: str) -> Optional[pd.DataFrame]:
    """Fetch candles for a single ticker with instance-bound yf.Ticker, completely
    isolated from yfinance's global shared._DFS state used by multi-ticker batch downloads."""
    try:
        t = yf.Ticker(ticker)
        df = t.history(period=period, interval=interval)
        if df is not None and not df.empty and len(df.dropna()) >= 1:
            return df
    except Exception as e:
        logger.debug(f"yf.Ticker({ticker}).history failed: {e}")
    # Fallback to yf.download with threads=False to avoid corrupting shared._DFS
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False, threads=False)
        return df
    except Exception as e:
        logger.warning(f"yf.download fallback failed for {ticker}: {e}")
        return None


def fetch_post_lock_candles(
    ticker: str,
    lock_date: str,
    label: str,
    period: str = "5d",
    interval: str = "5m",
    reference_close: Optional[float] = None,
) -> Optional[pd.DataFrame]:
    """Downloads recent candles for `ticker` and returns only the rows strictly after
    `lock_date` (a "YYYY-MM-DD" string) — i.e. the next trading session(s). Returns None if
    the fetch fails (after retry), comes back empty, or has no candles after the lock date."""
    df = call_with_retry(
        lambda: _download_candles(ticker, period=period, interval=interval),
        label=label,
    )
    
    # Fallback to 1m interval right at 9:15 AM market open when 5m candle hasn't completed yet
    if df is None or df.empty or len(df.dropna()) < 1:
        df = call_with_retry(
            lambda: _download_candles(ticker, period="2d", interval="1m"),
            label=f"{label} [1m fallback]",
        )

    if df is None or df.empty:
        return None

    # Handle MultiIndex if fallback returned multi-level columns
    if isinstance(df.columns, pd.MultiIndex):
        if ticker in df.columns.levels[0]:
            df = df[ticker]
        elif len(df.columns.levels) > 1 and ticker in df.columns.levels[1]:
            df = df.xs(ticker, axis=1, level=1)
        else:
            df.columns = df.columns.get_level_values(0)

    df = df.dropna().copy()
    if df.empty:
        return None

    df.reset_index(inplace=True)
    time_col = "Datetime" if "Datetime" in df.columns else ("Date" if "Date" in df.columns else df.columns[0])
    df["DateStr"] = df[time_col].astype(str).str.slice(0, 10)

    post_lock_df = df[df["DateStr"] > lock_date]

    # If post_lock_df is empty with 5m interval, try 1m fallback
    if post_lock_df.empty and interval != "1m":
        df_1m = call_with_retry(
            lambda: _download_candles(ticker, period="2d", interval="1m"),
            label=f"{label} [1m post-lock fallback]",
        )
        if df_1m is not None and not df_1m.empty:
            if isinstance(df_1m.columns, pd.MultiIndex):
                if ticker in df_1m.columns.levels[0]:
                    df_1m = df_1m[ticker]
                elif len(df_1m.columns.levels) > 1 and ticker in df_1m.columns.levels[1]:
                    df_1m = df_1m.xs(ticker, axis=1, level=1)
                else:
                    df_1m.columns = df_1m.columns.get_level_values(0)
            df_1m = df_1m.dropna().copy()
            if not df_1m.empty:
                df_1m.reset_index(inplace=True)
                tc = "Datetime" if "Datetime" in df_1m.columns else ("Date" if "Date" in df_1m.columns else df_1m.columns[0])
                df_1m["DateStr"] = df_1m[tc].astype(str).str.slice(0, 10)
                post_lock_df = df_1m[df_1m["DateStr"] > lock_date]

    if post_lock_df.empty:
        return None

    # Sanity guard on reference close if provided
    if reference_close is not None and reference_close > 0:
        try:
            cand_open = float(post_lock_df.iloc[0]["Open"])
            ratio = cand_open / reference_close
            if ratio < 0.65 or ratio > 1.45:
                logger.warning(
                    f"[{label}] Price sanity warning for {ticker}: fetched open {cand_open} vs reference close {reference_close} (ratio {ratio:.2f})."
                )
        except Exception:
            pass

    return post_lock_df

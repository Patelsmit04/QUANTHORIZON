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


def fetch_post_lock_candles(ticker: str, lock_date: str, label: str, period: str = "5d", interval: str = "5m") -> Optional[pd.DataFrame]:
    """Downloads recent candles for `ticker` and returns only the rows strictly after
    `lock_date` (a "YYYY-MM-DD" string) — i.e. the next trading session(s). Returns None if
    the fetch fails (after retry), comes back empty, or has no candles after the lock date."""
    df = call_with_retry(
        lambda: yf.download(ticker, period=period, interval=interval, progress=False),
        label=label,
    )
    if df is None or df.empty:
        return None

    # This yfinance version returns MultiIndex columns like ('Close', 'TICKER.NS') even for a
    # single-ticker download — the field name is level 0, not the ticker, so flatten to level 0
    # rather than trying to index by ticker.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna().copy()
    if df.empty:
        return None

    df.reset_index(inplace=True)
    time_col = "Datetime" if "Datetime" in df.columns else ("Date" if "Date" in df.columns else df.columns[0])
    df["DateStr"] = df[time_col].astype(str).str.slice(0, 10)

    post_lock_df = df[df["DateStr"] > lock_date]
    return post_lock_df if not post_lock_df.empty else None

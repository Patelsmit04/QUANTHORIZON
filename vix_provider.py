"""
INDIA VIX REGIME PROVIDER & CLASSIFIER
=====================================
Fetches live India VIX benchmark and classifies market volatility regime:
- LOW_VOL: VIX < 13.0
- NORMAL: 13.0 <= VIX <= 18.0
- HIGH_VOL: VIX > 18.0
"""

import logging
from typing import Dict, Any, Tuple
import yfinance as yf

logger = logging.getLogger("IndiaVIXProvider")

def fetch_india_vix() -> Tuple[float, str]:
    """
    Fetch current India VIX index value and return (vix_value, regime_name).
    """
    tickers = ["^INDIAVIX", "INDIAVIX.NS"]
    for ticker in tickers:
        try:
            df = yf.download(ticker, period="5d", interval="1d", progress=False)
            if df is not None and not df.empty:
                # This yfinance version returns MultiIndex columns like ('Close', 'TICKER')
                # even for a single-ticker download — flatten before selecting 'Close'.
                if hasattr(df.columns, "levels"):
                    df.columns = df.columns.get_level_values(0)
                df = df.dropna()
                if not df.empty:
                    latest_close = float(df['Close'].iloc[-1])
                    if latest_close > 0:
                        regime = classify_vix_regime(latest_close)
                        logger.info(f"India VIX fetched: {latest_close:.2f} ({regime})")
                        return round(latest_close, 2), regime
        except Exception as e:
            logger.warning(f"Failed to fetch VIX via {ticker}: {e}")

    # Fallback to default NORMAL regime if VIX feed is unreachable
    logger.warning("India VIX feed unavailable — defaulting to 15.0 (NORMAL)")
    return 15.0, "NORMAL"


def classify_vix_regime(vix_value: float) -> str:
    """Classify VIX value into LOW_VOL, NORMAL, or HIGH_VOL."""
    if vix_value < 13.0:
        return "LOW_VOL"
    elif vix_value <= 18.0:
        return "NORMAL"
    else:
        return "HIGH_VOL"

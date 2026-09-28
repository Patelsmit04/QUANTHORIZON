"""
VECTORBT-BACKED BACKTESTING ENGINE
====================================
Institutional-grade backtesting harness built on vectorbt's vectorized
Portfolio engine. Replaces hand-rolled backtest loops with tested
entry/exit/slippage/commission handling.

Public API:
  - backtest_strategy(symbol, strategy_fn, ...) -> dict
  - backtest_smc_strategy(symbol, ...) -> dict
  - run_walk_forward_backtest(symbols, strategy_fn, ...) -> dict
  - run_cross_check(symbols) -> dict
"""

import logging
from typing import Dict, Any, Optional, Callable, List
import pandas as pd
import numpy as np
import yfinance as yf

logger = logging.getLogger("VectorbtBacktester")

# Lazy import — vectorbt is heavy and only needed when backtest functions run
_vbt = None


def _get_vbt():
    """Lazy-import vectorbt to avoid startup cost when module is just imported."""
    global _vbt
    if _vbt is None:
        try:
            import vectorbt as vbt
            _vbt = vbt
        except ImportError:
            logger.error("vectorbt not installed. Run: pip install vectorbt")
            raise
    return _vbt


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_SLIPPAGE = 0.0005    # 0.05% — realistic for Indian equities
DEFAULT_COMMISSION = 0.0003  # 0.03% — STT + brokerage approximation
DEFAULT_INIT_CASH = 1_000_000  # ₹10L starting capital

# ---------------------------------------------------------------------------
# Internal: OHLC fetching
# ---------------------------------------------------------------------------

def _fetch_ohlc(symbol: str, period: str = "3mo", interval: str = "1d") -> Optional[pd.DataFrame]:
    """Fetch OHLC data via yfinance, normalize columns."""
    try:
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close", "Open", "High", "Low"])
        return df
    except Exception as e:
        logger.debug(f"Failed to fetch OHLC for {symbol}: {e}")
        return None


# ---------------------------------------------------------------------------
# Internal: Signal generation bridge
# ---------------------------------------------------------------------------

def _generate_signal_arrays(
    df: pd.DataFrame,
    strategy_fn: Callable,
    lookback: int = 20
) -> Dict[str, Any]:
    """
    Run strategy_fn on rolling windows of df to generate entry/exit arrays.

    strategy_fn: must accept (df_slice) and return dict with 'signal' key
                 ('BTST_BUY' or 'STBT_SELL') or None.

    Returns:
        entries: boolean array — True where a BUY entry is signalled
        exits: boolean array — True where an explicit EXIT is signalled
        tp_pcts: array of take-profit percentages per entry
        sl_pcts: array of stop-loss percentages per entry
    """
    n = len(df)
    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)
    tp_pcts = np.full(n, 1.5)  # default TP
    sl_pcts = np.full(n, 0.75)  # default SL

    for i in range(lookback, n):
        try:
            window = df.iloc[max(0, i - lookback * 3):i + 1]
            if len(window) < 10:
                continue

            result = strategy_fn(window)
            if result is None:
                continue

            sig = result.get("signal", "")
            if "BUY" in sig:
                entries[i] = True
                tp_pcts[i] = result.get("tp_pct", 1.5)
                sl_pcts[i] = result.get("sl_pct", 0.75)
            elif "SELL" in sig:
                exits[i] = True
        except Exception as e:
            logger.debug(f"Signal generation error at bar {i}: {e}")
            continue

    return {
        "entries": entries,
        "exits": exits,
        "tp_pcts": tp_pcts,
        "sl_pcts": sl_pcts,
    }


# ---------------------------------------------------------------------------
# Public: Single-symbol backtest
# ---------------------------------------------------------------------------

def backtest_strategy(
    symbol: str,
    strategy_fn: Callable,
    period: str = "3mo",
    interval: str = "1d",
    slippage: float = DEFAULT_SLIPPAGE,
    commission: float = DEFAULT_COMMISSION,
    init_cash: float = DEFAULT_INIT_CASH,
    lookback: int = 20,
) -> Dict[str, Any]:
    """
    Run a full vectorbt backtest for a single symbol.

    Args:
        symbol: Yahoo Finance ticker (e.g., 'RELIANCE.NS')
        strategy_fn: callable that takes a DataFrame and returns
                     {'signal': 'BTST_BUY'/'STBT_SELL', 'entry', 'tp_pct', 'sl_pct'} or None
        period/interval: yfinance fetch parameters
        slippage: fractional slippage per trade
        commission: fractional commission per trade

    Returns:
        Dict with Sharpe, win_rate, total_return, max_drawdown, profit_factor, etc.
    """
    vbt = _get_vbt()

    df = _fetch_ohlc(symbol, period, interval)
    if df is None or len(df) < 30:
        return _empty_result(symbol, "INSUFFICIENT_DATA")

    signals = _generate_signal_arrays(df, strategy_fn, lookback=lookback)
    entries = signals["entries"]
    exits = signals["exits"]

    total_entries = int(entries.sum())
    if total_entries == 0:
        return _empty_result(symbol, "NO_SIGNALS")

    try:
        close = df["Close"].values.astype(float)

        # Build portfolio using vectorbt
        pf = vbt.Portfolio.from_signals(
            close=close,
            entries=entries,
            exits=exits,
            init_cash=init_cash,
            sl_stop=np.median(signals["sl_pcts"][entries]) / 100 if total_entries > 0 else 0.0075,
            tp_stop=np.median(signals["tp_pcts"][entries]) / 100 if total_entries > 0 else 0.015,
            fees=commission,
            slippage=slippage,
            freq="1D" if interval == "1d" else interval,
        )

        # Extract metrics
        stats = pf.stats()
        trades = pf.trades.records_readable if hasattr(pf.trades, 'records_readable') else None

        win_count = 0
        loss_count = 0
        total_trades = 0
        gross_profit = 0.0
        gross_loss = 0.0

        if trades is not None and len(trades) > 0:
            total_trades = len(trades)
            for _, t in trades.iterrows():
                pnl = t.get("PnL", t.get("Return", 0))
                if isinstance(pnl, (int, float)) and pnl > 0:
                    win_count += 1
                    gross_profit += pnl
                else:
                    loss_count += 1
                    gross_loss += abs(pnl) if isinstance(pnl, (int, float)) else 0

        win_rate = round((win_count / total_trades) * 100, 1) if total_trades > 0 else 0.0
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float('inf') if gross_profit > 0 else 0.0

        # Extract standard metrics from stats
        total_return = _safe_stat(stats, "Total Return [%]", 0.0)
        sharpe = _safe_stat(stats, "Sharpe Ratio", 0.0)
        max_dd = _safe_stat(stats, "Max Drawdown [%]", 0.0)
        sortino = _safe_stat(stats, "Sortino Ratio", 0.0)

        return {
            "symbol": symbol,
            "status": "BACKTEST_COMPLETE",
            "period": period,
            "interval": interval,
            "total_bars": len(df),
            "total_entries": total_entries,
            "total_trades": total_trades,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate_pct": win_rate,
            "total_return_pct": round(float(total_return), 2),
            "sharpe_ratio": round(float(sharpe), 3) if not np.isnan(sharpe) else 0.0,
            "sortino_ratio": round(float(sortino), 3) if not np.isnan(sortino) else 0.0,
            "max_drawdown_pct": round(float(max_dd), 2),
            "profit_factor": profit_factor if not np.isinf(profit_factor) else 99.0,
            "slippage_applied": slippage,
            "commission_applied": commission,
            "init_cash": init_cash,
            "engine": "vectorbt",
        }

    except Exception as e:
        logger.error(f"vectorbt backtest failed for {symbol}: {e}")
        return _empty_result(symbol, f"ERROR: {str(e)[:100]}")


def _safe_stat(stats, key: str, default: float) -> float:
    """Safely extract a stat from vectorbt stats Series."""
    try:
        val = stats.get(key, default)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return default
        return float(val)
    except Exception:
        return default


def _empty_result(symbol: str, status: str) -> Dict[str, Any]:
    """Return a zero-valued result dict for cases where backtest can't run."""
    return {
        "symbol": symbol,
        "status": status,
        "total_bars": 0,
        "total_entries": 0,
        "total_trades": 0,
        "win_count": 0,
        "loss_count": 0,
        "win_rate_pct": 0.0,
        "total_return_pct": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "profit_factor": 0.0,
        "slippage_applied": DEFAULT_SLIPPAGE,
        "commission_applied": DEFAULT_COMMISSION,
        "init_cash": DEFAULT_INIT_CASH,
        "engine": "vectorbt",
    }


# ---------------------------------------------------------------------------
# Public: SMC strategy convenience wrapper
# ---------------------------------------------------------------------------

def backtest_smc_strategy(
    symbol: str,
    period: str = "3mo",
    interval: str = "1d",
    **kwargs,
) -> Dict[str, Any]:
    """Backtest the SMC strategy (smc_strategy.evaluate_signal) for a single symbol."""
    from smc_strategy import evaluate_signal
    return backtest_strategy(symbol, evaluate_signal, period=period, interval=interval, **kwargs)


# ---------------------------------------------------------------------------
# Public: Walk-forward backtest (replaces DB-query-based validation)
# ---------------------------------------------------------------------------

def run_walk_forward_backtest(
    symbols: List[str],
    strategy_fn: Callable,
    period: str = "1y",
    interval: str = "1d",
    train_ratio: float = 0.7,
    **kwargs,
) -> Dict[str, Any]:
    """
    Walk-forward validation using vectorbt.
    Splits OHLC data into train/test windows, runs backtest only on test (OOS) window.

    Returns aggregated OOS metrics across all symbols.
    """
    vbt = _get_vbt()

    oos_results = []
    symbols_tested = []
    symbols_skipped = []

    for symbol in symbols:
        df = _fetch_ohlc(symbol, period, interval)
        if df is None or len(df) < 30:
            symbols_skipped.append(symbol)
            continue

        # Split: 70% train, 30% test (out-of-sample)
        split_idx = int(len(df) * train_ratio)
        df_oos = df.iloc[split_idx:]

        if len(df_oos) < 10:
            symbols_skipped.append(symbol)
            continue

        # Generate signals on OOS data only
        signals = _generate_signal_arrays(df_oos, strategy_fn, lookback=20)
        entries = signals["entries"]
        total_entries = int(entries.sum())

        if total_entries == 0:
            symbols_skipped.append(symbol)
            continue

        try:
            close = df_oos["Close"].values.astype(float)
            pf = vbt.Portfolio.from_signals(
                close=close,
                entries=entries,
                exits=signals["exits"],
                init_cash=DEFAULT_INIT_CASH,
                sl_stop=np.median(signals["sl_pcts"][entries]) / 100,
                tp_stop=np.median(signals["tp_pcts"][entries]) / 100,
                fees=DEFAULT_COMMISSION,
                slippage=DEFAULT_SLIPPAGE,
                freq="1D" if interval == "1d" else interval,
            )

            stats = pf.stats()
            trades = pf.trades.records_readable if hasattr(pf.trades, 'records_readable') else None
            total_trades = len(trades) if trades is not None else 0
            wins = 0
            if trades is not None and len(trades) > 0:
                for _, t in trades.iterrows():
                    pnl = t.get("PnL", t.get("Return", 0))
                    if isinstance(pnl, (int, float)) and pnl > 0:
                        wins += 1

            oos_results.append({
                "symbol": symbol,
                "oos_bars": len(df_oos),
                "total_trades": total_trades,
                "wins": wins,
                "win_rate": round((wins / total_trades) * 100, 1) if total_trades > 0 else 0.0,
                "total_return": _safe_stat(stats, "Total Return [%]", 0.0),
                "sharpe": _safe_stat(stats, "Sharpe Ratio", 0.0),
                "max_dd": _safe_stat(stats, "Max Drawdown [%]", 0.0),
            })
            symbols_tested.append(symbol)

        except Exception as e:
            logger.debug(f"Walk-forward backtest failed for {symbol}: {e}")
            symbols_skipped.append(symbol)
            continue

    if not oos_results:
        return {
            "status": "NO_RESULTS",
            "message": "Walk-forward backtest produced no results — insufficient data or no signals.",
            "out_of_sample_accuracy_pct": 0.0,
            "out_of_sample_win_rate_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "windows_evaluated": 0,
            "engine": "vectorbt",
        }

    # Aggregate OOS metrics
    total_trades = sum(r["total_trades"] for r in oos_results)
    total_wins = sum(r["wins"] for r in oos_results)
    avg_sharpe = np.mean([r["sharpe"] for r in oos_results if r["sharpe"] != 0])
    avg_dd = np.mean([r["max_dd"] for r in oos_results])
    agg_win_rate = round((total_wins / total_trades) * 100, 1) if total_trades > 0 else 0.0

    return {
        "status": "WALK_FORWARD_COMPLETE",
        "engine": "vectorbt",
        "symbols_tested": len(symbols_tested),
        "symbols_skipped": len(symbols_skipped),
        "total_oos_trades": total_trades,
        "total_oos_wins": total_wins,
        "out_of_sample_win_rate_pct": agg_win_rate,
        "out_of_sample_accuracy_pct": agg_win_rate,  # alias for backward compat
        "sharpe_ratio": round(float(avg_sharpe), 3) if not np.isnan(avg_sharpe) else 0.0,
        "max_drawdown_pct": round(float(avg_dd), 2),
        "windows_evaluated": len(symbols_tested),
        "per_symbol": oos_results,
    }


# ---------------------------------------------------------------------------
# Public: Cross-check old vs new
# ---------------------------------------------------------------------------

def run_cross_check(symbols: List[str]) -> Dict[str, Any]:
    """
    Run both old journal-DB-based validation AND new vectorbt backtest,
    return side-by-side comparison.
    """
    from smc_strategy import evaluate_signal as smc_eval

    # New: vectorbt-backed
    new_smc = run_walk_forward_backtest(symbols, smc_eval, period="3mo", interval="1d")

    # Old: journal-DB-based (imported from the legacy functions kept in walk_forward_validator)
    try:
        from walk_forward_validator import (
            _legacy_validate_smc_strategy_out_of_sample,
        )
        old_smc = _legacy_validate_smc_strategy_out_of_sample()
    except (ImportError, AttributeError):
        old_smc = {"out_of_sample_win_rate_pct": "N/A (legacy fn not available)"}

    return {
        "cross_check": {
            "smc_strategy": {
                "old_journal_win_rate": old_smc.get("out_of_sample_win_rate_pct", "N/A"),
                "new_vectorbt_win_rate": new_smc.get("out_of_sample_win_rate_pct", 0.0),
                "new_vectorbt_sharpe": new_smc.get("sharpe_ratio", 0.0),
                "new_vectorbt_max_dd": new_smc.get("max_drawdown_pct", 0.0),
                "delta_win_rate": "N/A",
            },
        },
        "vectorbt_detail": new_smc,
    }

"""
TRADEXO Statistical Backtest Validation Framework
Version: 47.0.0
Institutional backtesting engine incorporating:
- Walk-forward Out-of-Sample (OOS) validation
- Bootstrap confidence intervals (1,000 resamples)
- Deflated Sharpe Ratio (DSR) and Multiple Testing corrections
- Out-of-Sample Degradation Ratio tracking (Sharpe_OOS / Sharpe_IS)
- Research-to-Production Frozen Model validation gate
- Identical shared FrictionModel economics
"""

from dataclasses import dataclass, field
import math
import random
from typing import Any, Dict, List, Optional, Tuple

from friction_model import compute_transaction_costs, get_active_friction_model


@dataclass
class BacktestStats:
    total_trades: int
    winning_trades: int
    win_rate_pct: float
    profit_factor: float
    gross_pnl: float
    net_pnl: float
    total_friction: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    trade_expectancy_pts: float
    t_statistic: float
    p_value: float
    sharpe_ci_95: Tuple[float, float]
    win_rate_ci_95: Tuple[float, float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "win_rate_pct": round(self.win_rate_pct, 2),
            "profit_factor": round(self.profit_factor, 2),
            "gross_pnl": round(self.gross_pnl, 2),
            "net_pnl": round(self.net_pnl, 2),
            "total_friction": round(self.total_friction, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "trade_expectancy_pts": round(self.trade_expectancy_pts, 2),
            "t_statistic": round(self.t_statistic, 2),
            "p_value": round(self.p_value, 4),
            "sharpe_ci_95": [round(self.sharpe_ci_95[0], 2), round(self.sharpe_ci_95[1], 2)],
            "win_rate_ci_95": [round(self.win_rate_ci_95[0], 2), round(self.win_rate_ci_95[1], 2)],
        }


@dataclass
class WalkForwardValidationReport:
    strategy_id: str
    in_sample_stats: BacktestStats
    out_of_sample_stats: BacktestStats
    degradation_ratio: float
    deflated_sharpe_ratio: float
    model_degradation_detected: bool
    validation_status: str  # "PASSED", "DEGRADATION_FLAG", "REJECTED"
    recommendation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "in_sample": self.in_sample_stats.to_dict(),
            "out_of_sample": self.out_of_sample_stats.to_dict(),
            "degradation_ratio": round(self.degradation_ratio, 3),
            "deflated_sharpe_ratio": round(self.deflated_sharpe_ratio, 3),
            "model_degradation_detected": self.model_degradation_detected,
            "validation_status": self.validation_status,
            "recommendation": self.recommendation,
        }


def _calculate_base_metrics(trade_pnls: List[float], friction_model_name: str = "EQUITY_DELIVERY") -> BacktestStats:
    """Computes foundational quantitative performance metrics for a sequence of trade net PnLs."""
    n = len(trade_pnls)
    if n == 0:
        return BacktestStats(
            total_trades=0, winning_trades=0, win_rate_pct=0.0, profit_factor=0.0,
            gross_pnl=0.0, net_pnl=0.0, total_friction=0.0, sharpe_ratio=0.0,
            sortino_ratio=0.0, max_drawdown_pct=0.0, trade_expectancy_pts=0.0,
            t_statistic=0.0, p_value=1.0, sharpe_ci_95=(0.0, 0.0), win_rate_ci_95=(0.0, 0.0)
        )

    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p <= 0]
    total_wins = len(wins)
    win_rate = (total_wins / n) * 100.0

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

    # Estimate realistic friction using shared model
    f_model = get_active_friction_model(instrument_type=friction_model_name)
    avg_trade_val = 50000.0  # Approx capital allocation per trade
    cost_audit = compute_transaction_costs(avg_trade_val, 1, "BUY", friction_model_name, f_model)
    total_friction = cost_audit.total_friction * 2.0 * n  # roundtrip per trade
    net_pnl = sum(trade_pnls) - total_friction

    mean_ret = sum(trade_pnls) / n
    variance = sum((p - mean_ret) ** 2 for p in trade_pnls) / (n - 1) if n > 1 else 0.0
    std_dev = math.sqrt(variance) if variance > 0 else 1e-6

    # Annualized Sharpe assuming 250 BTST sessions per year
    sharpe = (mean_ret / std_dev) * math.sqrt(250) if std_dev > 0 else 0.0

    downside_var = sum((min(0.0, p)) ** 2 for p in trade_pnls) / n
    downside_dev = math.sqrt(downside_var) if downside_var > 0 else 1e-6
    sortino = (mean_ret / downside_dev) * math.sqrt(250) if downside_dev > 0 else 0.0

    # Max Drawdown calculation
    cum_equity = [0.0]
    running = 0.0
    for p in trade_pnls:
        running += p
        cum_equity.append(running)
    peak = cum_equity[0]
    max_dd = 0.0
    for val in cum_equity:
        if val > peak:
            peak = val
        dd = peak - val
        if dd > max_dd:
            max_dd = dd
    max_dd_pct = (max_dd / max(100000.0, peak + 100000.0)) * 100.0

    # Trade expectancy and Student's t-test (secondary diagnostic)
    t_stat = (mean_ret / (std_dev / math.sqrt(n))) if n > 1 and std_dev > 0 else 0.0
    # Approximate two-tailed p-value for large N
    p_val = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0))))

    # Bootstrap 95% Confidence Intervals (1,000 resamples)
    boot_sharpes = []
    boot_win_rates = []
    random.seed(42)  # Deterministic seed for reproducible testing
    for _ in range(1000):
        sample = [random.choice(trade_pnls) for _ in range(n)]
        s_wins = sum(1 for x in sample if x > 0)
        boot_win_rates.append((s_wins / n) * 100.0)
        s_mean = sum(sample) / n
        s_var = sum((x - s_mean) ** 2 for x in sample) / (n - 1) if n > 1 else 0.0
        s_std = math.sqrt(s_var) if s_var > 0 else 1e-6
        boot_sharpes.append((s_mean / s_std) * math.sqrt(250))

    boot_sharpes.sort()
    boot_win_rates.sort()
    sharpe_ci = (boot_sharpes[25], boot_sharpes[975])
    win_rate_ci = (boot_win_rates[25], boot_win_rates[975])

    return BacktestStats(
        total_trades=n,
        winning_trades=total_wins,
        win_rate_pct=win_rate,
        profit_factor=profit_factor,
        gross_pnl=sum(trade_pnls),
        net_pnl=net_pnl,
        total_friction=total_friction,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown_pct=max_dd_pct,
        trade_expectancy_pts=mean_ret,
        t_statistic=t_stat,
        p_value=p_val,
        sharpe_ci_95=sharpe_ci,
        win_rate_ci_95=win_rate_ci,
    )


def evaluate_walk_forward(
    strategy_id: str,
    in_sample_pnls: List[float],
    out_of_sample_pnls: List[float],
    n_trials: int = 10,
) -> WalkForwardValidationReport:
    """
    Executes walk-forward statistical comparison between in-sample and out-of-sample data.
    Computes Degradation Ratio, Deflated Sharpe Ratio, and determines production deployment readiness.
    """
    is_stats = _calculate_base_metrics(in_sample_pnls)
    oos_stats = _calculate_base_metrics(out_of_sample_pnls)

    # Out-of-Sample Degradation Ratio: Sharpe_OOS / Sharpe_IS
    if is_stats.sharpe_ratio > 0:
        degradation_ratio = oos_stats.sharpe_ratio / is_stats.sharpe_ratio
    else:
        degradation_ratio = 1.0 if oos_stats.sharpe_ratio > 0 else 0.0

    # Deflated Sharpe Ratio (DSR) approximation:
    # Adjusts for multiple testing (n_trials) and non-normal returns
    gamma_euler = 0.5772156649
    expected_max_sharpe = math.sqrt(2.0 * math.log(max(1, n_trials))) + (
        gamma_euler / math.sqrt(2.0 * math.log(max(1, n_trials)))
        if n_trials > 1
        else 0.0
    )
    sharpe_diff = oos_stats.sharpe_ratio - expected_max_sharpe
    # CDF of standard normal
    dsr = 0.5 * (1.0 + math.erf(sharpe_diff / math.sqrt(2.0)))

    # Degradation Gate: If degradation ratio < 0.50 or OOS Sharpe <= 0 => MODEL_DEGRADATION
    model_degraded = (degradation_ratio < 0.50) or (oos_stats.sharpe_ratio <= 0.0) or (oos_stats.win_rate_pct < 40.0)

    if model_degraded:
        status = "DEGRADATION_FLAG"
        recommendation = "Reject deployment to live execution sandbox. Strategy edge collapsed out-of-sample."
    elif dsr < 0.70:
        status = "PROVISIONAL_REVIEW"
        recommendation = "Low Deflated Sharpe Ratio due to selection bias. Require further forward evaluation."
    else:
        status = "PASSED"
        recommendation = "Approved for Frozen Model Registry and Virtual Execution Sandbox."

    return WalkForwardValidationReport(
        strategy_id=strategy_id,
        in_sample_stats=is_stats,
        out_of_sample_stats=oos_stats,
        degradation_ratio=degradation_ratio,
        deflated_sharpe_ratio=dsr,
        model_degradation_detected=model_degraded,
        validation_status=status,
        recommendation=recommendation,
    )


def run_statistical_validation() -> Dict[str, Any]:
    """Runs standard validation across core strategy paradigms."""
    # Synthetic empirical distributions representing baseline strategies
    random.seed(101)
    is_sample = [random.normalvariate(120.0, 450.0) for _ in range(150)]
    oos_sample = [random.normalvariate(85.0, 460.0) for _ in range(80)]

    report = evaluate_walk_forward("MCE-ENSEMBLE-V1", is_sample, oos_sample)
    return report.to_dict()

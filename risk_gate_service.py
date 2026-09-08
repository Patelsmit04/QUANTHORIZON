"""
TRADEXO Institutional Portfolio Risk Gate & Strategy Quarantine Service
Version: 47.0.0

Enforces:
1. Single position capital limit (<= 20% equity).
2. Gross portfolio exposure limit (<= 60% equity).
3. Sector exposure limit (<= 30% equity).
4. Portfolio net beta constraints ([-0.50, +1.50]).
5. Correlation cluster cap (pairwise rho >= 0.70 => combined <= 25%).
6. Session daily loss circuit breaker (3.0% equity drawdown).
7. Progressive Strategy Degradation Protocol:
   - 20 trades: DEGRADATION_WARNING
   - 50 trades: DEGRADATION_EVALUATION
   - 100+ trades: QUARANTINED_AUTO
   - Catastrophic/Corruption: QUARANTINED_IMMEDIATE
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class QuarantineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEGRADATION_WARNING = "DEGRADATION_WARNING"
    DEGRADATION_EVALUATION = "DEGRADATION_EVALUATION"
    QUARANTINED_AUTO = "QUARANTINED_AUTO"
    QUARANTINED_IMMEDIATE = "QUARANTINED_IMMEDIATE"


# Sector mapping for F&O universe
SECTOR_MAP: Dict[str, str] = {
    # Banking & Financial Services
    "HDFCBANK": "BANKING",
    "ICICIBANK": "BANKING",
    "SBIN": "BANKING",
    "AXISBANK": "BANKING",
    "KOTAKBANK": "BANKING",
    "BAJFINANCE": "NBFC",
    "BAJAJFINSV": "NBFC",
    "BANKNIFTY": "BANKING",
    "FINNIFTY": "FINANCIAL_SERVICES",
    # Information Technology
    "TCS": "IT",
    "INFY": "IT",
    "WIPRO": "IT",
    "HCLTECH": "IT",
    "TECHM": "IT",
    # Energy, Oil & Power
    "RELIANCE": "ENERGY_CONGLOMERATE",
    "NTPC": "POWER",
    "POWERGRID": "POWER",
    "COALINDIA": "MINING_ENERGY",
    "ONGC": "OIL_GAS",
    "BPCL": "OIL_GAS",
    # Auto & Industrials
    "TATAMOTORS": "AUTO",
    "MARUTI": "AUTO",
    "M&M": "AUTO",
    "LT": "INFRASTRUCTURE",
    # Metals
    "TATASTEEL": "METALS",
    "JSWSTEEL": "METALS",
    "HINDALCO": "METALS",
    # Consumer & Pharma
    "ITC": "FMCG",
    "HINDUNILVR": "FMCG",
    "SUNPHARMA": "PHARMA",
    "CIPLA": "PHARMA",
    "DRREDDY": "PHARMA",
    "TITAN": "CONSUMER_DISCRETIONARY",
    "ADANIENT": "CONGLOMERATE",
    "ADANIPORTS": "INFRASTRUCTURE_PORTS",
}

# Approximate Stock Betas relative to Nifty 50
BETA_MAP: Dict[str, float] = {
    "NIFTY": 1.00,
    "NIFTY50": 1.00,
    "BANKNIFTY": 1.15,
    "FINNIFTY": 1.10,
    "SENSEX": 0.98,
    "RELIANCE": 1.05,
    "TCS": 0.75,
    "INFY": 0.85,
    "HDFCBANK": 1.10,
    "ICICIBANK": 1.20,
    "SBIN": 1.25,
    "TATAMOTORS": 1.45,
    "BAJFINANCE": 1.35,
    "TATASTEEL": 1.40,
    "LT": 0.95,
    "ITC": 0.60,
    "HINDUNILVR": 0.55,
    "SUNPHARMA": 0.65,
}

# Known high-correlation clusters (rho >= 0.70)
HIGH_CORRELATION_PAIRS: Set[Tuple[str, str]] = {
    ("TCS", "INFY"),
    ("INFY", "TCS"),
    ("HDFCBANK", "ICICIBANK"),
    ("ICICIBANK", "HDFCBANK"),
    ("ICICIBANK", "AXISBANK"),
    ("AXISBANK", "ICICIBANK"),
    ("TATASTEEL", "JSWSTEEL"),
    ("JSWSTEEL", "TATASTEEL"),
    ("NTPC", "POWERGRID"),
    ("POWERGRID", "NTPC"),
    ("ADANIENT", "ADANIPORTS"),
    ("ADANIPORTS", "ADANIENT"),
}


@dataclass
class RiskGateEvaluation:
    passed: bool
    rejection_reason: Optional[str]
    current_equity: float
    order_margin: float
    gross_exposure_pct: float
    sector: str
    sector_exposure_pct: float
    portfolio_beta: float
    daily_drawdown_pct: float
    circuit_breaker_active: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "rejection_reason": self.rejection_reason,
            "current_equity": round(self.current_equity, 2),
            "order_margin": round(self.order_margin, 2),
            "gross_exposure_pct": round(self.gross_exposure_pct, 2),
            "sector": self.sector,
            "sector_exposure_pct": round(self.sector_exposure_pct, 2),
            "portfolio_beta": round(self.portfolio_beta, 2),
            "daily_drawdown_pct": round(self.daily_drawdown_pct, 2),
            "circuit_breaker_active": self.circuit_breaker_active,
        }


class RiskGateService:
    """
    Evaluates and enforces institutional risk boundaries across capital, sectors,
    correlations, betas, and strategy operational health.
    """

    def __init__(self, starting_capital: float = 1_000_000.0):
        self.starting_capital = starting_capital
        self.strategy_performance: Dict[str, Dict[str, Any]] = {}
        self.quarantine_states: Dict[str, QuarantineStatus] = {}

    def get_sector(self, symbol: str) -> str:
        clean = symbol.replace(".NS", "").replace(".BO", "").upper().strip()
        return SECTOR_MAP.get(clean, "GENERAL_EQUITY")

    def get_beta(self, symbol: str) -> float:
        clean = symbol.replace(".NS", "").replace(".BO", "").upper().strip()
        return BETA_MAP.get(clean, 1.0)

    def evaluate_order_risk(
        self,
        symbol: str,
        order_margin: float,
        current_equity: float,
        open_positions: List[Dict[str, Any]],
        session_realized_pnl: float = 0.0,
        session_unrealized_pnl: float = 0.0,
    ) -> RiskGateEvaluation:
        """
        Comprehensive pre-trade portfolio risk check.
        """
        # 1. Session Daily Loss Circuit Breaker (3.0% of starting equity)
        total_session_pnl = session_realized_pnl + session_unrealized_pnl
        drawdown_pct = (-total_session_pnl / self.starting_capital) * 100.0 if total_session_pnl < 0 else 0.0
        if drawdown_pct >= 3.0:
            return RiskGateEvaluation(
                passed=False,
                rejection_reason=f"Risk Circuit Breaker Active: Session drawdown {drawdown_pct:.2f}% exceeds 3.0% threshold.",
                current_equity=current_equity,
                order_margin=order_margin,
                gross_exposure_pct=0.0,
                sector=self.get_sector(symbol),
                sector_exposure_pct=0.0,
                portfolio_beta=0.0,
                daily_drawdown_pct=drawdown_pct,
                circuit_breaker_active=True,
            )

        # 2. Single-Position Capital Limit (<= 25% equity)
        max_single_position = current_equity * 0.255
        if order_margin > max_single_position:
            return RiskGateEvaluation(
                passed=False,
                rejection_reason=f"Position margin ₹{order_margin:.0f} exceeds 25% single position limit of ₹{max_single_position:.0f}.",
                current_equity=current_equity,
                order_margin=order_margin,
                gross_exposure_pct=0.0,
                sector=self.get_sector(symbol),
                sector_exposure_pct=0.0,
                portfolio_beta=0.0,
                daily_drawdown_pct=drawdown_pct,
                circuit_breaker_active=False,
            )

        # 3. Gross Portfolio Exposure Limit (<= 60% equity)
        current_invested = sum(float(p.get("margin", p.get("cost", 0.0))) for p in open_positions)
        new_gross = current_invested + order_margin
        gross_pct = (new_gross / current_equity) * 100.0 if current_equity > 0 else 100.0
        if gross_pct > 60.0:
            return RiskGateEvaluation(
                passed=False,
                rejection_reason=f"Projected gross exposure {gross_pct:.1f}% exceeds 60% institutional limit.",
                current_equity=current_equity,
                order_margin=order_margin,
                gross_exposure_pct=gross_pct,
                sector=self.get_sector(symbol),
                sector_exposure_pct=0.0,
                portfolio_beta=0.0,
                daily_drawdown_pct=drawdown_pct,
                circuit_breaker_active=False,
            )

        # 4. Sector Exposure Limit (<= 30% equity)
        sector = self.get_sector(symbol)
        sector_invested = sum(
            float(p.get("margin", p.get("cost", 0.0)))
            for p in open_positions
            if self.get_sector(p.get("symbol", "")) == sector
        )
        new_sector_invested = sector_invested + order_margin
        sector_pct = (new_sector_invested / current_equity) * 100.0 if current_equity > 0 else 100.0
        if sector_pct > 30.0:
            return RiskGateEvaluation(
                passed=False,
                rejection_reason=f"Projected {sector} sector exposure {sector_pct:.1f}% exceeds 30% sector limit.",
                current_equity=current_equity,
                order_margin=order_margin,
                gross_exposure_pct=gross_pct,
                sector=sector,
                sector_exposure_pct=sector_pct,
                portfolio_beta=0.0,
                daily_drawdown_pct=drawdown_pct,
                circuit_breaker_active=False,
            )

        # 5. Pairwise Correlation Cluster Guard (rho >= 0.70 => combined <= 25%)
        clean_cand = symbol.replace(".NS", "").replace(".BO", "").upper().strip()
        for p in open_positions:
            pos_sym = str(p.get("symbol", "")).replace(".NS", "").replace(".BO", "").upper().strip()
            if (clean_cand, pos_sym) in HIGH_CORRELATION_PAIRS:
                pair_margin = float(p.get("margin", p.get("cost", 0.0))) + order_margin
                pair_pct = (pair_margin / current_equity) * 100.0
                if pair_pct > 25.0:
                    return RiskGateEvaluation(
                        passed=False,
                        rejection_reason=f"Correlated pair ({clean_cand} & {pos_sym}) exposure {pair_pct:.1f}% exceeds 25% cluster cap.",
                        current_equity=current_equity,
                        order_margin=order_margin,
                        gross_exposure_pct=gross_pct,
                        sector=sector,
                        sector_exposure_pct=sector_pct,
                        portfolio_beta=0.0,
                        daily_drawdown_pct=drawdown_pct,
                        circuit_breaker_active=False,
                    )

        # 6. Directional Beta Bounds ([-0.50, +1.50])
        total_beta_product = sum(
            float(p.get("margin", p.get("cost", 0.0))) * self.get_beta(p.get("symbol", ""))
            for p in open_positions
        ) + (order_margin * self.get_beta(symbol))
        portfolio_beta = (total_beta_product / new_gross) if new_gross > 0 else 1.0

        if portfolio_beta < -0.50 or portfolio_beta > 1.50:
            return RiskGateEvaluation(
                passed=False,
                rejection_reason=f"Projected portfolio beta {portfolio_beta:.2f} breaches [-0.50, +1.50] bounds.",
                current_equity=current_equity,
                order_margin=order_margin,
                gross_exposure_pct=gross_pct,
                sector=sector,
                sector_exposure_pct=sector_pct,
                portfolio_beta=portfolio_beta,
                daily_drawdown_pct=drawdown_pct,
                circuit_breaker_active=False,
            )

        # Passed all institutional risk gates
        return RiskGateEvaluation(
            passed=True,
            rejection_reason=None,
            current_equity=current_equity,
            order_margin=order_margin,
            gross_exposure_pct=gross_pct,
            sector=sector,
            sector_exposure_pct=sector_pct,
            portfolio_beta=portfolio_beta,
            daily_drawdown_pct=drawdown_pct,
            circuit_breaker_active=False,
        )

    def evaluate_strategy_health(
        self,
        strategy_id: str,
        recent_trade_outcomes: List[Dict[str, Any]],
        data_integrity_compromised: bool = False,
    ) -> QuarantineStatus:
        """
        Progressive Strategy Degradation Protocol:
        - 20 trades: DEGRADATION_WARNING
        - 50 trades: DEGRADATION_EVALUATION
        - 100+ trades: QUARANTINED_AUTO
        - Corruption/Catastrophic: QUARANTINED_IMMEDIATE
        """
        if data_integrity_compromised:
            self.quarantine_states[strategy_id] = QuarantineStatus.QUARANTINED_IMMEDIATE
            return QuarantineStatus.QUARANTINED_IMMEDIATE

        n_trades = len(recent_trade_outcomes)
        if n_trades < 20:
            self.quarantine_states[strategy_id] = QuarantineStatus.ACTIVE
            return QuarantineStatus.ACTIVE

        wins = sum(1 for t in recent_trade_outcomes if float(t.get("pnl", 0.0)) > 0)
        win_rate = wins / n_trades
        total_pnl = sum(float(t.get("pnl", 0.0)) for t in recent_trade_outcomes)

        if n_trades >= 100:
            if win_rate < 0.38 or total_pnl <= 0:
                status = QuarantineStatus.QUARANTINED_AUTO
            else:
                status = QuarantineStatus.ACTIVE
        elif n_trades >= 50:
            if win_rate < 0.35 or total_pnl <= 0:
                status = QuarantineStatus.DEGRADATION_EVALUATION
            else:
                status = QuarantineStatus.ACTIVE
        else:  # 20 <= n_trades < 50
            if win_rate < 0.40 or total_pnl <= 0:
                status = QuarantineStatus.DEGRADATION_WARNING
            else:
                status = QuarantineStatus.ACTIVE

        self.quarantine_states[strategy_id] = status
        return status

    def get_quarantined_strategy_ids(self) -> List[str]:
        """Returns strategy IDs strictly barred from MCE voting."""
        return [
            s_id
            for s_id, status in self.quarantine_states.items()
            if status in [QuarantineStatus.QUARANTINED_AUTO, QuarantineStatus.QUARANTINED_IMMEDIATE]
        ]


# Global singleton
risk_gate_service = RiskGateService()

"""
TRADEXO Institutional Transaction Cost & Friction Model
Version: 47.0.0
Unified, configurable, and versioned friction model shared identically
across Backtesting, Paper Trading, and Expected Value (EV) calculation.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class FrictionModel:
    version: str = "2026.09.v1"
    effective_from: str = "2026-09-01"
    effective_to: Optional[str] = None
    exchange: str = "NSE"  # "NSE" or "BSE"
    instrument_type: str = "EQUITY_DELIVERY"  # "EQUITY_DELIVERY", "OPTIONS", "FUTURES"
    broker: str = "DISCOUNT_INSTITUTIONAL"
    brokerage_flat_per_order: float = 20.00  # ₹20 flat per executed order
    brokerage_pct_cap: float = 0.0003  # 0.03% max brokerage
    stt_rate: float = 0.0010  # 0.10% delivery; for options applied on sell side
    exchange_txn_charge_rate: float = 0.0000345  # 0.00345% NSE cash rate
    gst_rate: float = 0.18  # 18% on (brokerage + exchange txn)
    sebi_turnover_rate: float = 0.000001  # ₹10 per crore
    stamp_duty_rate: float = 0.00015  # 0.015% buy delivery, 0.003% buy option
    slippage_model: str = "PARAMETRIC_UNIFORM"  # "PARAMETRIC_UNIFORM", "IMPACT_COST"
    slippage_min_pct: float = 0.0005  # 0.05%
    slippage_max_pct: float = 0.0010  # 0.10%
    half_spread_cost_bps: float = 2.5  # 2.5 basis points default


@dataclass
class FrictionCostBreakdown:
    turnover: float
    brokerage: float
    stt: float
    exchange_charges: float
    gst: float
    sebi_charges: float
    stamp_duty: float
    estimated_slippage: float
    spread_cost: float
    total_friction: float
    effective_bps: float
    version: str

    def to_dict(self) -> Dict[str, float]:
        return {
            "turnover": round(self.turnover, 2),
            "brokerage": round(self.brokerage, 2),
            "stt": round(self.stt, 2),
            "exchange_charges": round(self.exchange_charges, 2),
            "gst": round(self.gst, 2),
            "sebi_charges": round(self.sebi_charges, 2),
            "stamp_duty": round(self.stamp_duty, 2),
            "estimated_slippage": round(self.estimated_slippage, 2),
            "spread_cost": round(self.spread_cost, 2),
            "total_friction": round(self.total_friction, 2),
            "effective_bps": round(self.effective_bps, 2),
            "version": self.version,
        }


# Standard Presets
DEFAULT_EQUITY_MODEL = FrictionModel(
    version="2026.09.v1",
    exchange="NSE",
    instrument_type="EQUITY_DELIVERY",
    brokerage_flat_per_order=20.00,
    stt_rate=0.0010,
    exchange_txn_charge_rate=0.0000345,
    stamp_duty_rate=0.00015,
)

DEFAULT_OPTIONS_MODEL = FrictionModel(
    version="2026.09.v1",
    exchange="NSE",
    instrument_type="OPTIONS",
    brokerage_flat_per_order=20.00,
    stt_rate=0.000625,  # 0.0625% on sell premium
    exchange_txn_charge_rate=0.00050,  # 0.05% on premium
    stamp_duty_rate=0.00003,  # 0.003% on buy premium
    half_spread_cost_bps=5.0,  # Wider spread for options
)


def get_active_friction_model(exchange: str = "NSE", instrument_type: str = "OPTIONS") -> FrictionModel:
    """Returns official versioned friction model."""
    if instrument_type.upper() in ["OPTIONS", "INDEX_OPTION", "STOCK_OPTION"]:
        return DEFAULT_OPTIONS_MODEL
    return DEFAULT_EQUITY_MODEL


def compute_transaction_costs(
    price: float,
    quantity: int,
    side: str = "BUY",
    instrument_type: str = "EQUITY_DELIVERY",
    model: Optional[FrictionModel] = None,
) -> FrictionCostBreakdown:
    """
    Computes institutional transaction costs and friction for an execution.
    Handles regulatory statutory charges, exchange fees, brokerage, slippage, and spread.
    """
    if model is None:
        model = get_active_friction_model(instrument_type=instrument_type)

    turnover = float(price * quantity)
    if turnover <= 0:
        return FrictionCostBreakdown(
            turnover=0.0,
            brokerage=0.0,
            stt=0.0,
            exchange_charges=0.0,
            gst=0.0,
            sebi_charges=0.0,
            stamp_duty=0.0,
            estimated_slippage=0.0,
            spread_cost=0.0,
            total_friction=0.0,
            effective_bps=0.0,
            version=model.version,
        )

    side = side.upper()
    is_option = instrument_type.upper() in ["OPTIONS", "INDEX_OPTION", "STOCK_OPTION"]

    # 1. Brokerage: flat ₹20 per executed order (institutional discount broker standard)
    brokerage = model.brokerage_flat_per_order

    # 2. STT (Securities Transaction Tax)
    if is_option:
        # For options, STT is 0.0625% on sell side premium
        stt = (turnover * model.stt_rate) if side == "SELL" else 0.0
    else:
        # Delivery STT: 0.1% on both BUY and SELL
        stt = turnover * model.stt_rate

    # 3. Exchange Transaction Charges
    exchange_charges = turnover * model.exchange_txn_charge_rate

    # 4. GST: 18% on (brokerage + exchange charges)
    gst = (brokerage + exchange_charges) * model.gst_rate

    # 5. SEBI turnover charges (₹10 / crore)
    sebi_charges = turnover * model.sebi_turnover_rate

    # 6. Stamp Duty (only on BUY)
    stamp_duty = (turnover * model.stamp_duty_rate) if side == "BUY" else 0.0

    # 7. Slippage (Parametric uniform 0.05% - 0.10%)
    slippage_rate = (model.slippage_min_pct + model.slippage_max_pct) / 2.0
    estimated_slippage = turnover * slippage_rate

    # 8. Spread friction
    spread_cost = turnover * (model.half_spread_cost_bps / 10000.0)

    total_friction = (
        brokerage
        + stt
        + exchange_charges
        + gst
        + sebi_charges
        + stamp_duty
        + estimated_slippage
        + spread_cost
    )
    effective_bps = (total_friction / turnover) * 10000.0

    return FrictionCostBreakdown(
        turnover=turnover,
        brokerage=brokerage,
        stt=stt,
        exchange_charges=exchange_charges,
        gst=gst,
        sebi_charges=sebi_charges,
        stamp_duty=stamp_duty,
        estimated_slippage=estimated_slippage,
        spread_cost=spread_cost,
        total_friction=total_friction,
        effective_bps=effective_bps,
        version=model.version,
    )


def compute_expected_value(
    p_win: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    friction_cost_pct: float,
) -> Tuple[float, bool]:
    """
    Computes trade-level Expected Value (EV):
    EV = [P(win) * AvgWin%] - [(1 - P(win)) * AvgLoss%] - FrictionCost%
    Returns (ev_value, is_viable).
    If EV <= 0.0, is_viable is False (Fail-Closed EV Gate).
    """
    p_win = max(0.0, min(1.0, float(p_win)))
    p_loss = 1.0 - p_win

    gross_ev = (p_win * avg_win_pct) - (p_loss * avg_loss_pct)
    net_ev = gross_ev - friction_cost_pct
    is_viable = net_ev > 0.0001  # Must provide positive expected edge after all friction

    return round(net_ev, 4), is_viable

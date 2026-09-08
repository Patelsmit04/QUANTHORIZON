"""
TRADEXO Institutional Contract Specification Provider
Version: 47.0.0
Authoritative repository for Indian Exchange Derivative & Cash Contract Specifications.
Supports NSE and BSE separation, lot sizes, tick sizes, freeze limits, strike intervals, and expiry rules.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    exchange: str  # "NSE" or "BSE"
    instrument_type: str  # "INDEX_OPTION", "STOCK_OPTION", "EQUITY_CASH", "FUTURES"
    lot_size: int
    tick_size: float = 0.05
    strike_step: float = 50.0
    freeze_limit: int = 1800
    expiry_day: str = "THURSDAY"  # Weekly/Monthly default
    version: str = "2026.09.v1"
    effective_from: str = "2026-09-01"
    effective_to: Optional[str] = None


# Authoritative Contract Specification Registry
CONTRACT_REGISTRY: Dict[str, ContractSpec] = {
    # NSE INDICES
    "NIFTY": ContractSpec(
        symbol="NIFTY",
        exchange="NSE",
        instrument_type="INDEX_OPTION",
        lot_size=25,
        tick_size=0.05,
        strike_step=50.0,
        freeze_limit=1800,
        expiry_day="THURSDAY",
    ),
    "NIFTY50": ContractSpec(
        symbol="NIFTY50",
        exchange="NSE",
        instrument_type="INDEX_OPTION",
        lot_size=25,
        tick_size=0.05,
        strike_step=50.0,
        freeze_limit=1800,
        expiry_day="THURSDAY",
    ),
    "BANKNIFTY": ContractSpec(
        symbol="BANKNIFTY",
        exchange="NSE",
        instrument_type="INDEX_OPTION",
        lot_size=15,
        tick_size=0.05,
        strike_step=100.0,
        freeze_limit=900,
        expiry_day="WEDNESDAY",
    ),
    "FINNIFTY": ContractSpec(
        symbol="FINNIFTY",
        exchange="NSE",
        instrument_type="INDEX_OPTION",
        lot_size=25,
        tick_size=0.05,
        strike_step=50.0,
        freeze_limit=1800,
        expiry_day="TUESDAY",
    ),
    "MIDCPNIFTY": ContractSpec(
        symbol="MIDCPNIFTY",
        exchange="NSE",
        instrument_type="INDEX_OPTION",
        lot_size=50,
        tick_size=0.05,
        strike_step=25.0,
        freeze_limit=2800,
        expiry_day="MONDAY",
    ),
    # BSE INDICES
    "SENSEX": ContractSpec(
        symbol="SENSEX",
        exchange="BSE",
        instrument_type="INDEX_OPTION",
        lot_size=10,
        tick_size=0.05,
        strike_step=100.0,
        freeze_limit=1000,
        expiry_day="FRIDAY",
    ),
    "BANKEX": ContractSpec(
        symbol="BANKEX",
        exchange="BSE",
        instrument_type="INDEX_OPTION",
        lot_size=15,
        tick_size=0.05,
        strike_step=100.0,
        freeze_limit=900,
        expiry_day="MONDAY",
    ),
    # TOP NSE F&O EQUITIES
    "RELIANCE": ContractSpec(
        symbol="RELIANCE",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=250,
        tick_size=0.05,
        strike_step=20.0,
        freeze_limit=10000,
        expiry_day="LAST_THURSDAY",
    ),
    "TCS": ContractSpec(
        symbol="TCS",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=175,
        tick_size=0.05,
        strike_step=50.0,
        freeze_limit=7000,
        expiry_day="LAST_THURSDAY",
    ),
    "INFY": ContractSpec(
        symbol="INFY",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=400,
        tick_size=0.05,
        strike_step=20.0,
        freeze_limit=16000,
        expiry_day="LAST_THURSDAY",
    ),
    "HDFCBANK": ContractSpec(
        symbol="HDFCBANK",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=550,
        tick_size=0.05,
        strike_step=20.0,
        freeze_limit=22000,
        expiry_day="LAST_THURSDAY",
    ),
    "ICICIBANK": ContractSpec(
        symbol="ICICIBANK",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=700,
        tick_size=0.05,
        strike_step=10.0,
        freeze_limit=28000,
        expiry_day="LAST_THURSDAY",
    ),
    "SBIN": ContractSpec(
        symbol="SBIN",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=750,
        tick_size=0.05,
        strike_step=10.0,
        freeze_limit=30000,
        expiry_day="LAST_THURSDAY",
    ),
    "TATAMOTORS": ContractSpec(
        symbol="TATAMOTORS",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=1425,
        tick_size=0.05,
        strike_step=10.0,
        freeze_limit=42750,
        expiry_day="LAST_THURSDAY",
    ),
    "BAJFINANCE": ContractSpec(
        symbol="BAJFINANCE",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=125,
        tick_size=0.05,
        strike_step=50.0,
        freeze_limit=5000,
        expiry_day="LAST_THURSDAY",
    ),
    "BHARTIARTL": ContractSpec(
        symbol="BHARTIARTL",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=475,
        tick_size=0.05,
        strike_step=20.0,
        freeze_limit=19000,
        expiry_day="LAST_THURSDAY",
    ),
    "ITC": ContractSpec(
        symbol="ITC",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=1600,
        tick_size=0.05,
        strike_step=5.0,
        freeze_limit=64000,
        expiry_day="LAST_THURSDAY",
    ),
    "LT": ContractSpec(
        symbol="LT",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=150,
        tick_size=0.05,
        strike_step=50.0,
        freeze_limit=6000,
        expiry_day="LAST_THURSDAY",
    ),
    "AXISBANK": ContractSpec(
        symbol="AXISBANK",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=625,
        tick_size=0.05,
        strike_step=10.0,
        freeze_limit=25000,
        expiry_day="LAST_THURSDAY",
    ),
    "KOTAKBANK": ContractSpec(
        symbol="KOTAKBANK",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=400,
        tick_size=0.05,
        strike_step=20.0,
        freeze_limit=16000,
        expiry_day="LAST_THURSDAY",
    ),
    "MARUTI": ContractSpec(
        symbol="MARUTI",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=50,
        tick_size=0.05,
        strike_step=100.0,
        freeze_limit=2000,
        expiry_day="LAST_THURSDAY",
    ),
    "SUNPHARMA": ContractSpec(
        symbol="SUNPHARMA",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=350,
        tick_size=0.05,
        strike_step=20.0,
        freeze_limit=14000,
        expiry_day="LAST_THURSDAY",
    ),
    "TITAN": ContractSpec(
        symbol="TITAN",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=175,
        tick_size=0.05,
        strike_step=50.0,
        freeze_limit=7000,
        expiry_day="LAST_THURSDAY",
    ),
    "HINDUNILVR": ContractSpec(
        symbol="HINDUNILVR",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=300,
        tick_size=0.05,
        strike_step=20.0,
        freeze_limit=12000,
        expiry_day="LAST_THURSDAY",
    ),
    "WIPRO": ContractSpec(
        symbol="WIPRO",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=1500,
        tick_size=0.05,
        strike_step=5.0,
        freeze_limit=60000,
        expiry_day="LAST_THURSDAY",
    ),
    "TATASTEEL": ContractSpec(
        symbol="TATASTEEL",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=5500,
        tick_size=0.05,
        strike_step=2.5,
        freeze_limit=165000,
        expiry_day="LAST_THURSDAY",
    ),
    "POWERGRID": ContractSpec(
        symbol="POWERGRID",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=1800,
        tick_size=0.05,
        strike_step=5.0,
        freeze_limit=72000,
        expiry_day="LAST_THURSDAY",
    ),
    "NTPC": ContractSpec(
        symbol="NTPC",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=1500,
        tick_size=0.05,
        strike_step=5.0,
        freeze_limit=60000,
        expiry_day="LAST_THURSDAY",
    ),
    "ADANIENT": ContractSpec(
        symbol="ADANIENT",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=300,
        tick_size=0.05,
        strike_step=20.0,
        freeze_limit=12000,
        expiry_day="LAST_THURSDAY",
    ),
    "ADANIPORTS": ContractSpec(
        symbol="ADANIPORTS",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=400,
        tick_size=0.05,
        strike_step=20.0,
        freeze_limit=16000,
        expiry_day="LAST_THURSDAY",
    ),
    "COALINDIA": ContractSpec(
        symbol="COALINDIA",
        exchange="NSE",
        instrument_type="STOCK_OPTION",
        lot_size=1050,
        tick_size=0.05,
        strike_step=5.0,
        freeze_limit=42000,
        expiry_day="LAST_THURSDAY",
    ),
}


def clean_symbol(symbol: str) -> str:
    """Standardizes input symbol by stripping suffixes, whitespace, and case."""
    if not symbol:
        return ""
    clean = str(symbol).strip().upper()
    for suffix in [".NS", ".BO", "NSE:", "BSE:"]:
        if clean.endswith(suffix):
            clean = clean[: -len(suffix)]
        elif clean.startswith(suffix):
            clean = clean[len(suffix) :]
    return clean


def get_contract_spec(symbol: str, exchange_hint: Optional[str] = None) -> ContractSpec:
    """
    Retrieves authoritative ContractSpec. If symbol is unknown, returns
    a safe institutional default equity contract with lot size 1.
    """
    cleaned = clean_symbol(symbol)
    if cleaned in CONTRACT_REGISTRY:
        return CONTRACT_REGISTRY[cleaned]

    # Default for regular equity delivery
    exchange = "BSE" if (exchange_hint and exchange_hint.upper() == "BSE") or cleaned in ["SENSEX", "BANKEX"] else "NSE"
    return ContractSpec(
        symbol=cleaned,
        exchange=exchange,
        instrument_type="EQUITY_CASH",
        lot_size=1,
        tick_size=0.05,
        strike_step=10.0,
        freeze_limit=50000,
        expiry_day="NONE",
    )


def get_lot_size(symbol: str, is_option: bool = True) -> int:
    """
    Returns official lot size. If it's an option or F&O instrument, uses F&O lot size.
    For regular cash equities, default lot size is 1.
    """
    cleaned = clean_symbol(symbol)
    spec = get_contract_spec(cleaned)
    if not is_option and spec.instrument_type == "EQUITY_CASH":
        return 1
    # If it's an equity that is in F&O and user requests option lot size:
    return spec.lot_size if spec.lot_size > 0 else 1


def get_strike_step(symbol: str, price: Optional[float] = None) -> float:
    """Returns official strike step for symbol or falls back to price tier."""
    cleaned = clean_symbol(symbol)
    if cleaned in CONTRACT_REGISTRY:
        return CONTRACT_REGISTRY[cleaned].strike_step

    if price is not None and price > 0:
        if price > 20000:
            return 100.0
        elif price > 5000:
            return 50.0
        elif price > 1500:
            return 20.0
        elif price > 500:
            return 10.0
        elif price > 200:
            return 5.0
        else:
            return 2.5
    return 10.0


def validate_contract_order(
    symbol: str, quantity: int, price: float, is_option: bool = False
) -> Tuple[bool, str]:
    """
    Validates pre-execution contract parameters:
    1. Quantity must be > 0.
    2. For F&O/options contracts, quantity must be a strict positive multiple of lot_size.
    3. For cash equity delivery, quantity must be >= 1.
    4. Quantity must not exceed freeze limit.
    5. Price must conform to minimum tick size (0.05).
    """
    if quantity <= 0:
        return False, "Order rejected: Quantity must be strictly positive."

    spec = get_contract_spec(symbol)

    # For options or index derivatives, enforce lot size multiples
    if is_option or spec.instrument_type == "INDEX_OPTION":
        required_lot = spec.lot_size
        if quantity % required_lot != 0:
            return (
                False,
                f"Order rejected: Quantity {quantity} is not a valid multiple of lot size {required_lot} for {spec.symbol}.",
            )

    if quantity > spec.freeze_limit:
        return (
            False,
            f"Order rejected: Quantity {quantity} exceeds exchange freeze limit of {spec.freeze_limit} for {spec.symbol}.",
        )

    # Tick size check (allow tiny floating point tolerance)
    tick = spec.tick_size
    remainder = round(price % tick, 4)
    if remainder > 0.001 and abs(remainder - tick) > 0.001:
        return (
            False,
            f"Order rejected: Price {price:.2f} violates minimum tick size of {tick} for {spec.symbol}.",
        )

    return True, "Contract validation passed."

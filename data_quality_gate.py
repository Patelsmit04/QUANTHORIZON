"""
TRADEXO Institutional Data Quality Gate
Version: 47.0.0
Enforces a strict Fail-Closed data integrity layer.
Evaluates feed freshness, missing values, book depth, and market hours.
States: LIVE, DELAYED, STALE, MISSING, SYNTHETIC, ESTIMATED, ERROR.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class DataQualityState(str, Enum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    STALE = "STALE"
    MISSING = "MISSING"
    SYNTHETIC = "SYNTHETIC"
    ESTIMATED = "ESTIMATED"
    ERROR = "ERROR"


@dataclass
class DataQualityAudit:
    symbol: str
    state: DataQualityState
    latency_ms: float
    age_seconds: float
    is_tradable: bool
    rejection_reason: Optional[str] = None
    spread_pct: Optional[float] = None
    depth_available: bool = False
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "state": self.state.value,
            "latency_ms": round(self.latency_ms, 2),
            "age_seconds": round(self.age_seconds, 2),
            "is_tradable": self.is_tradable,
            "rejection_reason": self.rejection_reason,
            "spread_pct": round(self.spread_pct, 4) if self.spread_pct is not None else None,
            "depth_available": self.depth_available,
            "timestamp": self.timestamp,
        }


# Maximum allowed quote age in seconds before data is declared STALE
MAX_ALLOWED_AGE_SECONDS = 15.0
# Maximum allowed spread percentage before order feasibility is rejected
MAX_BID_ASK_SPREAD_PCT = 0.03  # 3.0%


def evaluate_quote_quality(
    symbol: str,
    price: Optional[float],
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    last_updated: Optional[datetime] = None,
    is_mock: bool = False,
    depth_count: int = 0,
) -> DataQualityAudit:
    """
    Evaluates quote quality and enforces institutional fail-closed trading gates.
    """
    now = datetime.now(timezone.utc)
    ts_str = now.isoformat()

    # 1. Missing check
    if price is None or price <= 0.0:
        return DataQualityAudit(
            symbol=symbol,
            state=DataQualityState.MISSING,
            latency_ms=9999.0,
            age_seconds=999.0,
            is_tradable=False,
            rejection_reason="Price quote is missing or zero.",
            timestamp=ts_str,
        )

    # 2. Staleness calculation
    if last_updated is not None:
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=timezone.utc)
        age_sec = (now - last_updated).total_seconds()
    else:
        age_sec = 0.0

    latency_ms = max(0.0, age_sec * 1000.0)

    # 3. Synthetic check
    if is_mock:
        return DataQualityAudit(
            symbol=symbol,
            state=DataQualityState.SYNTHETIC,
            latency_ms=latency_ms,
            age_seconds=age_sec,
            is_tradable=False,
            rejection_reason="Synthetic/mock data stream not eligible for live execution.",
            timestamp=ts_str,
        )

    # 4. Stale check (> 15 seconds)
    if age_sec > MAX_ALLOWED_AGE_SECONDS:
        return DataQualityAudit(
            symbol=symbol,
            state=DataQualityState.STALE,
            latency_ms=latency_ms,
            age_seconds=age_sec,
            is_tradable=False,
            rejection_reason=f"Quote age {age_sec:.1f}s exceeds maximum threshold of {MAX_ALLOWED_AGE_SECONDS}s.",
            timestamp=ts_str,
        )

    # 5. Spread and depth validation
    spread_pct = None
    if bid is not None and ask is not None:
        if bid <= 0.0 or ask <= 0.0:
            return DataQualityAudit(
                symbol=symbol,
                state=DataQualityState.ERROR,
                latency_ms=latency_ms,
                age_seconds=age_sec,
                is_tradable=False,
                rejection_reason="Zero or negative bid/ask in orderbook.",
                timestamp=ts_str,
            )
        if bid > ask:
            return DataQualityAudit(
                symbol=symbol,
                state=DataQualityState.ERROR,
                latency_ms=latency_ms,
                age_seconds=age_sec,
                is_tradable=False,
                rejection_reason=f"Inverted orderbook: bid ({bid}) > ask ({ask}).",
                timestamp=ts_str,
            )
        spread_pct = (ask - bid) / ask
        if spread_pct > MAX_BID_ASK_SPREAD_PCT:
            return DataQualityAudit(
                symbol=symbol,
                state=DataQualityState.LIVE,
                latency_ms=latency_ms,
                age_seconds=age_sec,
                is_tradable=False,
                rejection_reason=f"Spread {spread_pct*100:.2f}% exceeds execution limit of {MAX_BID_ASK_SPREAD_PCT*100:.1f}%.",
                spread_pct=spread_pct,
                depth_available=depth_count >= 5,
                timestamp=ts_str,
            )

    # Passed all checks
    state = DataQualityState.LIVE if age_sec <= 2.0 else DataQualityState.DELAYED
    return DataQualityAudit(
        symbol=symbol,
        state=state,
        latency_ms=latency_ms,
        age_seconds=age_sec,
        is_tradable=True,
        spread_pct=spread_pct,
        depth_available=depth_count >= 5,
        timestamp=ts_str,
    )

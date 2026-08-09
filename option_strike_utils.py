"""
STRIKE / EXPIRY / LOT-SIZE RESOLUTION FOR THE INTRADAY STRATEGY ENGINE
========================================================================
ATM/OTM strike selection reads the actual live option chain's strike list wherever one
exists (indices via options_chain_provider.py, stocks via stock_derivatives_provider.py) —
this is deliberately NOT a fixed "round to nearest N" assumption, because NSE F&O stock
strike intervals vary wildly by price band (a few rupees for a low-priced stock, Rs 100+ for
a high-priced one like MRF). Picking from the chain's own real strikes is always correct;
guessing a step is not.

SENSEX is the one asset with no live chain at all (BSE-traded, no NSE source — see
options_chain_provider.py's module docstring). For Sensex only, this module falls back to a
synthetic ATM strike (nearest Rs 100, Sensex's standard strike interval) and a configured
fallback expiry weekday. Both are hardcoded config, not derived from live data, because
there's nothing live to derive them from — flagged here for periodic manual verification,
same spirit as fo_universe.py's self-documented 6-month staleness check.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from env_utils import get_ist_now

logger = logging.getLogger("OptionStrikeUtils")

# Bank Nifty position sizing is capped at 1 lot regardless of scanner signal (global filter
# from the strategy spec — high volatility instrument).
BANKNIFTY_LOT_CAP = 1

# Sensex has no live chain to read a strike interval or expiry list from — synthetic fallback
# only. Verify these against BSE's current Sensex derivatives contract spec periodically;
# both strike interval and expiry weekday have changed under SEBI rules before and can again.
SENSEX_SYNTHETIC_STRIKE_STEP = 100
SENSEX_SYNTHETIC_EXPIRY_WEEKDAY = 1  # Monday=0 ... Tuesday=1 (BSE Sensex weekly, as of this build)

EXPIRY_ROLLOVER_HOUR_IST = 13  # after this hour, if the nearest expiry is today, roll to next


def get_atm_strike_from_chain(chain: Dict[str, Any], spot: float) -> Optional[float]:
    """Nearest real strike_price to spot from a live chain's strikes list. None if the chain
    has no usable strikes (mirrors the FAIL LOUD discipline of the chain providers)."""
    strikes = chain.get("strikes") if chain else None
    if not strikes:
        return None
    return min(strikes, key=lambda s: abs(s["strike_price"] - spot))["strike_price"]


def get_otm_strike_from_chain(chain: Dict[str, Any], spot: float, option_type: str, steps: int = 1) -> Optional[float]:
    """OTM strike `steps` positions away from ATM in the OTM direction, using the chain's own
    real strike ladder (handles irregular real-world intervals correctly). option_type: "CE"
    (OTM = higher strikes) or "PE" (OTM = lower strikes). None if there aren't enough strikes
    on that side of the chain."""
    strikes = chain.get("strikes") if chain else None
    if not strikes:
        return None

    ladder = sorted({s["strike_price"] for s in strikes})
    atm = get_atm_strike_from_chain(chain, spot)
    if atm is None or atm not in ladder:
        return None
    atm_idx = ladder.index(atm)

    if option_type.upper() == "CE":
        target_idx = atm_idx + steps
    else:
        target_idx = atm_idx - steps

    if target_idx < 0 or target_idx >= len(ladder):
        return None
    return ladder[target_idx]


def get_synthetic_atm_strike(spot: float, strike_step: int = SENSEX_SYNTHETIC_STRIKE_STEP) -> float:
    """Rounds spot to the nearest strike_step — Sensex-only fallback, no live chain exists."""
    return round(spot / strike_step) * strike_step


def get_synthetic_otm_strike(spot: float, option_type: str, steps: int = 1, strike_step: int = SENSEX_SYNTHETIC_STRIKE_STEP) -> float:
    atm = get_synthetic_atm_strike(spot, strike_step)
    offset = steps * strike_step
    return atm + offset if option_type.upper() == "CE" else atm - offset


def resolve_expiry(chain: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> Optional[str]:
    """Nearest weekly expiry from a live chain's expiry_dates list (already NSE-sorted
    ascending), rolling to the next expiry if the nearest one is today and it's past the
    rollover cutoff (default 1 PM IST) — a generalized version of the spec's "after 1PM
    Wednesday" rule that reads the real expiry weekday from the chain instead of hardcoding
    one, since NSE/BSE's weekly expiry day has changed under SEBI rules before.

    Returns the expiry string in NSE's own "DD-Mon-YYYY" format, or None if no chain/expiry
    is available (caller should fall back to resolve_synthetic_expiry for Sensex)."""
    if now is None:
        now = get_ist_now()

    expiry_dates: List[str] = (chain or {}).get("expiry_dates") or []
    if not expiry_dates:
        return None

    nearest = expiry_dates[0]
    try:
        nearest_date = datetime.strptime(nearest, "%d-%b-%Y").date()
    except ValueError:
        return nearest

    if nearest_date == now.date() and now.hour >= EXPIRY_ROLLOVER_HOUR_IST:
        return expiry_dates[1] if len(expiry_dates) > 1 else nearest
    return nearest


def resolve_synthetic_expiry(now: Optional[datetime] = None, weekday: int = SENSEX_SYNTHETIC_EXPIRY_WEEKDAY) -> str:
    """Sensex-only fallback: next occurrence of `weekday`, rolled to the following week's if
    today already is that weekday and it's past the rollover cutoff. Formatted to match the
    live-chain expiry string format ("DD-Mon-YYYY")."""
    if now is None:
        now = get_ist_now()

    days_ahead = (weekday - now.weekday()) % 7
    if days_ahead == 0 and now.hour >= EXPIRY_ROLLOVER_HOUR_IST:
        days_ahead = 7
    expiry_date = now.date() + timedelta(days=days_ahead)
    return expiry_date.strftime("%d-%b-%Y")


def apply_banknifty_lot_cap(asset: str, quantity: int) -> int:
    if asset.upper().replace(" ", "") in ("BANKNIFTY",):
        return min(quantity, BANKNIFTY_LOT_CAP)
    return quantity

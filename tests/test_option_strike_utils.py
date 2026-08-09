"""Tests for option_strike_utils.py — ATM/OTM strike resolution from a live chain, expiry
rollover logic, and the Sensex-only synthetic fallback."""
from datetime import datetime

import option_strike_utils as osu


def _chain(strikes, expiry_dates):
    return {
        "strikes": [{"strike_price": s} for s in strikes],
        "expiry_dates": expiry_dates,
    }


def test_get_atm_strike_from_chain_picks_nearest():
    chain = _chain([24400, 24450, 24500, 24550, 24600], ["14-Aug-2026"])
    assert osu.get_atm_strike_from_chain(chain, 24512) == 24500
    assert osu.get_atm_strike_from_chain(chain, 24530) == 24550


def test_get_atm_strike_from_chain_none_when_no_strikes():
    assert osu.get_atm_strike_from_chain({"strikes": []}, 100) is None
    assert osu.get_atm_strike_from_chain(None, 100) is None


def test_get_otm_strike_from_chain_call_is_above_atm():
    chain = _chain([1000, 1010, 1020, 1030, 1040], ["25-Aug-2026"])
    otm = osu.get_otm_strike_from_chain(chain, spot=1002, option_type="CE", steps=1)
    assert otm == 1010  # ATM=1000, 1 step OTM for a call = next strike up


def test_get_otm_strike_from_chain_put_is_below_atm():
    chain = _chain([980, 990, 1000, 1010, 1020], ["25-Aug-2026"])
    otm = osu.get_otm_strike_from_chain(chain, spot=1002, option_type="PE", steps=1)
    assert otm == 990  # ATM=1000, 1 step OTM for a put = next strike down


def test_get_otm_strike_from_chain_none_past_ladder_edge():
    chain = _chain([1000, 1010], ["25-Aug-2026"])
    # ATM for spot=1000 is 1000 (index 0); 1 step further OTM for a put would be off the ladder.
    assert osu.get_otm_strike_from_chain(chain, spot=1000, option_type="PE", steps=1) is None


def test_get_synthetic_atm_strike_rounds_to_nearest_step():
    assert osu.get_synthetic_atm_strike(81432, strike_step=100) == 81400
    assert osu.get_synthetic_atm_strike(81460, strike_step=100) == 81500


def test_resolve_expiry_rolls_over_after_1pm_on_expiry_day():
    chain = _chain([100], ["09-Aug-2026", "16-Aug-2026"])
    morning = datetime(2026, 8, 9, 10, 0)
    afternoon = datetime(2026, 8, 9, 14, 0)
    assert osu.resolve_expiry(chain, now=morning) == "09-Aug-2026"
    assert osu.resolve_expiry(chain, now=afternoon) == "16-Aug-2026"


def test_resolve_expiry_no_chain_returns_none():
    assert osu.resolve_expiry(None) is None
    assert osu.resolve_expiry({"expiry_dates": []}) is None


def test_resolve_synthetic_expiry_returns_configured_weekday():
    now = datetime(2026, 8, 9, 10, 0)  # Sunday
    result = osu.resolve_synthetic_expiry(now, weekday=osu.SENSEX_SYNTHETIC_EXPIRY_WEEKDAY)
    parsed = datetime.strptime(result, "%d-%b-%Y")
    assert parsed.weekday() == osu.SENSEX_SYNTHETIC_EXPIRY_WEEKDAY


def test_apply_banknifty_lot_cap_caps_only_banknifty():
    assert osu.apply_banknifty_lot_cap("BANKNIFTY", 5) == osu.BANKNIFTY_LOT_CAP
    assert osu.apply_banknifty_lot_cap("NIFTY50", 5) == 5

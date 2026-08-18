from datetime import datetime
import zoneinfo
from index_scoring import fetch_gift_nifty_live, is_gift_nifty_trading_active

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def test_fetch_gift_nifty_live_returns_structured_payload():
    result = fetch_gift_nifty_live()
    # Must return a dictionary with index_name="GIFTNIFTY", ltp > 0, price_verified=True
    assert result is not None
    assert result.get("index_name") == "GIFTNIFTY"
    assert result.get("ltp", 0) > 0
    assert result.get("price_verified") is True
    assert "signal" in result
    assert "session_info" in result


def test_is_gift_nifty_trading_active_session_1():
    # Wednesday 07:00 AM IST (Session 1 Active)
    dt_s1 = datetime(2026, 8, 19, 7, 0, tzinfo=IST)
    is_active, code, meta = is_gift_nifty_trading_active(dt_s1)
    assert is_active is True
    assert "SESSION_1" in code


def test_is_gift_nifty_trading_active_session_2():
    # Wednesday 08:30 PM IST (Session 2 US Overlap Active)
    dt_s2 = datetime(2026, 8, 19, 20, 30, tzinfo=IST)
    is_active, code, meta = is_gift_nifty_trading_active(dt_s2)
    assert is_active is True
    assert "SESSION_2" in code

    # Thursday 02:00 AM IST (Session 2 Late Night Continuation)
    dt_s2_night = datetime(2026, 8, 20, 2, 0, tzinfo=IST)
    is_active_n, code_n, meta_n = is_gift_nifty_trading_active(dt_s2_night)
    assert is_active_n is True
    assert "SESSION_2" in code_n


def test_is_gift_nifty_maintenance_break():
    # Wednesday 03:45 PM IST (Maintenance Break 03:40 - 03:58 PM)
    dt_break = datetime(2026, 8, 19, 15, 45, tzinfo=IST)
    is_active, code, meta = is_gift_nifty_trading_active(dt_break)
    assert is_active is False
    assert code == "MAINTENANCE_BREAK"


def test_is_gift_nifty_weekend_closed():
    # Sunday 12:00 PM IST
    dt_sun = datetime(2026, 8, 23, 12, 0, tzinfo=IST)
    is_active, code, meta = is_gift_nifty_trading_active(dt_sun)
    assert is_active is False
    assert code == "WEEKEND_CLOSED"

import pytest
from fo_universe import is_valid_fo_stock, get_active_fo_set, NSE_FO_STOCKS

def test_is_valid_fo_stock_validates_canonical_stocks():
    assert is_valid_fo_stock("RELIANCE") is True
    assert is_valid_fo_stock("RELIANCE.NS") is True
    assert is_valid_fo_stock("INFY") is True
    assert is_valid_fo_stock("INVALID_TICKER_XYZ") is False

def test_get_active_fo_set_returns_non_empty_set():
    active = get_active_fo_set()
    assert isinstance(active, set)
    assert len(active) >= 200
    assert "RELIANCE" in active

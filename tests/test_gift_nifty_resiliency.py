from index_scoring import fetch_gift_nifty_live

def test_fetch_gift_nifty_live_returns_structured_payload():
    result = fetch_gift_nifty_live()
    # Must return a dictionary with index_name="GIFTNIFTY", ltp > 0, price_verified=True
    assert result is not None
    assert result.get("index_name") == "GIFTNIFTY"
    assert result.get("ltp", 0) > 0
    assert result.get("price_verified") is True
    assert "signal" in result

import pytest
from news_provider import classify_news_signal, apply_news_gate

def test_negative_macro_headlines_classified_negative():
    headlines_cases = [
        {"title": "Market recovery at risk: Will bond yield spike, interest rate fear deepen Sensex, Nifty losses after two years of negative returns? - Fortune India"},
        {"title": "Indian Markets Tumble: Sensex Drops 553 Pts, Oil Prices Soar - Rediff MoneyWiz"},
        {"title": "Sensex, Nifty slip amid RBI norms... banks lead decline - Business Standard"},
        {"title": "West Asia crisis: Down 3%, Indian stocks log worst week in over one year - Business Standard"}
    ]
    for h in headlines_cases:
        res = classify_news_signal([h])
        assert res["verdict"] in ("NEGATIVE", "CAUTION"), f"Failed for {h['title']}: got {res['verdict']}"
        assert res["sentiment_score"] < 0.0, f"Expected negative score for {h['title']}, got {res['sentiment_score']}"

def test_positive_price_moves_and_record_highs():
    positive_cases = [
        {"title": "Tata Consultancy Services Ltd. Share Price Today Up 3.07% - univest.in"},
        {"title": "Sensex, Nifty 50 jump to record highs... What drove the Indian stock market higher? Explained - Livemint"},
        {"title": "Nifty, Sensex hit fresh record highs: RBI MPC outcome in focus - The Times of India"}
    ]
    for h in positive_cases:
        res = classify_news_signal([h])
        assert res["verdict"] == "POSITIVE", f"Failed for {h['title']}: got {res['verdict']}"
        assert res["sentiment_score"] > 0.0, f"Expected positive score for {h['title']}, got {res['sentiment_score']}"

def test_stock_specific_risk_and_target_cut():
    neg_stock_cases = [
        {"title": "TCS Share Price Slides, Hits 52-Week Low as IT Stocks Face Heavy Selloff - HDFC Sky"},
        {"title": "TCS, Tata Motors PV, Tata Steel shares slide up to 6% as N Chandrasekaran steps down; key details - Upstox"}
    ]
    for h in neg_stock_cases:
        res = classify_news_signal([h])
        assert res["verdict"] in ("NEGATIVE", "CAUTION"), f"Failed for {h['title']}: got {res['verdict']}"
        assert res["sentiment_score"] < 0.0

    target_cut_case = [{"title": "Tata Consultancy Services Limited Just Reported Earnings, And Analysts Cut Their Target Price - simplywall.st"}]
    res_cut = classify_news_signal(target_cut_case)
    assert res_cut["verdict"] in ("CAUTION", "NEGATIVE")
    assert res_cut["sentiment_score"] < 0.0

def test_pillar5_news_gate_protection():
    # If classifier tags negative, Pillar 5 must downgrade priority
    stock = {
        "symbol": "TCS",
        "priority_level": "P1_HIGH",
        "conviction_level": "HIGH_CONVICTION"
    }
    classification = classify_news_signal([
        {"title": "TCS Share Price Slides, Hits 52-Week Low as IT Stocks Face Heavy Selloff"}
    ])
    assert classification["verdict"] == "NEGATIVE"
    
    gated_stock = apply_news_gate(stock, classification)
    assert gated_stock["priority_level"] == "P3_LOW", "Pillar 5 must demote priority to P3_LOW on negative news"
    assert "Capped" in gated_stock["news_signal"]["gate_applied"]

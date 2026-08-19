import pytest
from fastapi.testclient import TestClient
from news_provider import classify_news_signal, apply_news_gate
from event_calendar import has_high_impact_event_within
from app import app

client = TestClient(app)

def test_api_news_endpoint():
    res = client.get("/api/news")
    assert res.status_code == 200
    data = res.json()
    assert "stocks" in data
    assert "global_news" in data

def test_api_news_global_endpoint():
    res = client.get("/api/news/global")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "categorized" in data
    assert "central_banks" in data["categorized"]
    assert "commodities" in data["categorized"]
    assert "currencies_and_yields" in data["categorized"]
    assert "global_indices" in data["categorized"]

def test_api_news_symbol_endpoint():
    res = client.get("/api/news/RELIANCE")
    assert res.status_code == 200
    data = res.json()
    assert data.get("symbol") == "RELIANCE"
    assert "classification" in data

def test_sentiment_classifier_keyword_bounds():
    # Negative headlines (fraud, scam, downgrade)
    neg_headlines = [
        {"title": "Company faces SEBI fraud probe and raid", "description": "Investigation into financial scam and irregularities"},
        {"title": "Credit rating downgraded to default warning", "description": "Severe debt crisis and bankruptcy risk"}
    ]
    neg_res = classify_news_signal(neg_headlines)
    assert neg_res["verdict"] == "NEGATIVE"
    assert neg_res["sentiment_score"] <= -0.50

    # Positive headlines (profit jump, order win)
    pos_headlines = [
        {"title": "Company reports record profit jump and margin expansion", "description": "Strong earnings beats estimates"},
        {"title": "Bags major order win and expansion", "description": "New partnership and robust growth"}
    ]
    pos_res = classify_news_signal(pos_headlines)
    assert pos_res["verdict"] == "POSITIVE"
    assert pos_res["sentiment_score"] > 0.0

def test_apply_news_gate_downgrade():
    stock = {
        "symbol": "ABC",
        "priority_level": "P1_HIGH",
        "conviction_level": "HIGH_CONVICTION"
    }
    classification = {"verdict": "NEGATIVE", "sentiment_score": -0.8}
    gated = apply_news_gate(stock, classification)
    assert gated["priority_level"] == "P3_LOW"
    assert gated["conviction_level"] == "MODERATE"

def test_high_impact_event_calendar():
    # Non-existent asset should not throw error
    has_event = has_high_impact_event_within("NON_EXISTENT_ASSET", hours=48)
    assert isinstance(has_event, bool)

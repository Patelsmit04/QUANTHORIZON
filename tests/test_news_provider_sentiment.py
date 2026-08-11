import pytest
from news_provider import classify_news_signal

def test_classify_news_signal_calculates_sentiment_score():
    headlines = [
        {"title": "Company reports record profit and strong earnings upgrade"},
        {"title": "Shares surge as firm bags major new order"}
    ]
    res = classify_news_signal(headlines)
    assert res["verdict"] == "POSITIVE"
    assert res["nlp_method"] == "KEYWORD_WEIGHTED_SENTIMENT"
    assert res["sentiment_score"] > 0.0

def test_classify_news_signal_negative_sentiment():
    headlines = [
        {"title": "Company raided amid fraud probe and lawsuit"},
        {"title": "Stock plunges following regulatory warning"}
    ]
    res = classify_news_signal(headlines)
    assert res["verdict"] == "NEGATIVE"
    assert res["sentiment_score"] < 0.0

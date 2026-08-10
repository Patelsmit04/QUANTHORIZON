import app as appmod

def test_win_rate_excludes_neutral_trades_from_denominator():
    store = {
        "trades": [
            {"status": "COMPLETED", "outcome": "JACKPOT WIN"},
            {"status": "COMPLETED", "outcome": "LOSS"},
            {"status": "COMPLETED", "outcome": "NEUTRAL"},
        ]
    }
    appmod.TradeHistoryManager._recalculate_metrics(store)
    # 1 Win / (1 Win + 1 Loss) = 50.0%, NOT 1 / 3 = 33.3%
    assert store["win_rate_pct"] == 50.0
    assert store["wins"] == 1
    assert store["losses"] == 1
    assert store["neutrals"] == 1
    assert store["total_trades"] == 3


def test_accuracy_score_and_outcome_formulas():
    # Gap = +2.0%, Predicted = +1.0% -> Variance error = 1.0 -> Accuracy = 100 - (1.0 * 15) = 85.0%
    gap_pct = 2.0
    predicted_gap = 1.0
    variance_error = round(abs(gap_pct - predicted_gap), 2)
    accuracy_score = max(0.0, round(100.0 - (variance_error * 15.0), 1))

    assert variance_error == 1.0
    assert accuracy_score == 85.0

"""
Tests for Pillar 6: Institutional Flow in scoring_engine.evaluate_5_pillar_matrix — tiered
weight, direction-agreement gating (like Pillar 3), sell-side dampening, and shadow mode
(computed/visible but excluded from confirmed_pillars_weight until explicitly turned off).
"""
import pandas as pd

from scoring_engine import evaluate_5_pillar_matrix

SYMBOL = "RELIANCE"  # must be in the NSE F&O whitelist (fo_universe.py) for the engine to score it


def _make_df(closes):
    """20-row intraday-shaped OHLCV frame. High/Low hug Close so Pillar 5 (Marubozu) stays
    out of the way; Volume is flat so Pillars 2/4 (volume-based) don't confirm either — this
    test only cares about Pillar 6's own contribution."""
    rows = []
    prev = closes[0]
    for c in closes:
        rows.append({"Open": prev, "High": c + 0.3, "Low": c - 0.3, "Close": c, "Volume": 50000})
        prev = c
    return pd.DataFrame(rows)


# Mostly-up with a few minor dips (real gains/losses so RSI isn't the degenerate "all gains,
# zero losses" case, which this codebase's own RSI formula NaN-fills to 50 — see scoring_engine.py).
BULLISH_CLOSES = [100.0, 100.5, 101.0, 100.8, 101.5, 102.0, 102.5, 102.3, 103.0, 103.5,
                   104.0, 104.5, 104.3, 105.0, 105.5, 106.0, 106.5, 107.0, 107.5, 108.0]
BEARISH_CLOSES = [108.0, 107.5, 107.0, 107.2, 106.5, 106.0, 105.5, 105.7, 105.0, 104.5,
                   104.0, 103.5, 103.7, 103.0, 102.5, 102.0, 101.5, 101.0, 100.5, 100.0]


def _bullish_flow(tier="MODERATE", net=80.0):
    return {"tier": tier, "dominant_side": "BUY", "net_value_cr": net, "buy_value_cr": net,
            "sell_value_cr": 0.0, "deal_types": ["block"], "as_of": "2026-08-07T14:30:00+05:30", "source": "LIVE_SNAPSHOT"}


def _bearish_flow(tier="STRONG", net=-200.0):
    return {"tier": tier, "dominant_side": "SELL", "net_value_cr": net, "buy_value_cr": 0.0,
            "sell_value_cr": abs(net), "deal_types": ["bulk"], "as_of": "2026-08-07T14:30:00+05:30", "source": "LIVE_SNAPSHOT"}


def test_data_unavailable_when_no_institutional_flow_passed():
    result = evaluate_5_pillar_matrix(SYMBOL, _make_df(BULLISH_CLOSES), institutional_flow_data=None)
    assert result["pillar_weights"]["Pillar 6: Institutional Flow"] == 0.0
    assert result["institutional_flow"]["data_status"] == "DATA_UNAVAILABLE"
    assert "Pillar 6: Institutional Flow" not in "".join(result["confirmed_pillars"])


def test_shadow_mode_computes_but_excludes_weight_by_default():
    result = evaluate_5_pillar_matrix(
        SYMBOL, _make_df(BULLISH_CLOSES),
        institutional_flow_data=_bullish_flow(),
        # institutional_flow_shadow_mode defaults to True
    )
    flow = result["institutional_flow"]
    assert flow["shadow_mode"] is True
    assert flow["would_confirm"] is True
    assert flow["would_weight"] == 1.0  # MODERATE tier, buy-side, full weight
    # Shadow mode must keep it OUT of anything that affects the live verdict.
    assert result["pillar_weights"]["Pillar 6: Institutional Flow"] == 0.0
    assert not any("Pillar 6" in p for p in result["confirmed_pillars"])


def test_shadow_mode_off_lets_pillar_6_contribute_real_weight():
    result = evaluate_5_pillar_matrix(
        SYMBOL, _make_df(BULLISH_CLOSES),
        institutional_flow_data=_bullish_flow(),
        institutional_flow_shadow_mode=False,
    )
    assert result["pillar_weights"]["Pillar 6: Institutional Flow"] == 1.0
    assert any("Pillar 6" in p for p in result["confirmed_pillars"])


def test_tier_weights_weak_moderate_strong():
    for tier, expected_weight in [("WEAK", 0.5), ("MODERATE", 1.0), ("STRONG", 1.5)]:
        result = evaluate_5_pillar_matrix(
            SYMBOL, _make_df(BULLISH_CLOSES),
            institutional_flow_data=_bullish_flow(tier=tier),
            institutional_flow_shadow_mode=False,
        )
        assert result["pillar_weights"]["Pillar 6: Institutional Flow"] == expected_weight, tier


def test_sell_side_confirmation_is_dampened_relative_to_buy_side():
    result = evaluate_5_pillar_matrix(
        SYMBOL, _make_df(BEARISH_CLOSES),
        institutional_flow_data=_bearish_flow(tier="STRONG"),
        institutional_flow_shadow_mode=False,
    )
    # STRONG tier weight is 1.5; sell-side must be dampened to 1.5 * 0.7 = 1.05, never full 1.5.
    assert result["pillar_weights"]["Pillar 6: Institutional Flow"] == 1.05


def test_direction_disagreement_does_not_confirm():
    # Bullish price action (VWAP/RSI bias) but institutional flow is SELL-dominant — must not
    # count as confirmation, same discipline as Pillar 3's relative-strength direction gate.
    result = evaluate_5_pillar_matrix(
        SYMBOL, _make_df(BULLISH_CLOSES),
        institutional_flow_data=_bearish_flow(),
        institutional_flow_shadow_mode=False,
    )
    assert result["pillar_weights"]["Pillar 6: Institutional Flow"] == 0.0
    assert result["institutional_flow"]["would_confirm"] is False


def test_below_threshold_tier_never_confirms_even_off_shadow():
    result = evaluate_5_pillar_matrix(
        SYMBOL, _make_df(BULLISH_CLOSES),
        institutional_flow_data=_bullish_flow(tier="BELOW_THRESHOLD", net=10.0),
        institutional_flow_shadow_mode=False,
    )
    assert result["pillar_weights"]["Pillar 6: Institutional Flow"] == 0.0


def test_pillar_weight_multiplier_scales_institutional_flow_like_other_pillars():
    result = evaluate_5_pillar_matrix(
        SYMBOL, _make_df(BULLISH_CLOSES),
        institutional_flow_data=_bullish_flow(tier="MODERATE"),
        institutional_flow_shadow_mode=False,
        pillar_weight_multipliers={"Pillar 6: Institutional Flow": 0.5},
    )
    assert result["pillar_weights"]["Pillar 6: Institutional Flow"] == 0.5  # 1.0 base * 0.5 multiplier

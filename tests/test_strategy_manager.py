"""
M7 audit fixes in strategy_manager.py:
1. required_weight_override is now validated (must be None or a positive number) — previously
   a value of 0 or negative silently made the confirmation gate always pass.
2. The built-in Default 5-Pillar strategy's scoring configuration (scope/pillars/weight-bar/
   gates) can no longer be silently rewritten via PUT — only deactivation and deletion were
   ever blocked before.
"""
import pytest

import strategy_manager as sm


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "STRATEGIES_FILE", str(tmp_path / "strategies.json"))
    monkeypatch.setattr(sm, "generate_clarification", lambda strategy, correction_note=None: {
        "plain_summary": "test clarification", "assumptions": [],
    })
    sm._seed_default_strategy_if_missing()
    yield


@pytest.mark.parametrize("bad_value", [0, -1.0, -0.01, "not-a-number", True])
def test_validate_required_weight_override_rejects_invalid(bad_value):
    with pytest.raises(ValueError):
        sm._validate_required_weight_override(bad_value)


@pytest.mark.parametrize("good_value", [None, 0.01, 1.0, 4.5])
def test_validate_required_weight_override_accepts_valid(good_value):
    sm._validate_required_weight_override(good_value)  # must not raise


def test_create_strategy_draft_rejects_bad_weight_override_before_clarification(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("generate_clarification should not be called when validation fails first")

    monkeypatch.setattr(sm, "generate_clarification", fail_if_called)

    with pytest.raises(ValueError):
        sm.create_strategy_draft(name="Bad Strategy", required_weight_override=-5.0)


def test_builtin_strategy_config_cannot_be_changed():
    with pytest.raises(ValueError):
        sm.update_strategy(sm.DEFAULT_STRATEGY_ID, active_pillars={"Pillar 1: Futures OI": False})

    with pytest.raises(ValueError):
        sm.update_strategy(sm.DEFAULT_STRATEGY_ID, required_weight_override=3.0)

    with pytest.raises(ValueError):
        sm.update_strategy(sm.DEFAULT_STRATEGY_ID, target_scope=["STOCKS"])

    # Scoring config must be provably untouched after every rejected attempt.
    strategy = sm.get_strategy(sm.DEFAULT_STRATEGY_ID)
    assert strategy["active_pillars"]["Pillar 1: Futures OI"] is True
    assert strategy["required_weight_override"] is None


def test_builtin_strategy_cosmetic_fields_can_still_be_changed():
    updated = sm.update_strategy(sm.DEFAULT_STRATEGY_ID, description="Updated description")
    assert updated["description"] == "Updated description"


def test_builtin_strategy_still_cannot_be_deactivated():
    with pytest.raises(ValueError):
        sm.update_strategy(sm.DEFAULT_STRATEGY_ID, is_active=False)


def test_custom_strategy_weight_override_validated_on_update():
    draft = sm.create_strategy_draft(name="Custom Strategy")
    with pytest.raises(ValueError):
        sm.update_strategy(draft["id"], required_weight_override=0)

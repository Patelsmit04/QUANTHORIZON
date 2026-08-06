"""
M7 audit fix: fetch_india_vix() must report (None, "UNAVAILABLE") on total feed failure,
never a fabricated (15.0, "NORMAL") reading indistinguishable from a real one.
"""
import vix_provider


def test_fetch_india_vix_reports_unavailable_on_total_failure(monkeypatch):
    def always_fails(fn, label=None, **kwargs):
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(vix_provider, "call_with_retry", always_fails)

    vix_val, vix_regime = vix_provider.fetch_india_vix()

    assert vix_val is None
    assert vix_regime == "UNAVAILABLE"


def test_fetch_india_vix_returns_real_value_when_feed_succeeds(monkeypatch):
    import pandas as pd

    def fake_call_with_retry(fn, label=None, **kwargs):
        return pd.DataFrame({"Close": [14.2, 15.75]})

    monkeypatch.setattr(vix_provider, "call_with_retry", fake_call_with_retry)

    vix_val, vix_regime = vix_provider.fetch_india_vix()

    assert vix_val == 15.75
    assert vix_regime == "NORMAL"


def test_classify_vix_regime_boundaries():
    assert vix_provider.classify_vix_regime(12.99) == "LOW_VOL"
    assert vix_provider.classify_vix_regime(13.0) == "NORMAL"
    assert vix_provider.classify_vix_regime(18.0) == "NORMAL"
    assert vix_provider.classify_vix_regime(18.01) == "HIGH_VOL"

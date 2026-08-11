import os
import pytest
from app import get_market_schedule_info, cache_store

def test_audio_synthesizer_frequency_parameters_in_static_app_js():
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "app.js")
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "AudioContext" in content, "Missing Web Audio API AudioContext initialization"
    assert "587.33" in content, "Missing D5 tone frequency (587.33 Hz)"
    assert "880.00" in content, "Missing A5 tone frequency (880.00 Hz)"
    assert "exponentialRampToValueAtTime" in content, "Missing exponential gain decay ramp"
    assert "playNotificationSound" in content, "Missing playNotificationSound function"

def test_operator_timeline_schedule_info_status():
    info = get_market_schedule_info()
    assert "status" in info
    assert "is_open" in info
    assert "mode" in info
    assert "sleep_seconds" in info

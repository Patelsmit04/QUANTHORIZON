import os
import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import sentry_config


class TestSentryIntegration(unittest.TestCase):
    def test_sentry_disabled_by_default_without_dsn(self):
        """When SENTRY_DSN is not set in env, sentry functions are safe zero-cost no-ops."""
        with patch.dict(os.environ, {"SENTRY_DSN": ""}, clear=False):
            # Reset state for unit test
            sentry_config._initialized = False
            sentry_config._enabled = False

            enabled = sentry_config.init_sentry()
            self.assertFalse(enabled)
            self.assertFalse(sentry_config._enabled)

            # All helper functions must be safe no-ops and never raise
            try:
                sentry_config.capture_exception(ValueError("Test error"), symbol="RELIANCE.NS")
                sentry_config.capture_message("Test message", level="warning", test=True)
                sentry_config.set_context("test_ctx", {"a": 1})
                sentry_config.add_breadcrumb("test breadcrumb", category="test")
            except Exception as e:
                self.fail(f"Sentry helper functions raised while disabled: {e}")

    def test_sentry_api_endpoint(self):
        """Test GET /api/sentry_dsn returns the public configuration for frontend JS."""
        from app import app
        client = TestClient(app)

        with patch.dict(os.environ, {"SENTRY_DSN": "https://dummykey@o0.ingest.sentry.io/123", "SENTRY_ENVIRONMENT": "staging"}, clear=False):
            resp = client.get("/api/sentry_dsn")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["dsn"], "https://dummykey@o0.ingest.sentry.io/123")
            self.assertEqual(data["environment"], "staging")
            self.assertIn("release", data)

    def test_before_send_filter(self):
        """Pre-send filter should drop client disconnects and keyboard interrupts, but tag market events."""
        event = {}
        hint = {"exc_info": (ConnectionResetError, ConnectionResetError("Connection reset"), None)}
        filtered = sentry_config._before_send(event, hint)
        self.assertIsNone(filtered)

        # Non-dropped exception should get ist_time tag
        real_event = {"tags": {}}
        real_hint = {"exc_info": (ValueError, ValueError("Something bad"), None)}
        res = sentry_config._before_send(real_event, real_hint)
        self.assertIsNotNone(res)
        self.assertIn("ist_time", res.get("tags", {}))


if __name__ == "__main__":
    unittest.main()

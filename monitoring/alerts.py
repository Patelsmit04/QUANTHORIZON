"""
Alert channel senders for the external health monitor (see health_monitor.py).

Every sender is independently optional -- configured purely by whether its environment
variable is set. Missing credentials for a channel just means that channel is skipped, not an
error; the monitor must keep working with zero, one, or all three channels configured.

Channels:
    Telegram -> TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    Discord  -> DISCORD_WEBHOOK_URL
    Slack    -> SLACK_WEBHOOK_URL

No secrets are ever logged or embedded in code -- all read from the environment at call time.
"""

import os
import logging
from typing import List

import requests

logger = logging.getLogger("HealthMonitor.Alerts")

_REQUEST_TIMEOUT_SECONDS = 10


def _send_telegram(message: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            logger.warning(f"Telegram alert failed: HTTP {resp.status_code} {resp.text[:200]}")
            return False
        return True
    except requests.RequestException as e:
        logger.warning(f"Telegram alert failed: {e}")
        return False


def _send_discord(message: str) -> bool:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return False
    try:
        resp = requests.post(webhook_url, json={"content": message}, timeout=_REQUEST_TIMEOUT_SECONDS)
        if resp.status_code not in (200, 204):
            logger.warning(f"Discord alert failed: HTTP {resp.status_code} {resp.text[:200]}")
            return False
        return True
    except requests.RequestException as e:
        logger.warning(f"Discord alert failed: {e}")
        return False


def _send_slack(message: str) -> bool:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return False
    try:
        resp = requests.post(webhook_url, json={"text": message}, timeout=_REQUEST_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            logger.warning(f"Slack alert failed: HTTP {resp.status_code} {resp.text[:200]}")
            return False
        return True
    except requests.RequestException as e:
        logger.warning(f"Slack alert failed: {e}")
        return False


def send_alert(message: str) -> List[str]:
    """Sends `message` to every configured channel. Returns the list of channel names that
    actually accepted it -- never raises, so a broken alert channel can't crash the monitor
    run or block state from being saved."""
    sent_to = []
    if _send_telegram(message):
        sent_to.append("telegram")
    if _send_discord(message):
        sent_to.append("discord")
    if _send_slack(message):
        sent_to.append("slack")
    if not sent_to:
        logger.info("No alert channel configured/succeeded -- alert was only logged, not delivered.")
    return sent_to

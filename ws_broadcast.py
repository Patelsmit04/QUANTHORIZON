"""
WebSocket broadcast infrastructure — /ws/live pushes live events (closing-sequence step
completions, scan updates) to connected clients, so a dashboard doesn't have to poll to find
out something changed.

QUANTHORIZON's background scheduler runs as plain OS threads (threading.Thread), not asyncio
tasks — broadcasting from those threads into WebSocket connections owned by FastAPI's asyncio
event loop needs an explicit bridge: asyncio.run_coroutine_threadsafe(). The alternative
(converting both scheduler threads' synchronous yfinance/jugaad_data calls to run on the event
loop) would be a much bigger, riskier change than this milestone's scope. capture_event_loop()
is called once at FastAPI startup — from inside the running event loop, via the startup hook —
so broadcast_sync() has a valid loop reference to bridge into from any thread for the life of
the process.
"""

import json
import logging
import asyncio
from typing import Dict, Any, List, Optional

from fastapi import WebSocket

logger = logging.getLogger("WSBroadcast")

_active_connections: List[WebSocket] = []
_event_loop: Optional[asyncio.AbstractEventLoop] = None


def capture_event_loop() -> None:
    """Call once, from inside a running event loop (FastAPI's startup hook) — stores the
    reference broadcast_sync() bridges into from any OS thread."""
    global _event_loop
    _event_loop = asyncio.get_running_loop()


async def register(websocket: WebSocket) -> None:
    await websocket.accept()
    _active_connections.append(websocket)
    logger.info(f"WS client connected ({len(_active_connections)} active).")


def unregister(websocket: WebSocket) -> None:
    if websocket in _active_connections:
        _active_connections.remove(websocket)
        logger.info(f"WS client disconnected ({len(_active_connections)} active).")


async def broadcast(message: Dict[str, Any]) -> None:
    """Push a JSON message to every connected client. Call this directly when already inside
    the event loop (e.g. a FastAPI route); scheduler threads must use broadcast_sync() instead."""
    if not _active_connections:
        return
    payload = json.dumps(message, default=str)
    dead = []
    for ws in _active_connections:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        unregister(ws)


def broadcast_sync(message: Dict[str, Any]) -> None:
    """Thread-safe entry point for the background scheduler threads, which are NOT running
    inside the asyncio event loop. Best-effort by design: a broadcast failure (no loop
    captured yet, no clients connected, a scheduling error) is logged and swallowed, never
    raised — a scheduler tick must never fail because nobody's watching the dashboard."""
    if _event_loop is None:
        logger.debug("broadcast_sync called before the event loop was captured — dropping message.")
        return
    if not _active_connections:
        return  # nothing to do — avoids scheduling a coroutine for zero recipients
    try:
        asyncio.run_coroutine_threadsafe(broadcast(message), _event_loop)
    except Exception as e:
        logger.warning(f"broadcast_sync failed to schedule a broadcast: {e}")

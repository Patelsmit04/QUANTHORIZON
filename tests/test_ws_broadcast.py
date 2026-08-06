"""
M8 audit fix: broadcast() now iterates a snapshot of _active_connections, not the live list —
a disconnect's unregister() call landing mid-broadcast (while an earlier `await send_text`
is suspended) can no longer mutate the list broadcast() is still iterating over.
"""
import asyncio

import pytest

import ws_broadcast


class FakeWebSocket:
    def __init__(self, name, disconnect_others_on_send=None):
        self.name = name
        self.sent = []
        self._disconnect_others_on_send = disconnect_others_on_send or []

    async def send_text(self, payload):
        # Simulate another coroutine unregistering connections while THIS send is "in flight" —
        # this models the real hazard: an await point during which the event loop can run
        # other ready coroutines that mutate the shared list.
        for victim in self._disconnect_others_on_send:
            ws_broadcast.unregister(victim)
        self.sent.append(payload)


@pytest.fixture(autouse=True)
def clean_connections():
    ws_broadcast._active_connections.clear()
    yield
    ws_broadcast._active_connections.clear()


def test_broadcast_reaches_every_connection_despite_concurrent_disconnect():
    """
    The actual failure mode: connection A's OWN disconnect gets detected and unregistered by
    a concurrent task (e.g. its receive-loop noticing a close frame) WHILE broadcast() is still
    suspended inside `await ws_a.send_text(...)`. Iterating the live list, removing the
    CURRENTLY-being-visited element shifts the next element (B) into A's already-consumed
    index — the for-loop then advances past it, skipping B entirely, even though B is a live,
    unrelated connection that should have received the message. (Removing some OTHER,
    not-yet-visited connection does NOT reproduce this — Python's list iteration naturally
    "absorbs" that shift without skipping anything, which is why this specific scenario matters.)
    """
    ws_c = FakeWebSocket("C")
    ws_b = FakeWebSocket("B")
    ws_a = FakeWebSocket("A")
    ws_a._disconnect_others_on_send = [ws_a]  # self-unregister mid-send

    ws_broadcast._active_connections.extend([ws_a, ws_b, ws_c])

    asyncio.run(ws_broadcast.broadcast({"type": "test"}))

    assert len(ws_a.sent) == 1
    assert len(ws_b.sent) == 1  # this is the one the old live-list iteration would skip
    assert len(ws_c.sent) == 1
    assert ws_a not in ws_broadcast._active_connections
    assert ws_b in ws_broadcast._active_connections
    assert ws_c in ws_broadcast._active_connections

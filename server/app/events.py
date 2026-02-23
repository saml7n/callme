"""In-memory event bus for broadcasting live call events to WebSocket clients.

Events are simple dicts with ``type`` and ``call_id`` keys, plus event-specific
data.  The bus fans out each event to all connected listeners.

Event types:
- ``call_started``  — {call_id, caller_number, workflow_name, timestamp}
- ``transcript``    — {call_id, role: "caller"|"ai", text, timestamp}
- ``node_transition`` — {call_id, from_node, to_node, timestamp}
- ``call_ended``    — {call_id, duration, timestamp}
- ``transfer_started`` — {call_id, target_number, timestamp}
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    """Broadcast live-call events to multiple WebSocket consumers."""

    def __init__(self) -> None:
        self._listeners: list[asyncio.Queue[dict[str, Any]]] = []
        # Active calls: call_id → metadata dict
        self._active_calls: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Active call registry
    # ------------------------------------------------------------------

    def register_call(
        self,
        call_id: str,
        call_sid: str = "",
        caller_number: str = "",
        workflow_name: str = "",
    ) -> None:
        """Register a call as active and broadcast ``call_started``."""
        meta = {
            "call_id": call_id,
            "call_sid": call_sid,
            "caller_number": caller_number,
            "workflow_name": workflow_name,
            "started_at": time.time(),
        }
        self._active_calls[call_id] = meta
        self.emit({
            "type": "call_started",
            "call_id": call_id,
            "caller_number": caller_number,
            "workflow_name": workflow_name,
            "timestamp": meta["started_at"],
        })
        logger.info("Call registered: %s (active=%d)", call_id, len(self._active_calls))

    def unregister_call(self, call_id: str, duration: float | None = None) -> None:
        """Remove a call from active set and broadcast ``call_ended``."""
        self._active_calls.pop(call_id, None)
        self.emit({
            "type": "call_ended",
            "call_id": call_id,
            "duration": duration,
            "timestamp": time.time(),
        })
        logger.info("Call unregistered: %s (active=%d)", call_id, len(self._active_calls))

    def get_active_calls(self) -> list[dict[str, Any]]:
        """Return a snapshot of all currently active calls."""
        return list(self._active_calls.values())

    def get_call_sid(self, call_id: str) -> str | None:
        """Return the Twilio call_sid for an active call, or None."""
        meta = self._active_calls.get(call_id)
        return meta["call_sid"] if meta else None

    def is_active(self, call_id: str) -> bool:
        return call_id in self._active_calls

    # ------------------------------------------------------------------
    # Pub / Sub
    # ------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Create a new subscriber queue. Returns the queue to ``await .get()`` on."""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._listeners.append(q)
        logger.debug("New subscriber (total=%d)", len(self._listeners))
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscriber queue."""
        try:
            self._listeners.remove(q)
        except ValueError:
            pass
        logger.debug("Subscriber removed (total=%d)", len(self._listeners))

    def emit(self, event: dict[str, Any]) -> None:
        """Broadcast an event to all subscribers. Non-blocking — drops if full."""
        for q in self._listeners:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Dropping event for slow subscriber: %s", event.get("type"))


# Module-level singleton used across the application
event_bus = EventBus()

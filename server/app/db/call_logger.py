"""Call event logger — writes events to the database during a call.

Usage in the pipeline::

    logger = CallLogger(call_id=call.id)
    logger.log_transcript("Hello, I need help")
    logger.log_llm_response("Sure, how can I help?")
    logger.log_node_transition("greeting", "intent_router", "e_greeting_to_router")
    logger.log_summary("greeting", {"summary": "Caller greeted", "key_info": {}})
    logger.log_action("end_call", {"message": "Goodbye!"})
    await logger.flush()       # write all pending events to DB
    await logger.finalise()    # set call ended_at + duration
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlmodel import Session

from app.db.models import Call, CallEvent, EventType

logger = logging.getLogger(__name__)


class CallLogger:
    """Buffers call events and writes them to the database in batches."""

    def __init__(self, call_id: UUID) -> None:
        self._call_id = call_id
        self._pending: list[CallEvent] = []

    def _add(self, event_type: EventType, data: dict[str, Any]) -> None:
        self._pending.append(
            CallEvent(
                call_id=self._call_id,
                event_type=event_type,
                data_json=data,
            )
        )

    def log_transcript(self, transcript: str) -> None:
        self._add(EventType.transcript, {"transcript": transcript})

    def log_llm_response(self, response: str) -> None:
        self._add(EventType.llm_response, {"response": response})

    def log_node_transition(
        self, from_node: str, to_node: str, edge_id: str
    ) -> None:
        self._add(
            EventType.node_transition,
            {"from_node": from_node, "to_node": to_node, "edge_id": edge_id},
        )

    def log_summary(self, node_id: str, summary: dict[str, Any]) -> None:
        self._add(
            EventType.summary_generated,
            {"node_id": node_id, "summary": summary},
        )

    def log_action(self, action_type: str, data: dict[str, Any]) -> None:
        self._add(EventType.action_executed, {"action_type": action_type, **data})

    def log_error(self, error: str, context: dict[str, Any] | None = None) -> None:
        self._add(EventType.error, {"error": error, **(context or {})})

    def flush(self) -> None:
        """Write all pending events to the database."""
        if not self._pending:
            return
        try:
            from app.db.session import _engine
            with Session(_engine) as session:
                for event in self._pending:
                    session.add(event)
                session.commit()
            logger.debug("Flushed %d call events for call %s", len(self._pending), self._call_id)
            self._pending.clear()
        except Exception:
            logger.exception("Failed to flush call events")

    def finalise(self, started_at: datetime | None = None) -> None:
        """Mark the call as ended and compute duration."""
        try:
            from app.db.session import _engine
            with Session(_engine) as session:
                call = session.get(Call, self._call_id)
                if call is not None:
                    now = datetime.now(timezone.utc)
                    call.ended_at = now
                    # Compute duration — handle both tz-aware and tz-naive started_at
                    ref = started_at or call.started_at
                    if ref is not None:
                        if ref.tzinfo is None:
                            ref = ref.replace(tzinfo=timezone.utc)
                        call.duration_seconds = (now - ref).total_seconds()
                    session.add(call)
                    session.commit()
                    logger.info(
                        "Call %s finalised: duration=%.1fs",
                        self._call_id,
                        call.duration_seconds or 0,
                    )
        except Exception:
            logger.exception("Failed to finalise call %s", self._call_id)

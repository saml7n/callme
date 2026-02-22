"""Call log API endpoints.

Provides read-only access to call records and their events.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db.models import Call, CallEvent, Workflow
from app.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calls", tags=["calls"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class CallListItem(BaseModel):
    """Summary for list endpoint."""

    id: UUID
    call_sid: str
    from_number: str
    to_number: str
    workflow_id: UUID | None
    workflow_name: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: float | None
    status: str  # completed | transferred | error | in_progress


class CallEventItem(BaseModel):
    """A single call event."""

    id: UUID
    timestamp: datetime
    event_type: str
    data_json: dict[str, Any]


class CallDetail(BaseModel):
    """Full call detail with events."""

    id: UUID
    call_sid: str
    from_number: str
    to_number: str
    workflow_id: UUID | None
    workflow_name: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: float | None
    status: str
    events: list[CallEventItem]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_status(call: Call, events: list[CallEvent] | None = None) -> str:
    """Derive a human-readable status from a call record."""
    if call.ended_at is None:
        return "in_progress"
    if events:
        for e in events:
            if e.event_type == "error":
                return "error"
            if e.event_type == "action_executed":
                data = e.data_json or {}
                if data.get("action_type") == "transfer":
                    return "transferred"
    return "completed"


def _workflow_name(session: Session, workflow_id: UUID | None) -> str | None:
    """Look up workflow name by ID."""
    if workflow_id is None:
        return None
    wf = session.get(Workflow, workflow_id)
    return wf.name if wf else None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[CallListItem])
async def list_calls(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """List recent calls, most recent first."""
    calls = list(
        session.exec(
            select(Call)
            .order_by(Call.started_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    results = []
    for call in calls:
        # Fetch events only to determine status (lightweight: just event types)
        events = list(session.exec(
            select(CallEvent)
            .where(CallEvent.call_id == call.id)
            .order_by(CallEvent.timestamp)
        ).all())
        results.append({
            "id": call.id,
            "call_sid": call.call_sid,
            "from_number": call.from_number,
            "to_number": call.to_number,
            "workflow_id": call.workflow_id,
            "workflow_name": _workflow_name(session, call.workflow_id),
            "started_at": call.started_at,
            "ended_at": call.ended_at,
            "duration_seconds": call.duration_seconds,
            "status": _call_status(call, events),
        })
    return results


@router.get("/{call_id}", response_model=CallDetail)
async def get_call(
    call_id: UUID,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Get a single call with all its events."""
    call = session.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")

    events = list(session.exec(
        select(CallEvent)
        .where(CallEvent.call_id == call_id)
        .order_by(CallEvent.timestamp)
    ).all())

    return {
        "id": call.id,
        "call_sid": call.call_sid,
        "from_number": call.from_number,
        "to_number": call.to_number,
        "workflow_id": call.workflow_id,
        "workflow_name": _workflow_name(session, call.workflow_id),
        "started_at": call.started_at,
        "ended_at": call.ended_at,
        "duration_seconds": call.duration_seconds,
        "status": _call_status(call, events),
        "events": [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "event_type": e.event_type,
                "data_json": e.data_json,
            }
            for e in events
        ],
    }

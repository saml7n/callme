"""Call log API endpoints.

Provides read-only access to call records and their events.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db.models import Call, CallEvent
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
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: float | None


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
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: float | None
    events: list[CallEventItem]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[CallListItem])
async def list_calls(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> list[Call]:
    """List recent calls, most recent first."""
    return list(
        session.exec(
            select(Call).order_by(Call.started_at.desc()).limit(limit)
        ).all()
    )


@router.get("/{call_id}", response_model=CallDetail)
async def get_call(
    call_id: UUID,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Get a single call with all its events."""
    call = session.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")

    events = session.exec(
        select(CallEvent)
        .where(CallEvent.call_id == call_id)
        .order_by(CallEvent.timestamp)
    ).all()

    return {
        "id": call.id,
        "call_sid": call.call_sid,
        "from_number": call.from_number,
        "to_number": call.to_number,
        "workflow_id": call.workflow_id,
        "started_at": call.started_at,
        "ended_at": call.ended_at,
        "duration_seconds": call.duration_seconds,
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

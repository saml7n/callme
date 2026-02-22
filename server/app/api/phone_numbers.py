"""Phone number management API endpoints (Story 14).

Provides CRUD for registered phone numbers that can be assigned to workflows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.auth import require_auth
from app.db.models import PhoneNumber, Workflow
from app.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/phone-numbers",
    tags=["phone-numbers"],
    dependencies=[Depends(require_auth)],
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class PhoneNumberCreate(BaseModel):
    """Body for POST /api/phone-numbers."""

    number: str = Field(min_length=1, max_length=30, description="E.164 phone number")
    label: str = Field(default="", max_length=200, description="Friendly name")


class PhoneNumberResponse(BaseModel):
    """Returned for each phone number."""

    id: UUID
    number: str
    label: str
    workflow_id: UUID | None
    workflow_name: str | None = None
    updated_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enrich_with_workflow_name(
    phone: PhoneNumber,
    session: Session,
) -> PhoneNumberResponse:
    """Build a response with the assigned workflow's name (if any)."""
    wf_name: str | None = None
    if phone.workflow_id is not None:
        wf = session.get(Workflow, phone.workflow_id)
        if wf is not None:
            wf_name = wf.name
    return PhoneNumberResponse(
        id=phone.id,
        number=phone.number,
        label=phone.label,
        workflow_id=phone.workflow_id,
        workflow_name=wf_name,
        updated_at=phone.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[PhoneNumberResponse])
async def list_phone_numbers(
    session: Session = Depends(get_session),
) -> list[PhoneNumberResponse]:
    """List all registered phone numbers with their workflow assignment."""
    phones = session.exec(
        select(PhoneNumber).order_by(PhoneNumber.updated_at.desc())
    ).all()
    return [_enrich_with_workflow_name(p, session) for p in phones]


@router.post("", response_model=PhoneNumberResponse, status_code=201)
async def create_phone_number(
    body: PhoneNumberCreate,
    session: Session = Depends(get_session),
) -> PhoneNumberResponse:
    """Register a new phone number."""
    # Check for duplicate
    existing = session.exec(
        select(PhoneNumber).where(PhoneNumber.number == body.number)
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Phone number already registered")

    phone = PhoneNumber(number=body.number, label=body.label)
    session.add(phone)
    session.commit()
    session.refresh(phone)
    logger.info("Registered phone number %s (%s)", phone.number, phone.id)
    return _enrich_with_workflow_name(phone, session)


@router.delete("/{phone_id}", status_code=204)
async def delete_phone_number(
    phone_id: UUID,
    session: Session = Depends(get_session),
) -> None:
    """Remove a phone number. Blocked if assigned to an active workflow."""
    phone = session.get(PhoneNumber, phone_id)
    if phone is None:
        raise HTTPException(status_code=404, detail="Phone number not found")

    if phone.workflow_id is not None:
        # Check if the assigned workflow is still active
        wf = session.get(Workflow, phone.workflow_id)
        if wf is not None and wf.is_active:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete: number is assigned to active workflow "
                f"'{wf.name}'",
            )

    session.delete(phone)
    session.commit()
    logger.info("Deleted phone number %s (%s)", phone.number, phone_id)

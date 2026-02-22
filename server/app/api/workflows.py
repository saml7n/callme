"""Workflow CRUD API endpoints.

Provides create, read, update, delete, list, and publish for workflows.
Validates ``graph_json`` against the workflow schema on create/update.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.auth import require_auth
from app.db.models import PhoneNumber, Workflow
from app.db.session import get_session
from app.workflow.schema import Workflow as WorkflowSchema

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"], dependencies=[Depends(require_auth)])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class WorkflowCreate(BaseModel):
    """Body for POST /api/workflows."""

    name: str = Field(min_length=1, max_length=200)
    graph_json: dict[str, Any]


class WorkflowUpdate(BaseModel):
    """Body for PUT /api/workflows/{id}."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    graph_json: dict[str, Any] | None = None


class WorkflowPublish(BaseModel):
    """Body for POST /api/workflows/{id}/publish."""

    phone_number_id: UUID
    version: int | None = None  # optimistic concurrency — reject if stale


class WorkflowListItem(BaseModel):
    """Summary returned in list endpoint."""

    id: UUID
    name: str
    version: int
    is_active: bool
    phone_number: str | None
    updated_at: datetime


class WorkflowDetail(BaseModel):
    """Full workflow detail."""

    id: UUID
    name: str
    version: int
    graph_json: dict[str, Any]
    is_active: bool
    phone_number: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------

def _validate_graph(graph_json: dict[str, Any]) -> None:
    """Validate graph_json against the workflow Pydantic schema.

    Raises HTTPException 422 on invalid data.
    """
    try:
        WorkflowSchema.model_validate(graph_json)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid graph_json: {exc}") from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[WorkflowListItem])
async def list_workflows(session: Session = Depends(get_session)) -> list[Workflow]:
    """List all workflows (summary view)."""
    return list(session.exec(select(Workflow).order_by(Workflow.updated_at.desc())).all())


@router.get("/active", response_model=WorkflowDetail)
async def get_active_workflow(
    phone_number: str | None = None,
    session: Session = Depends(get_session),
) -> Workflow:
    """Return the currently active workflow, optionally filtered by phone number.

    If no phone_number is given, returns the first active workflow.
    """
    stmt = select(Workflow).where(Workflow.is_active == True)  # noqa: E712
    if phone_number:
        stmt = stmt.where(Workflow.phone_number == phone_number)
    workflow = session.exec(stmt).first()
    if workflow is None:
        raise HTTPException(status_code=404, detail="No active workflow")
    return workflow


@router.get("/{workflow_id}", response_model=WorkflowDetail)
async def get_workflow(
    workflow_id: UUID,
    session: Session = Depends(get_session),
) -> Workflow:
    """Get a single workflow by ID."""
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.post("", response_model=WorkflowDetail, status_code=201)
async def create_workflow(
    body: WorkflowCreate,
    session: Session = Depends(get_session),
) -> Workflow:
    """Create a new workflow."""
    _validate_graph(body.graph_json)

    workflow = Workflow(
        name=body.name,
        graph_json=body.graph_json,
    )
    session.add(workflow)
    session.commit()
    session.refresh(workflow)
    logger.info("Created workflow %s: %s", workflow.id, workflow.name)
    return workflow


@router.put("/{workflow_id}", response_model=WorkflowDetail)
async def update_workflow(
    workflow_id: UUID,
    body: WorkflowUpdate,
    session: Session = Depends(get_session),
) -> Workflow:
    """Update an existing workflow."""
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if body.name is not None:
        workflow.name = body.name
    if body.graph_json is not None:
        _validate_graph(body.graph_json)
        workflow.graph_json = body.graph_json
        workflow.version += 1

    workflow.updated_at = datetime.now(timezone.utc)
    session.add(workflow)
    session.commit()
    session.refresh(workflow)
    logger.info("Updated workflow %s (v%d)", workflow.id, workflow.version)
    return workflow


@router.post("/{workflow_id}/publish", response_model=WorkflowDetail)
async def publish_workflow(
    workflow_id: UUID,
    body: WorkflowPublish,
    session: Session = Depends(get_session),
) -> Workflow:
    """Publish a workflow — sets is_active=True and assigns a phone number.

    Accepts ``phone_number_id`` referencing the ``phone_numbers`` table.
    Supports optimistic concurrency: if ``version`` is provided and doesn't
    match the current DB version, returns 409.
    Deactivates any other workflow currently active on the same phone number.
    """
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Optimistic concurrency check
    if body.version is not None and body.version != workflow.version:
        raise HTTPException(
            status_code=409,
            detail=f"Version conflict: expected {body.version}, current is {workflow.version}",
        )

    # Resolve phone number
    phone = session.get(PhoneNumber, body.phone_number_id)
    if phone is None:
        raise HTTPException(status_code=404, detail="Phone number not found")

    # Check if the number is assigned to a different active workflow
    if phone.workflow_id is not None and phone.workflow_id != workflow_id:
        other_wf = session.get(Workflow, phone.workflow_id)
        if other_wf is not None and other_wf.is_active:
            # Deactivate the other workflow
            other_wf.is_active = False
            other_wf.phone_number = None
            other_wf.updated_at = datetime.now(timezone.utc)
            session.add(other_wf)

    # Unassign this phone number from any previous workflow's phone_number field
    prev_on_number = session.exec(
        select(Workflow).where(
            Workflow.phone_number == phone.number,
            Workflow.id != workflow_id,
        )
    ).all()
    for w in prev_on_number:
        w.is_active = False
        w.phone_number = None
        w.updated_at = datetime.now(timezone.utc)
        session.add(w)

    # Assign phone number to this workflow
    phone.workflow_id = workflow_id
    phone.updated_at = datetime.now(timezone.utc)
    session.add(phone)

    workflow.is_active = True
    workflow.phone_number = phone.number
    workflow.updated_at = datetime.now(timezone.utc)
    session.add(workflow)
    session.commit()
    session.refresh(workflow)
    logger.info("Published workflow %s to %s", workflow.id, phone.number)
    return workflow


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: UUID,
    session: Session = Depends(get_session),
) -> None:
    """Hard-delete a workflow."""
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    session.delete(workflow)
    session.commit()
    logger.info("Deleted workflow %s", workflow_id)

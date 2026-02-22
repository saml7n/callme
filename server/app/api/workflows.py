"""Workflow API routes.

Provides read-only access to the currently loaded workflow for the
debug / preview UI.  Full CRUD comes in Story 10.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

# Re-use the same path the media-stream handler loads from.
_WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "schemas"
    / "examples"
    / "reception_flow.json"
)


def _load_workflow() -> dict[str, Any] | None:
    if _WORKFLOW_PATH.exists():
        return json.loads(_WORKFLOW_PATH.read_text())
    return None


@router.get("/active")
async def get_active_workflow() -> dict[str, Any]:
    """Return the currently loaded workflow JSON."""
    workflow = _load_workflow()
    if workflow is None:
        raise HTTPException(status_code=404, detail="No active workflow")
    return workflow

"""Templates API — list starter workflow templates.

Templates are stored as JSON files in ``schemas/templates/``.
Selecting a template creates a new editable workflow — the template
itself is never modified (read-only starting points).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/templates",
    tags=["templates"],
    dependencies=[Depends(require_auth)],
)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "schemas" / "templates"

# Template icon mapping
TEMPLATE_ICONS: dict[str, str] = {
    "simple_receptionist": "📞",
    "appointment_booking": "📅",
    "faq_bot": "❓",
}


class TemplateOut(BaseModel):
    """A starter template."""
    id: str
    name: str
    description: str
    icon: str
    graph: dict[str, Any]


def _load_templates() -> list[TemplateOut]:
    """Load all template JSON files from the templates directory."""
    templates: list[TemplateOut] = []
    if not TEMPLATES_DIR.exists():
        logger.warning("Templates directory not found: %s", TEMPLATES_DIR)
        return templates

    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            template_id = path.stem
            templates.append(TemplateOut(
                id=template_id,
                name=data.get("name", template_id),
                description=data.get("description", ""),
                icon=TEMPLATE_ICONS.get(template_id, "📋"),
                graph=data,
            ))
        except Exception:
            logger.warning("Failed to load template: %s", path, exc_info=True)

    return templates


@router.get("", response_model=list[TemplateOut])
async def list_templates() -> list[TemplateOut]:
    """Return all available starter templates."""
    return _load_templates()

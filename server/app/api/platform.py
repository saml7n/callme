"""Platform status API — reports which services have platform-level keys configured.

This allows the web UI to show the "Use platform keys" option in the setup wizard
only when the host has actually configured platform-level API keys in .env.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/api/platform", tags=["platform"])


@router.get("/status")
async def platform_status() -> dict:
    """Return which services have platform-level keys configured.

    No auth required — this only reveals *whether* keys exist, not their values.
    """
    return {
        "twilio": bool(settings.twilio_account_sid),
        "deepgram": bool(settings.deepgram_api_key),
        "elevenlabs": bool(settings.elevenlabs_api_key),
        "openai": bool(settings.openai_api_key),
        "has_any": bool(
            settings.twilio_account_sid
            or settings.deepgram_api_key
            or settings.elevenlabs_api_key
            or settings.openai_api_key
        ),
    }

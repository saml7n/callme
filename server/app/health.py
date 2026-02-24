"""Health checks — probe external service connectivity.

Each checker attempts a lightweight API call and returns ``{"status": "ok"}``
or ``{"status": "error", "detail": "…"}``.  All checks run with a short
timeout so the health endpoint stays fast.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 4.0  # seconds per service check


async def _check_twilio() -> dict[str, str]:
    """Ping Twilio API with account credentials."""
    try:
        from app.config import settings
        sid = settings.twilio_account_sid
        if not sid:
            return {"status": "not_configured"}
        # Use API key if available, else auth token
        if settings.twilio_api_key_sid and settings.twilio_api_key_secret:
            auth = (settings.twilio_api_key_sid, settings.twilio_api_key_secret)
        elif settings.twilio_auth_token:
            auth = (sid, settings.twilio_auth_token)
        else:
            return {"status": "not_configured"}
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, auth=auth)
        if resp.status_code < 300:
            return {"status": "ok"}
        return {"status": "error", "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)[:120]}


async def _check_deepgram() -> dict[str, str]:
    """Ping Deepgram projects endpoint."""
    try:
        from app.config import settings
        key = settings.deepgram_api_key
        if not key:
            return {"status": "not_configured"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://api.deepgram.com/v1/projects",
                headers={"Authorization": f"Token {key}"},
            )
        if resp.status_code < 300:
            return {"status": "ok"}
        return {"status": "error", "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)[:120]}


async def _check_elevenlabs() -> dict[str, str]:
    """Ping ElevenLabs user info endpoint."""
    try:
        from app.config import settings
        key = settings.elevenlabs_api_key
        if not key:
            return {"status": "not_configured"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://api.elevenlabs.io/v1/user",
                headers={"xi-api-key": key},
            )
        if resp.status_code < 300:
            return {"status": "ok"}
        return {"status": "error", "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)[:120]}


async def _check_openai() -> dict[str, str]:
    """Ping OpenAI models endpoint."""
    try:
        from app.config import settings
        key = settings.openai_api_key
        if not key:
            return {"status": "not_configured"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
        if resp.status_code < 300:
            return {"status": "ok"}
        return {"status": "error", "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)[:120]}


async def check_all_services() -> dict[str, dict[str, str]]:
    """Run all health checks concurrently and return results."""
    import asyncio
    twilio, deepgram, elevenlabs, openai = await asyncio.gather(
        _check_twilio(),
        _check_deepgram(),
        _check_elevenlabs(),
        _check_openai(),
    )
    return {
        "twilio": twilio,
        "deepgram": deepgram,
        "elevenlabs": elevenlabs,
        "openai": openai,
    }

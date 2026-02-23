"""Settings API — manage API keys and service configuration.

Endpoints
---------
GET  /api/settings          — return all settings with redacted values
PUT  /api/settings          — bulk upsert settings
POST /api/settings/validate — test each configured service
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import get_current_user, require_auth
from app.crypto import decrypt, encrypt
from app.db.models import Setting, User
from app.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(require_auth)],
)

# Allowed setting keys
ALLOWED_KEYS = {
    "twilio_account_sid",
    "twilio_api_key_sid",
    "twilio_api_key_secret",
    "twilio_auth_token",
    "twilio_phone_number",
    "deepgram_api_key",
    "elevenlabs_api_key",
    "openai_api_key",
    "admin_phone_number",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _redact(value: str) -> str:
    """Redact a secret value, showing only the last 4 chars."""
    if len(value) <= 4:
        return "••••"
    return "••••" + value[-4:]


def get_setting(session: Session, key: str, user_id: UUID | None = None) -> str | None:
    """Get a decrypted setting value, or None if not set.

    When ``user_id`` is provided, only that user's settings are searched.
    When ``None``, returns the first matching row (legacy / admin fallback).
    """
    if user_id is not None:
        row = session.exec(
            select(Setting).where(Setting.key == key, Setting.user_id == user_id)
        ).first()
    else:
        row = session.exec(select(Setting).where(Setting.key == key)).first()
    if row is None or not row.value_encrypted:
        return None
    try:
        return decrypt(row.value_encrypted)
    except Exception:
        logger.warning("Failed to decrypt setting %s", key)
        return None


def get_all_settings(session: Session, user_id: UUID | None = None) -> dict[str, str]:
    """Return all decrypted settings as a dict.

    When ``user_id`` is provided, only that user's settings are returned.
    """
    stmt = select(Setting)
    if user_id is not None:
        stmt = stmt.where(Setting.user_id == user_id)
    rows = session.exec(stmt).all()
    result: dict[str, str] = {}
    for row in rows:
        try:
            val = decrypt(row.value_encrypted) if row.value_encrypted else ""
            if val:
                result[row.key] = val
        except Exception:
            logger.warning("Failed to decrypt setting %s", row.key)
    return result


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class SettingsOut(BaseModel):
    """GET response — keys with redacted values."""
    settings: dict[str, str]
    configured: bool


class SettingsPut(BaseModel):
    """PUT body — arbitrary key-value pairs (only ALLOWED_KEYS accepted)."""
    settings: dict[str, str]


class ValidateResult(BaseModel):
    """POST /validate response."""
    results: dict[str, str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=SettingsOut)
async def get_settings(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SettingsOut:
    """Return all settings with redacted values for the current user."""
    all_settings = get_all_settings(session, user_id=user.id)
    redacted: dict[str, str] = {}
    for key in ALLOWED_KEYS:
        val = all_settings.get(key, "")
        if val:
            redacted[key] = _redact(val)
        else:
            redacted[key] = ""
    # "configured" is True if at least the 4 core API keys are set
    core_keys = {"twilio_account_sid", "deepgram_api_key", "elevenlabs_api_key", "openai_api_key"}
    configured = all(all_settings.get(k) for k in core_keys)
    return SettingsOut(settings=redacted, configured=configured)


@router.put("", response_model=SettingsOut)
async def put_settings(
    body: SettingsPut,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SettingsOut:
    """Bulk upsert settings for the current user. Only ALLOWED_KEYS are accepted."""
    now = datetime.now(timezone.utc)
    for key, value in body.settings.items():
        if key not in ALLOWED_KEYS:
            continue
        existing = session.exec(
            select(Setting).where(Setting.key == key, Setting.user_id == user.id)
        ).first()
        if existing is not None:
            existing.value_encrypted = encrypt(value) if value else ""
            existing.updated_at = now
            session.add(existing)
        else:
            row = Setting(
                key=key,
                user_id=user.id,
                value_encrypted=encrypt(value) if value else "",
                updated_at=now,
            )
            session.add(row)
    session.commit()
    logger.info("Settings updated for user %s: %s", user.id, list(body.settings.keys()))

    # Return redacted view
    return await get_settings(session, user)


@router.post("/validate", response_model=ValidateResult)
async def validate_settings(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ValidateResult:
    """Test each configured service and return per-service status."""
    all_settings = get_all_settings(session, user_id=user.id)
    results: dict[str, str] = {}

    # Twilio — supports API Key (SID+Secret) or Auth Token for REST auth
    twilio_sid = all_settings.get("twilio_account_sid", "")
    twilio_key_sid = all_settings.get("twilio_api_key_sid", "")
    twilio_key_secret = all_settings.get("twilio_api_key_secret", "")
    twilio_auth_token = all_settings.get("twilio_auth_token", "")

    # Prefer API Key, fall back to Auth Token
    if twilio_sid and twilio_key_sid and twilio_key_secret:
        auth_pair = (twilio_key_sid, twilio_key_secret)
    elif twilio_sid and twilio_auth_token:
        auth_pair = (twilio_sid, twilio_auth_token)
    else:
        auth_pair = None

    if twilio_sid and auth_pair:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Calls.json?PageSize=1",
                    auth=auth_pair,
                    timeout=10.0,
                )
                results["twilio"] = "ok" if resp.status_code == 200 else f"error ({resp.status_code})"
        except Exception as exc:
            results["twilio"] = f"error ({exc})"
    else:
        results["twilio"] = "not_configured"

    # Deepgram
    dg_key = all_settings.get("deepgram_api_key", "")
    if dg_key:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.deepgram.com/v1/projects",
                    headers={"Authorization": f"Token {dg_key}"},
                    timeout=10.0,
                )
                results["deepgram"] = "ok" if resp.status_code == 200 else f"error ({resp.status_code})"
        except Exception as exc:
            results["deepgram"] = f"error ({exc})"
    else:
        results["deepgram"] = "not_configured"

    # ElevenLabs — use a tiny TTS request instead of GET /v1/voices
    # because scoped API keys may lack voices_read permission.
    el_key = all_settings.get("elevenlabs_api_key", "")
    if el_key:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM",
                    headers={"xi-api-key": el_key, "Content-Type": "application/json"},
                    json={"text": "ok", "model_id": "eleven_flash_v2_5"},
                    timeout=15.0,
                )
                results["elevenlabs"] = "ok" if resp.status_code == 200 else f"error ({resp.status_code})"
        except Exception as exc:
            results["elevenlabs"] = f"error ({exc})"
    else:
        results["elevenlabs"] = "not_configured"

    # OpenAI
    oai_key = all_settings.get("openai_api_key", "")
    if oai_key:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {oai_key}"},
                    timeout=10.0,
                )
                results["openai"] = "ok" if resp.status_code == 200 else f"error ({resp.status_code})"
        except Exception as exc:
            results["openai"] = f"error ({exc})"
    else:
        results["openai"] = "not_configured"

    return ValidateResult(results=results)

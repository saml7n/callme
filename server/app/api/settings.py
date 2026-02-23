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

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import require_auth
from app.crypto import decrypt, encrypt
from app.db.models import Setting
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


def get_setting(session: Session, key: str) -> str | None:
    """Get a decrypted setting value, or None if not set."""
    row = session.get(Setting, key)
    if row is None or not row.value_encrypted:
        return None
    try:
        return decrypt(row.value_encrypted)
    except Exception:
        logger.warning("Failed to decrypt setting %s", key)
        return None


def get_all_settings(session: Session) -> dict[str, str]:
    """Return all decrypted settings as a dict."""
    result: dict[str, str] = {}
    rows = session.exec(select(Setting)).all()
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
async def get_settings(session: Session = Depends(get_session)) -> SettingsOut:
    """Return all settings with redacted values."""
    all_settings = get_all_settings(session)
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
) -> SettingsOut:
    """Bulk upsert settings. Only ALLOWED_KEYS are accepted."""
    now = datetime.now(timezone.utc)
    for key, value in body.settings.items():
        if key not in ALLOWED_KEYS:
            continue
        existing = session.get(Setting, key)
        if existing is not None:
            existing.value_encrypted = encrypt(value) if value else ""
            existing.updated_at = now
            session.add(existing)
        else:
            row = Setting(
                key=key,
                value_encrypted=encrypt(value) if value else "",
                updated_at=now,
            )
            session.add(row)
    session.commit()
    logger.info("Settings updated: %s", list(body.settings.keys()))

    # Return redacted view
    return await get_settings(session)


@router.post("/validate", response_model=ValidateResult)
async def validate_settings(
    session: Session = Depends(get_session),
) -> ValidateResult:
    """Test each configured service and return per-service status."""
    all_settings = get_all_settings(session)
    results: dict[str, str] = {}

    # Twilio
    twilio_sid = all_settings.get("twilio_account_sid", "")
    twilio_token = all_settings.get("twilio_auth_token", "")
    if twilio_sid and twilio_token:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}.json",
                    auth=(twilio_sid, twilio_token),
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

    # ElevenLabs
    el_key = all_settings.get("elevenlabs_api_key", "")
    if el_key:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.elevenlabs.io/v1/voices",
                    headers={"xi-api-key": el_key},
                    timeout=10.0,
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

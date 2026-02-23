"""Auth API endpoints — login and key validation."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_api_key, require_auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    key: str


class LoginResponse(BaseModel):
    ok: bool
    token: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    """Validate an API key and return it as a token.

    This endpoint is intentionally unauthenticated — it IS the auth gate.
    """
    api_key = get_api_key()
    if not secrets.compare_digest(body.key, api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return LoginResponse(ok=True, token=api_key)


@router.get("/check")
async def check() -> dict:
    """Return whether auth is enabled (i.e. an API key is configured)."""
    key = get_api_key()
    return {"auth_enabled": bool(key)}


@router.get("/config-warnings", dependencies=[Depends(require_auth)])
async def config_warnings() -> dict:
    """Return warnings about missing configuration.

    Protected by auth (callers must be logged in).
    """
    from app.config import settings
    from app.credentials import get_admin_phone_number

    warnings: list[str] = []
    if not settings.callme_fallback_number and not get_admin_phone_number():
        warnings.append(
            "No fallback phone number configured. Enter your mobile number in "
            "Setup → Phone Number, or set CALLME_FALLBACK_NUMBER in your .env."
        )
    if not settings.twilio_auth_token and not (settings.twilio_api_key_sid and settings.twilio_api_key_secret):
        warnings.append(
            "No Twilio auth credentials configured. Set TWILIO_API_KEY_SID + "
            "TWILIO_API_KEY_SECRET (or TWILIO_AUTH_TOKEN) to enable API calls "
            "and webhook signature validation."
        )
    return {"warnings": warnings}

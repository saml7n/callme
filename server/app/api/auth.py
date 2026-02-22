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

    warnings: list[str] = []
    if not settings.callme_fallback_number:
        warnings.append(
            "No fallback phone number configured. Set CALLME_FALLBACK_NUMBER "
            "so calls can be transferred to a human when errors occur."
        )
    if not settings.twilio_auth_token:
        warnings.append(
            "No Twilio auth token configured. Set TWILIO_AUTH_TOKEN to enable "
            "webhook signature validation."
        )
    return {"warnings": warnings}

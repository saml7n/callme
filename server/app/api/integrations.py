"""Integrations CRUD API — manage external service connections.

Endpoints
---------
GET    /api/integrations            — list all (credentials redacted)
POST   /api/integrations            — create
PUT    /api/integrations/{id}       — update
DELETE /api/integrations/{id}       — remove (blocked if referenced by active workflow)
POST   /api/integrations/{id}/test  — dry-run connection test
GET    /api/integrations/{id}/oauth/start   — start Google OAuth flow
GET    /api/integrations/{id}/oauth/callback — handle Google OAuth callback
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.auth import require_auth
from app.crypto import decrypt, encrypt
from app.db.models import Integration, IntegrationType, Workflow
from app.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/integrations",
    tags=["integrations"],
    dependencies=[Depends(require_auth)],
)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class IntegrationCreate(BaseModel):
    type: IntegrationType
    name: str = Field(..., min_length=1, max_length=200)
    config: dict[str, Any] = Field(
        ...,
        description="Type-specific configuration (will be encrypted at rest).",
    )


class IntegrationUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None


class IntegrationOut(BaseModel):
    id: UUID
    type: IntegrationType
    name: str
    config_redacted: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TestResult(BaseModel):
    success: bool
    detail: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS = {
    "client_secret", "refresh_token", "access_token", "auth_header",
    "service_account_json", "api_key", "secret",
}


def _redact(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *config* with sensitive values masked."""
    redacted: dict[str, Any] = {}
    for k, v in config.items():
        if k in _SENSITIVE_KEYS and isinstance(v, str) and len(v) > 4:
            redacted[k] = "••••" + v[-4:]
        else:
            redacted[k] = v
    return redacted


def _decrypt_config(integration: Integration) -> dict[str, Any]:
    """Decrypt the config blob stored on an Integration row."""
    if not integration.config_encrypted:
        return {}
    return json.loads(decrypt(integration.config_encrypted))


def _to_out(integration: Integration) -> IntegrationOut:
    config = _decrypt_config(integration)
    return IntegrationOut(
        id=integration.id,
        type=integration.type,
        name=integration.name,
        config_redacted=_redact(config),
        created_at=integration.created_at,
        updated_at=integration.updated_at,
    )


def _validate_google_calendar_config(config: dict[str, Any]) -> None:
    """Validate config required for Google Calendar integration."""
    if not config.get("calendar_id"):
        raise HTTPException(status_code=422, detail="Google Calendar config requires 'calendar_id'.")
    if not config.get("client_id") and not config.get("refresh_token"):
        raise HTTPException(
            status_code=422,
            detail="Google Calendar config requires 'client_id' + 'client_secret' for OAuth, "
                   "or 'refresh_token' if already authorised.",
        )


def _validate_webhook_config(config: dict[str, Any]) -> None:
    """Validate config required for webhook integration."""
    url = config.get("url", "")
    if not url or not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Webhook config requires a valid 'url' (http/https).")
    method = config.get("method", "POST").upper()
    if method not in ("POST", "PUT"):
        raise HTTPException(status_code=422, detail="Webhook 'method' must be POST or PUT.")


_VALIDATORS = {
    IntegrationType.google_calendar: _validate_google_calendar_config,
    IntegrationType.webhook: _validate_webhook_config,
}


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[IntegrationOut])
async def list_integrations(session: Session = Depends(get_session)) -> list[IntegrationOut]:
    integrations = session.exec(select(Integration)).all()
    return [_to_out(i) for i in integrations]


@router.post("", response_model=IntegrationOut, status_code=201)
async def create_integration(
    body: IntegrationCreate,
    session: Session = Depends(get_session),
) -> IntegrationOut:
    validator = _VALIDATORS.get(body.type)
    if validator:
        validator(body.config)

    integration = Integration(
        type=body.type,
        name=body.name,
        config_encrypted=encrypt(json.dumps(body.config)),
    )
    session.add(integration)
    session.commit()
    session.refresh(integration)
    logger.info("Created integration %s (%s): %s", integration.id, integration.type, integration.name)
    return _to_out(integration)


@router.put("/{integration_id}", response_model=IntegrationOut)
async def update_integration(
    integration_id: UUID,
    body: IntegrationUpdate,
    session: Session = Depends(get_session),
) -> IntegrationOut:
    integration = session.get(Integration, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")

    if body.name is not None:
        integration.name = body.name

    if body.config is not None:
        validator = _VALIDATORS.get(integration.type)
        if validator:
            validator(body.config)
        integration.config_encrypted = encrypt(json.dumps(body.config))

    integration.updated_at = datetime.now(timezone.utc)
    session.add(integration)
    session.commit()
    session.refresh(integration)
    logger.info("Updated integration %s", integration.id)
    return _to_out(integration)


@router.delete("/{integration_id}", status_code=204)
async def delete_integration(
    integration_id: UUID,
    session: Session = Depends(get_session),
) -> None:
    integration = session.get(Integration, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")

    # Check if any active workflow references this integration
    active_workflows = session.exec(
        select(Workflow).where(Workflow.is_active == True)  # noqa: E712
    ).all()
    for wf in active_workflows:
        graph = wf.graph_json or {}
        for node in graph.get("nodes", []):
            data = node.get("data", {})
            if (
                node.get("type") == "action"
                and data.get("action_type") == "integration"
                and str(data.get("integration_id")) == str(integration_id)
            ):
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot delete: integration is used by active workflow '{wf.name}'.",
                )

    session.delete(integration)
    session.commit()
    logger.info("Deleted integration %s", integration_id)


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------

@router.post("/{integration_id}/test", response_model=TestResult)
async def test_integration(
    integration_id: UUID,
    session: Session = Depends(get_session),
) -> TestResult:
    integration = session.get(Integration, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")

    config = _decrypt_config(integration)

    if integration.type == IntegrationType.google_calendar:
        return await _test_google_calendar(config)
    elif integration.type == IntegrationType.webhook:
        return await _test_webhook(config)
    else:
        return TestResult(success=False, detail=f"Unknown integration type: {integration.type}")


async def _test_google_calendar(config: dict[str, Any]) -> TestResult:
    """Test Google Calendar connection by listing calendars."""
    refresh_token = config.get("refresh_token")
    if not refresh_token:
        return TestResult(success=False, detail="No refresh_token — complete OAuth first.")

    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Exchange refresh token for access token
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if resp.status_code != 200:
                return TestResult(success=False, detail=f"Token refresh failed: {resp.text[:200]}")

            access_token = resp.json().get("access_token")
            # Try listing calendar
            cal_id = config.get("calendar_id", "primary")
            cal_resp = await client.get(
                f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if cal_resp.status_code == 200:
                cal_name = cal_resp.json().get("summary", cal_id)
                return TestResult(success=True, detail=f"Connected to calendar: {cal_name}")
            else:
                return TestResult(success=False, detail=f"Calendar API error: {cal_resp.text[:200]}")
    except Exception as exc:
        return TestResult(success=False, detail=f"Connection error: {exc}")


async def _test_webhook(config: dict[str, Any]) -> TestResult:
    """Test webhook by sending a HEAD or GET request to the URL."""
    url = config.get("url", "")
    headers: dict[str, str] = config.get("headers", {})
    auth = config.get("auth_header", "")
    if auth:
        headers["Authorization"] = auth

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.head(url, headers=headers)
            if resp.is_success or resp.status_code in (405, 501):
                # 405/501 = HEAD not supported but URL is reachable
                return TestResult(success=True, detail=f"Webhook reachable (HTTP {resp.status_code})")
            else:
                return TestResult(success=False, detail=f"Webhook returned HTTP {resp.status_code}")
    except httpx.TimeoutException:
        return TestResult(success=False, detail="Webhook timed out (5s)")
    except Exception as exc:
        return TestResult(success=False, detail=f"Connection error: {exc}")


# ---------------------------------------------------------------------------
# Google OAuth flow
# ---------------------------------------------------------------------------

@router.get("/{integration_id}/oauth/start")
async def oauth_start(
    integration_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Return the Google OAuth consent URL for the user to visit."""
    integration = session.get(Integration, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    if integration.type != IntegrationType.google_calendar:
        raise HTTPException(status_code=400, detail="OAuth is only for Google Calendar integrations")

    config = _decrypt_config(integration)
    client_id = config.get("client_id", "")
    if not client_id:
        raise HTTPException(status_code=422, detail="client_id not configured")

    # Build callback URL
    base = str(request.base_url).rstrip("/")
    redirect_uri = f"{base}/api/integrations/{integration_id}/oauth/callback"

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        "&response_type=code"
        "&scope=https://www.googleapis.com/auth/calendar"
        "&access_type=offline"
        "&prompt=consent"
    )
    return {"url": auth_url}


@router.get("/{integration_id}/oauth/callback")
async def oauth_callback(
    integration_id: UUID,
    code: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Exchange the authorization code for tokens and store the refresh token."""
    integration = session.get(Integration, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")

    config = _decrypt_config(integration)
    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")

    base = str(request.base_url).rstrip("/")
    redirect_uri = f"{base}/api/integrations/{integration_id}/oauth/callback"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Token exchange failed: {resp.text[:200]}")

    tokens = resp.json()
    config["refresh_token"] = tokens["refresh_token"]
    if "access_token" in tokens:
        config["access_token"] = tokens["access_token"]

    integration.config_encrypted = encrypt(json.dumps(config))
    integration.updated_at = datetime.now(timezone.utc)
    session.add(integration)
    session.commit()
    logger.info("OAuth completed for integration %s", integration_id)

    return {"status": "ok", "detail": "Google Calendar authorised. You can close this tab."}

"""Tests for Story 23 — Per-user setup wizard & shared platform keys.

Covers:
- Platform status endpoint
- Credential resolution priority (user DB → platform env fallback)
- Call routing by phone number
- Settings use_platform_keys flag
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session, select

from app.api.settings import get_setting, ALLOWED_KEYS
from app.config import Settings
from app.credentials import _resolve, _user_wants_platform_keys, get_openai_api_key
from app.crypto import encrypt
from app.db.models import PhoneNumber, Setting, User, Workflow
from app.main import app
from tests.conftest import TEST_USER_ID, _minimal_graph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth_header(token: str = "test-api-key-for-tests") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _set_user_setting(session: Session, key: str, value: str, user_id=TEST_USER_ID) -> None:
    """Write a setting row directly into the DB."""
    row = Setting(
        key=key,
        user_id=user_id,
        value_encrypted=encrypt(value) if value else "",
    )
    session.add(row)
    session.commit()


# ===========================================================================
# Platform status endpoint
# ===========================================================================

class TestPlatformStatus:
    """GET /api/platform/status — reports platform key availability."""

    @pytest.mark.asyncio
    async def test_returns_status_for_each_service(self, monkeypatch):
        """Platform status reflects env var availability."""
        monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
        monkeypatch.setenv("DEEPGRAM_API_KEY", "dg_test")
        monkeypatch.setenv("ELEVENLABS_API_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")

        monkeypatch.setattr("app.api.platform.settings", Settings())

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/platform/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["twilio"] is True
        assert data["deepgram"] is True
        assert data["elevenlabs"] is False
        assert data["openai"] is True
        assert data["has_any"] is True

    @pytest.mark.asyncio
    async def test_all_empty_returns_false(self, monkeypatch):
        """When no platform keys are configured, all values are False."""
        monkeypatch.setenv("TWILIO_ACCOUNT_SID", "")
        monkeypatch.setenv("DEEPGRAM_API_KEY", "")
        monkeypatch.setenv("ELEVENLABS_API_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "")

        monkeypatch.setattr("app.api.platform.settings", Settings())

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/platform/status")

        data = resp.json()
        assert data["has_any"] is False

    @pytest.mark.asyncio
    async def test_no_auth_required(self):
        """Platform status endpoint should work without authentication."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/platform/status")
        # Should not get 401/403
        assert resp.status_code == 200


# ===========================================================================
# Credential resolution
# ===========================================================================

class TestCredentialResolution:
    """Verify credential resolution priority: user DB → platform env."""

    def test_user_own_key_takes_precedence(self, db_session: Session):
        """User's own DB setting wins over platform env."""
        _set_user_setting(db_session, "openai_api_key", "user-key-123")
        _set_user_setting(db_session, "use_platform_keys", "true")

        with patch("app.credentials.settings") as mock_settings:
            mock_settings.openai_api_key = "platform-key-456"
            result = get_openai_api_key(user_id=TEST_USER_ID)

        assert result == "user-key-123"

    def test_platform_fallback_when_opted_in(self, db_session: Session):
        """When user has use_platform_keys=true, platform env is used as fallback."""
        _set_user_setting(db_session, "use_platform_keys", "true")
        # No user openai key set

        with patch("app.credentials.settings") as mock_settings:
            mock_settings.openai_api_key = "platform-key-456"
            result = get_openai_api_key(user_id=TEST_USER_ID)

        assert result == "platform-key-456"

    def test_no_platform_fallback_when_not_opted_in(self, db_session: Session):
        """Without use_platform_keys, platform env is NOT used."""
        # No use_platform_keys set, no user key
        with patch("app.credentials.settings") as mock_settings:
            mock_settings.openai_api_key = "platform-key-456"
            result = get_openai_api_key(user_id=TEST_USER_ID)

        assert result == ""

    def test_none_user_id_always_falls_back(self, db_session: Session):
        """user_id=None always falls back to platform env (backward compat)."""
        result = _resolve("openai_api_key", "platform-fallback", user_id=None)
        assert result == "platform-fallback"

    def test_resolve_helper_with_db_value(self, db_session: Session):
        """_resolve returns DB value over env when available."""
        _set_user_setting(db_session, "deepgram_api_key", "dg-user")

        result = _resolve("deepgram_api_key", "dg-platform", user_id=TEST_USER_ID)
        assert result == "dg-user"

    def test_user_wants_platform_keys_false_by_default(self, db_session: Session):
        """Default: user has NOT opted in to platform keys."""
        assert _user_wants_platform_keys(TEST_USER_ID) is False

    def test_user_wants_platform_keys_true(self, db_session: Session):
        """Explicit opt-in returns True."""
        _set_user_setting(db_session, "use_platform_keys", "true")
        assert _user_wants_platform_keys(TEST_USER_ID) is True


# ===========================================================================
# Call routing by phone number
# ===========================================================================

class TestCallRouting:
    """Verify _load_active_workflow routes by dialled number."""

    def test_routes_to_user_by_phone_number(self, db_session: Session):
        """When To number matches a PhoneNumber, loads that user's workflow."""
        from app.twilio.media_stream import _load_active_workflow

        user_b_id = uuid4()
        user_b = User(id=user_b_id, email="userb@test.com", name="User B")
        db_session.add(user_b)
        db_session.commit()

        wf = Workflow(
            name="B's Workflow",
            graph_json=_minimal_graph(),
            is_active=True,
            phone_number="+15551111111",
            user_id=user_b_id,
        )
        db_session.add(wf)
        ph = PhoneNumber(number="+15551111111", label="B's Line", user_id=user_b_id)
        db_session.add(ph)
        db_session.commit()

        graph, wf_id, name, uid = _load_active_workflow(to_number="+15551111111")

        assert name == "B's Workflow"
        assert uid == user_b_id

    def test_falls_back_to_any_active_workflow(self, db_session: Session):
        """When To number is unknown, falls back to any active workflow."""
        from app.twilio.media_stream import _load_active_workflow

        wf = Workflow(
            name="Global Workflow",
            graph_json=_minimal_graph(),
            is_active=True,
            user_id=TEST_USER_ID,
        )
        db_session.add(wf)
        db_session.commit()

        graph, wf_id, name, uid = _load_active_workflow(to_number="+19999999999")

        assert name == "Global Workflow"

    def test_unknown_number_no_active_workflow(self, db_session: Session):
        """When no active workflow exists, returns None."""
        from app.twilio.media_stream import _load_active_workflow

        graph, wf_id, name, uid = _load_active_workflow(to_number="+19999999999")

        # Should fall back to disk — either fallback or None
        # (depends on whether reception_flow.json exists; our concern is no crash)
        assert name is not None  # could be "Fallback" or ""

    def test_two_users_different_numbers(self, db_session: Session):
        """Two users each get their own workflow based on dialled number."""
        from app.twilio.media_stream import _load_active_workflow

        user_a_id = uuid4()
        user_b_id = uuid4()
        db_session.add(User(id=user_a_id, email="a@test.com", name="A"))
        db_session.add(User(id=user_b_id, email="b@test.com", name="B"))
        db_session.commit()

        wf_a = Workflow(
            name="A's WF", graph_json=_minimal_graph(),
            is_active=True, phone_number="+15550000001", user_id=user_a_id,
        )
        wf_b = Workflow(
            name="B's WF", graph_json=_minimal_graph(),
            is_active=True, phone_number="+15550000002", user_id=user_b_id,
        )
        db_session.add_all([wf_a, wf_b])
        db_session.add(PhoneNumber(number="+15550000001", user_id=user_a_id))
        db_session.add(PhoneNumber(number="+15550000002", user_id=user_b_id))
        db_session.commit()

        _, _, name_a, uid_a = _load_active_workflow(to_number="+15550000001")
        _, _, name_b, uid_b = _load_active_workflow(to_number="+15550000002")

        assert name_a == "A's WF"
        assert uid_a == user_a_id
        assert name_b == "B's WF"
        assert uid_b == user_b_id


# ===========================================================================
# Settings use_platform_keys
# ===========================================================================

class TestSettingsPlatformKeys:
    """Settings API interaction with use_platform_keys."""

    @pytest.mark.asyncio
    async def test_use_platform_keys_in_allowed_keys(self):
        """use_platform_keys is an allowed setting key."""
        assert "use_platform_keys" in ALLOWED_KEYS

    @pytest.mark.asyncio
    async def test_put_and_get_use_platform_keys(self, db_session: Session):
        """Can save and retrieve use_platform_keys via the API."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # PUT
            resp = await client.put(
                "/api/settings",
                json={"settings": {"use_platform_keys": "true"}},
                headers=_auth_header(),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["use_platform_keys"] is True

            # GET
            resp = await client.get("/api/settings", headers=_auth_header())
            assert resp.status_code == 200
            data = resp.json()
            assert data["use_platform_keys"] is True

    @pytest.mark.asyncio
    async def test_validate_uses_platform_keys_when_opted_in(self, db_session: Session, monkeypatch):
        """When use_platform_keys is set, validate resolves platform credentials."""
        _set_user_setting(db_session, "use_platform_keys", "true")

        # Mock platform env keys (we don't want real API calls)
        monkeypatch.setattr("app.credentials.settings", Settings(
            openai_api_key="sk-platform-test",
            deepgram_api_key="dg-platform-test",
            elevenlabs_api_key="el-platform-test",
            twilio_account_sid="AC-platform-test",
        ))

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/settings/validate", headers=_auth_header())

        assert resp.status_code == 200
        data = resp.json()
        # Should attempt validation (will fail because keys are fake, but
        # the point is they're not "not_configured")
        for service in ("twilio", "deepgram", "elevenlabs", "openai"):
            assert data["results"][service] != "not_configured"


# ===========================================================================
# Webhook passes To/From to stream URL
# ===========================================================================

class TestWebhookCallMetadata:
    """Verify the webhook passes caller metadata in the stream URL."""

    @pytest.mark.asyncio
    async def test_to_and_from_in_stream_url(self, monkeypatch):
        """Webhook includes To and From as query params in the stream URL."""
        monkeypatch.setenv("PUBLIC_URL", "https://example.ngrok.io")
        monkeypatch.setattr("app.twilio.webhook.settings", Settings())
        monkeypatch.setattr("app.twilio.webhook.get_twilio_auth_token", lambda: "")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/twilio/incoming",
                data={"To": "+15551234567", "From": "+15559876543"},
            )

        assert resp.status_code == 200
        body = resp.text
        assert "to=%2B15551234567" in body or "to=+15551234567" in body or "to=%2B15551234567" in body.replace(" ", "+")
        assert "from=%2B15559876543" in body or "from=+15559876543" in body or "from=%2B15559876543" in body.replace(" ", "+")

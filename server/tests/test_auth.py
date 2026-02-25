"""Tests for the auth middleware and login/check endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import get_api_key, get_current_user, init_api_key, require_auth
from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_KEY = "test-secret-key-12345"


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """Set a known API key and JWT secret for all auth tests."""
    monkeypatch.setattr("app.auth._api_key", TEST_KEY)
    monkeypatch.setattr("app.auth.JWT_SECRET_KEY", TEST_KEY)
    monkeypatch.setattr("app.auth.settings.callme_api_key", TEST_KEY)


@pytest.fixture
def client():
    """Unauthenticated async HTTP client."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def authed_client():
    """Authenticated async HTTP client."""
    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {TEST_KEY}"},
    )


# ---------------------------------------------------------------------------
# Login endpoint
# ---------------------------------------------------------------------------


class TestLogin:
    async def test_login_valid_key(self, client, db_session):
        async with client:
            resp = await client.post("/api/auth/login", json={"key": TEST_KEY})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        # Now returns a JWT rather than the raw key
        assert body["token"] is not None
        assert body["user"]["email"] == "admin@local"

    async def test_login_invalid_key(self, client, db_session):
        async with client:
            resp = await client.post("/api/auth/login", json={"key": "wrong-key"})
        assert resp.status_code == 401

    async def test_login_empty_key(self, client, db_session):
        async with client:
            resp = await client.post("/api/auth/login", json={"key": ""})
        # Empty key falls through to email+password path → 422
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Check endpoint
# ---------------------------------------------------------------------------


class TestCheck:
    async def test_check_returns_auth_enabled(self, client):
        async with client:
            resp = await client.get("/api/auth/check")
        assert resp.status_code == 200
        body = resp.json()
        assert body["auth_enabled"] is True


# ---------------------------------------------------------------------------
# Protected endpoints — require_auth
# ---------------------------------------------------------------------------


class TestRequireAuth:
    async def test_missing_token_returns_401(self, client, db_session):
        """No Authorization header → 401."""
        # Ensure auth dependencies are NOT overridden for these tests
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        try:
            async with client:
                resp = await client.get("/api/workflows")
            assert resp.status_code == 401
        finally:
            # Restore overrides so other tests work
            async def _no_auth() -> str:
                return TEST_KEY
            from tests.conftest import TEST_USER
            async def _test_user():
                return TEST_USER
            app.dependency_overrides[require_auth] = _no_auth
            app.dependency_overrides[get_current_user] = _test_user

    async def test_invalid_token_returns_401(self, client, db_session):
        """Wrong Bearer token → 401."""
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        try:
            async with client:
                resp = await client.get(
                    "/api/workflows",
                    headers={"Authorization": "Bearer wrong-token"},
                )
            assert resp.status_code == 401
        finally:
            async def _no_auth() -> str:
                return TEST_KEY
            from tests.conftest import TEST_USER
            async def _test_user():
                return TEST_USER
            app.dependency_overrides[require_auth] = _no_auth
            app.dependency_overrides[get_current_user] = _test_user

    async def test_valid_token_returns_200(self, authed_client, db_session):
        """Correct Bearer token → 200."""
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        try:
            async with authed_client:
                resp = await authed_client.get("/api/workflows")
            assert resp.status_code == 200
        finally:
            async def _no_auth() -> str:
                return TEST_KEY
            from tests.conftest import TEST_USER
            async def _test_user():
                return TEST_USER
            app.dependency_overrides[require_auth] = _no_auth
            app.dependency_overrides[get_current_user] = _test_user


# ---------------------------------------------------------------------------
# Health endpoint remains open
# ---------------------------------------------------------------------------


class TestHealthNoAuth:
    async def test_health_no_auth_needed(self, client):
        """GET /health works without any token."""
        async with client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "public_url" in data
        assert "demo_mode" in data


# ---------------------------------------------------------------------------
# Twilio signature validation
# ---------------------------------------------------------------------------


class TestTwilioSignatureValidation:
    def test_no_auth_token_skips_validation(self, monkeypatch):
        """When twilio_auth_token is empty, validation passes."""
        from app.twilio.webhook import validate_twilio_signature

        monkeypatch.setattr("app.twilio.webhook.get_twilio_auth_token", lambda: "")
        assert validate_twilio_signature("http://example.com", {}, "") is True

    def test_invalid_signature_fails(self, monkeypatch):
        """When auth token is set and signature is wrong, validation fails."""
        from app.twilio.webhook import validate_twilio_signature

        monkeypatch.setattr(
            "app.twilio.webhook.get_twilio_auth_token", lambda: "test-auth-token"
        )
        assert (
            validate_twilio_signature("http://example.com", {}, "bad-signature")
            is False
        )

    def test_valid_signature_passes(self, monkeypatch):
        """When auth token is set and signature is correct, validation passes."""
        from twilio.request_validator import RequestValidator

        from app.twilio.webhook import validate_twilio_signature

        auth_token = "my-secret-token"
        monkeypatch.setattr(
            "app.twilio.webhook.get_twilio_auth_token", lambda: auth_token
        )

        # Generate a correct signature using the same validator
        validator = RequestValidator(auth_token)
        url = "http://example.com/twilio/incoming"
        params = {"CallSid": "CA123", "From": "+1234"}
        signature = validator.compute_signature(url, params)

        assert validate_twilio_signature(url, params, signature) is True

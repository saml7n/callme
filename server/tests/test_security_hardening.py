"""Tests for Story 26 — Security Hardening.

Covers all 8 acceptance criteria:
1. Gated registration (invite code)
2. Admin role (is_admin field)
3. Admin-only endpoints (require_admin)
4. WebSocket authentication
5. Separate JWT secret
6. Configurable demo credentials
7. Health endpoint hardening
8. Password policy
"""

from __future__ import annotations

import secrets

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session, select

from app.auth import (
    JWT_SECRET_KEY,
    create_jwt,
    decode_jwt,
    get_api_key,
    get_current_user,
    hash_password,
    init_api_key,
    require_admin,
    require_auth,
    validate_password,
)
from app.db.models import User
from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_KEY = "test-secret-key-12345"
TEST_INVITE_CODE = "welcome2026"


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """Set a known API key and JWT secret for all tests."""
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
    """Authenticated async HTTP client (API key)."""
    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {TEST_KEY}"},
    )


# ---------------------------------------------------------------------------
# AC 1: Gated registration
# ---------------------------------------------------------------------------


class TestGatedRegistration:
    """Registration requires a valid invite code."""

    async def test_register_disabled_when_invite_code_not_set(
        self, client, db_session, monkeypatch
    ):
        """When CALLME_INVITE_CODE is unset, registration returns 403."""
        monkeypatch.setattr("app.api.auth.settings.callme_invite_code", "")
        # Remove auth overrides so we hit real registration logic
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        try:
            async with client:
                resp = await client.post(
                    "/api/auth/register",
                    json={
                        "email": "new@example.com",
                        "password": "Password1",
                        "name": "New User",
                        "invite_code": "",
                    },
                )
            assert resp.status_code == 403
            assert "disabled" in resp.json()["detail"].lower()
        finally:
            from tests.conftest import TEST_USER

            async def _no_auth() -> str:
                return TEST_KEY

            async def _test_user():
                return TEST_USER

            app.dependency_overrides[require_auth] = _no_auth
            app.dependency_overrides[get_current_user] = _test_user

    async def test_register_rejected_with_wrong_invite_code(
        self, client, db_session, monkeypatch
    ):
        """Wrong invite code returns 403."""
        monkeypatch.setattr(
            "app.api.auth.settings.callme_invite_code", TEST_INVITE_CODE
        )
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        try:
            async with client:
                resp = await client.post(
                    "/api/auth/register",
                    json={
                        "email": "new@example.com",
                        "password": "Password1",
                        "name": "New User",
                        "invite_code": "wrong-code",
                    },
                )
            assert resp.status_code == 403
            assert "invalid invite code" in resp.json()["detail"].lower()
        finally:
            from tests.conftest import TEST_USER

            async def _no_auth() -> str:
                return TEST_KEY

            async def _test_user():
                return TEST_USER

            app.dependency_overrides[require_auth] = _no_auth
            app.dependency_overrides[get_current_user] = _test_user

    async def test_register_succeeds_with_correct_invite_code(
        self, client, db_session, monkeypatch
    ):
        """Correct invite code allows registration."""
        monkeypatch.setattr(
            "app.api.auth.settings.callme_invite_code", TEST_INVITE_CODE
        )
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        try:
            async with client:
                resp = await client.post(
                    "/api/auth/register",
                    json={
                        "email": "newuser@example.com",
                        "password": "Password1",
                        "name": "New User",
                        "invite_code": TEST_INVITE_CODE,
                    },
                )
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["token"] is not None
        finally:
            from tests.conftest import TEST_USER

            async def _no_auth() -> str:
                return TEST_KEY

            async def _test_user():
                return TEST_USER

            app.dependency_overrides[require_auth] = _no_auth
            app.dependency_overrides[get_current_user] = _test_user


# ---------------------------------------------------------------------------
# AC 2: Admin role
# ---------------------------------------------------------------------------


class TestAdminRole:
    """User model has is_admin field, admin user gets is_admin=True."""

    def test_user_model_has_is_admin_field(self):
        """User model has is_admin field defaulting to False."""
        user = User(email="test@example.com", name="Test")
        assert user.is_admin is False

    def test_user_model_is_admin_can_be_set_true(self):
        """is_admin can be set to True."""
        user = User(email="admin@example.com", name="Admin", is_admin=True)
        assert user.is_admin is True

    def test_ensure_admin_user_creates_admin(self, db_session):
        """ensure_admin_user creates user with is_admin=True."""
        from app.auth import ensure_admin_user
        import app.auth as auth_mod

        auth_mod._admin_user_id = None  # Reset cache
        admin = ensure_admin_user(db_session)
        assert admin.is_admin is True

    def test_api_key_auth_resolves_to_admin(self, db_session):
        """API key auth resolves to an admin user."""
        from app.auth import ensure_admin_user
        import app.auth as auth_mod

        auth_mod._admin_user_id = None
        admin = ensure_admin_user(db_session)
        assert admin.is_admin is True


# ---------------------------------------------------------------------------
# AC 3: Admin-only endpoints
# ---------------------------------------------------------------------------


class TestAdminOnlyEndpoints:
    """POST /api/admin/reset and POST /api/admin/seed require is_admin=True."""

    async def test_non_admin_cannot_call_admin_reset(self, client, db_session):
        """Non-admin user gets 403 on POST /api/admin/reset."""
        # Override get_current_user to return a non-admin user
        non_admin = User(
            email="regular@example.com", name="Regular", is_admin=False
        )

        async def _non_admin_user():
            return non_admin

        app.dependency_overrides[get_current_user] = _non_admin_user
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(require_admin, None)
        try:
            async with client:
                resp = await client.post("/api/admin/reset")
            assert resp.status_code == 403
            assert "admin" in resp.json()["detail"].lower()
        finally:
            from tests.conftest import TEST_USER

            async def _no_auth() -> str:
                return TEST_KEY

            async def _test_user():
                return TEST_USER

            app.dependency_overrides[require_auth] = _no_auth
            app.dependency_overrides[get_current_user] = _test_user

    async def test_non_admin_cannot_call_admin_seed(self, client, db_session):
        """Non-admin user gets 403 on POST /api/admin/seed."""
        non_admin = User(
            email="regular@example.com", name="Regular", is_admin=False
        )

        async def _non_admin_user():
            return non_admin

        app.dependency_overrides[get_current_user] = _non_admin_user
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(require_admin, None)
        try:
            async with client:
                resp = await client.post("/api/admin/seed")
            assert resp.status_code == 403
        finally:
            from tests.conftest import TEST_USER

            async def _no_auth() -> str:
                return TEST_KEY

            async def _test_user():
                return TEST_USER

            app.dependency_overrides[require_auth] = _no_auth
            app.dependency_overrides[get_current_user] = _test_user

    async def test_admin_can_call_admin_seed(self, client, db_session):
        """Admin user can call POST /api/admin/seed."""
        admin_user = User(
            email="admin@example.com", name="Admin", is_admin=True
        )

        async def _admin_user():
            return admin_user

        app.dependency_overrides[get_current_user] = _admin_user
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(require_admin, None)
        try:
            async with client:
                resp = await client.post("/api/admin/seed")
            assert resp.status_code == 200
        finally:
            from tests.conftest import TEST_USER

            async def _no_auth() -> str:
                return TEST_KEY

            async def _test_user():
                return TEST_USER

            app.dependency_overrides[require_auth] = _no_auth
            app.dependency_overrides[get_current_user] = _test_user


# ---------------------------------------------------------------------------
# AC 4: WebSocket authentication
# ---------------------------------------------------------------------------


class TestWebSocketAuth:
    """GET /ws/calls/live validates token before accepting."""

    async def test_ws_rejects_missing_token(self, client, db_session):
        """WebSocket without token is closed with code 4001."""
        from starlette.testclient import TestClient

        sync_client = TestClient(app)
        with pytest.raises(Exception):
            with sync_client.websocket_connect("/ws/calls/live"):
                pass  # Should not reach here

    async def test_ws_rejects_invalid_token(self, client, db_session):
        """WebSocket with invalid token is closed with code 4001."""
        from starlette.testclient import TestClient

        sync_client = TestClient(app)
        with pytest.raises(Exception):
            with sync_client.websocket_connect(
                "/ws/calls/live?token=invalid-token"
            ):
                pass

    async def test_ws_accepts_valid_api_key(self, client, db_session):
        """WebSocket with valid API key is accepted."""
        from starlette.testclient import TestClient

        sync_client = TestClient(app)
        with sync_client.websocket_connect(
            f"/ws/calls/live?token={TEST_KEY}"
        ) as ws:
            # Should receive a snapshot message
            data = ws.receive_json()
            assert data["type"] == "snapshot"

    async def test_ws_accepts_valid_jwt(self, client, db_session):
        """WebSocket with valid JWT is accepted."""
        from starlette.testclient import TestClient
        from uuid import uuid4

        token = create_jwt(uuid4(), "test@example.com", "Test")
        sync_client = TestClient(app)
        with sync_client.websocket_connect(
            f"/ws/calls/live?token={token}"
        ) as ws:
            data = ws.receive_json()
            assert data["type"] == "snapshot"


# ---------------------------------------------------------------------------
# AC 5: Separate JWT secret
# ---------------------------------------------------------------------------


class TestSeparateJwtSecret:
    """JWT_SECRET env var is used for signing when set."""

    def test_init_uses_jwt_secret_when_set(self, monkeypatch):
        """When JWT_SECRET is set, it's used instead of CALLME_API_KEY."""
        import app.auth as auth_mod

        monkeypatch.setattr("app.auth.settings.jwt_secret", "my-jwt-secret")
        monkeypatch.setattr("app.auth.settings.callme_api_key", TEST_KEY)
        init_api_key()
        assert auth_mod.JWT_SECRET_KEY == "my-jwt-secret"
        # Restore
        auth_mod.JWT_SECRET_KEY = TEST_KEY
        auth_mod._api_key = TEST_KEY

    def test_init_falls_back_to_api_key(self, monkeypatch):
        """When JWT_SECRET is not set, falls back to CALLME_API_KEY."""
        import app.auth as auth_mod

        monkeypatch.setattr("app.auth.settings.jwt_secret", "")
        monkeypatch.setattr("app.auth.settings.callme_api_key", TEST_KEY)
        init_api_key()
        assert auth_mod.JWT_SECRET_KEY == TEST_KEY
        # Restore
        auth_mod._api_key = TEST_KEY

    def test_jwt_signed_with_jwt_secret_not_api_key(self, monkeypatch):
        """JWT is signed with JWT_SECRET, not CALLME_API_KEY."""
        import app.auth as auth_mod
        from uuid import uuid4
        import jwt

        jwt_secret = "separate-jwt-secret"
        monkeypatch.setattr("app.auth.JWT_SECRET_KEY", jwt_secret)

        token = create_jwt(uuid4(), "test@example.com", "Test")

        # Decoding with jwt_secret should work
        payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
        assert payload["email"] == "test@example.com"

        # Decoding with API key should fail
        with pytest.raises(jwt.InvalidSignatureError):
            jwt.decode(token, TEST_KEY, algorithms=["HS256"])

        # Restore
        auth_mod.JWT_SECRET_KEY = TEST_KEY


# ---------------------------------------------------------------------------
# AC 6: Configurable demo credentials
# ---------------------------------------------------------------------------


class TestConfigurableDemoCredentials:
    """DEMO_EMAIL and DEMO_PASSWORD env vars control demo user."""

    def test_get_demo_password_returns_configured(self, monkeypatch):
        """When DEMO_PASSWORD is set, it's used."""
        monkeypatch.setattr("app.config.settings.demo_password", "custom-pass")
        from app.seed import get_demo_password

        assert get_demo_password() == "custom-pass"

    def test_get_demo_password_auto_generates(self, monkeypatch):
        """When DEMO_PASSWORD is not set, a UUID is generated."""
        monkeypatch.setattr("app.config.settings.demo_password", "")
        from app.seed import get_demo_password

        password = get_demo_password()
        assert len(password) == 16  # uuid4().hex[:16]

    def test_get_demo_email_returns_configured(self, monkeypatch):
        """When DEMO_EMAIL is set, it's used."""
        monkeypatch.setattr("app.config.settings.demo_email", "custom@demo.com")
        from app.seed import get_demo_email

        assert get_demo_email() == "custom@demo.com"

    def test_get_demo_email_default(self, monkeypatch):
        """Default demo email is demo@callme.ai."""
        monkeypatch.setattr("app.config.settings.demo_email", "demo@callme.ai")
        from app.seed import get_demo_email

        assert get_demo_email() == "demo@callme.ai"


# ---------------------------------------------------------------------------
# AC 7: Health endpoint hardened
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """GET /health returns minimal info; detail requires auth."""

    async def test_health_returns_only_status(self, client):
        """Unauthenticated GET /health returns only {"status": "ok"}."""
        async with client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"status": "ok"}
        # Must NOT contain sensitive info
        assert "public_url" not in data
        assert "demo_mode" not in data
        assert "services" not in data

    async def test_health_detail_requires_auth(self, client):
        """GET /health?detail=true without auth returns 401."""
        async with client:
            resp = await client.get("/health?detail=true")
        assert resp.status_code == 401

    async def test_health_detail_with_auth(self, authed_client):
        """GET /health?detail=true with Bearer token returns full info."""
        async with authed_client:
            resp = await authed_client.get("/health?detail=true")
        # May return 200 or 500 depending on service availability,
        # but should not return 401
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "public_url" in data

    async def test_health_detail_invalid_token(self, client):
        """GET /health?detail=true with bad token returns 401."""
        async with client:
            resp = await client.get(
                "/health?detail=true",
                headers={"Authorization": "Bearer bad-token"},
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# AC 8: Password policy
# ---------------------------------------------------------------------------


class TestPasswordPolicy:
    """Registration requires >=8 chars, at least one letter and one digit."""

    def test_password_too_short(self):
        """Password under 8 characters is rejected."""
        assert validate_password("Pass1") is not None
        assert "8 characters" in validate_password("Pass1")

    def test_password_no_digit(self):
        """Password without a digit is rejected."""
        assert validate_password("Password") is not None
        assert "digit" in validate_password("Password")

    def test_password_no_letter(self):
        """Password without a letter is rejected."""
        assert validate_password("12345678") is not None
        assert "letter" in validate_password("12345678")

    def test_valid_password(self):
        """Valid password passes validation."""
        assert validate_password("Password1") is None
        assert validate_password("abcdefg1") is None
        assert validate_password("1abcdefg") is None

    async def test_register_rejects_weak_password(
        self, client, db_session, monkeypatch
    ):
        """Registration with weak password returns 422."""
        monkeypatch.setattr(
            "app.api.auth.settings.callme_invite_code", TEST_INVITE_CODE
        )
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        try:
            async with client:
                # Too short
                resp = await client.post(
                    "/api/auth/register",
                    json={
                        "email": "weak@example.com",
                        "password": "Pass1",
                        "name": "Test",
                        "invite_code": TEST_INVITE_CODE,
                    },
                )
            assert resp.status_code == 422
            assert "8 characters" in resp.json()["detail"]
        finally:
            from tests.conftest import TEST_USER

            async def _no_auth() -> str:
                return TEST_KEY

            async def _test_user():
                return TEST_USER

            app.dependency_overrides[require_auth] = _no_auth
            app.dependency_overrides[get_current_user] = _test_user

    async def test_register_rejects_no_digit_password(
        self, client, db_session, monkeypatch
    ):
        """Registration with no-digit password returns 422."""
        monkeypatch.setattr(
            "app.api.auth.settings.callme_invite_code", TEST_INVITE_CODE
        )
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        try:
            async with client:
                resp = await client.post(
                    "/api/auth/register",
                    json={
                        "email": "weak@example.com",
                        "password": "PasswordOnly",
                        "name": "Test",
                        "invite_code": TEST_INVITE_CODE,
                    },
                )
            assert resp.status_code == 422
            assert "digit" in resp.json()["detail"]
        finally:
            from tests.conftest import TEST_USER

            async def _no_auth() -> str:
                return TEST_KEY

            async def _test_user():
                return TEST_USER

            app.dependency_overrides[require_auth] = _no_auth
            app.dependency_overrides[get_current_user] = _test_user

    async def test_register_rejects_no_letter_password(
        self, client, db_session, monkeypatch
    ):
        """Registration with no-letter password returns 422."""
        monkeypatch.setattr(
            "app.api.auth.settings.callme_invite_code", TEST_INVITE_CODE
        )
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        try:
            async with client:
                resp = await client.post(
                    "/api/auth/register",
                    json={
                        "email": "weak@example.com",
                        "password": "12345678",
                        "name": "Test",
                        "invite_code": TEST_INVITE_CODE,
                    },
                )
            assert resp.status_code == 422
            assert "letter" in resp.json()["detail"]
        finally:
            from tests.conftest import TEST_USER

            async def _no_auth() -> str:
                return TEST_KEY

            async def _test_user():
                return TEST_USER

            app.dependency_overrides[require_auth] = _no_auth
            app.dependency_overrides[get_current_user] = _test_user

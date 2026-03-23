"""Tests for Story 22 — User accounts & multi-tenant isolation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session, select

from app.auth import (
    create_jwt,
    decode_jwt,
    get_current_user,
    hash_password,
    require_auth,
    verify_password,
)
from app.db.models import Call, PhoneNumber, Setting, User, Workflow
from app.main import app
from tests.conftest import TEST_USER, TEST_USER_ID


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = hash_password("my-secret-123")
        assert hashed != "my-secret-123"
        assert verify_password("my-secret-123", hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("correct-password")
        assert not verify_password("wrong-password", hashed)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


class TestJWT:
    @pytest.fixture(autouse=True)
    def _set_jwt_secret(self, monkeypatch):
        monkeypatch.setattr("app.auth.JWT_SECRET_KEY", "test-jwt-secret-key-1234567890")

    def test_create_and_decode(self):
        uid = uuid4()
        token = create_jwt(uid, "alice@example.com", "Alice")
        payload = decode_jwt(token)
        assert payload["sub"] == str(uid)
        assert payload["email"] == "alice@example.com"
        assert payload["name"] == "Alice"
        assert "exp" in payload
        assert "iat" in payload

    def test_invalid_token_raises(self):
        import jwt as pyjwt

        with pytest.raises(pyjwt.InvalidTokenError):
            decode_jwt("not-a-valid-jwt")

    def test_expired_token_raises(self, monkeypatch):
        import jwt as pyjwt
        from datetime import datetime, timedelta, timezone

        # Create a token that's already expired
        payload = {
            "sub": str(uuid4()),
            "email": "x@x.com",
            "name": "X",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        token = pyjwt.encode(payload, "test-jwt-secret-key-1234567890", algorithm="HS256")
        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_jwt(token)


# ---------------------------------------------------------------------------
# Registration endpoint
# ---------------------------------------------------------------------------

TEST_JWT_SECRET = "test-jwt-secret-key-for-auth-tests"


TEST_INVITE_CODE = "test-invite-code"


class TestRegister:
    @pytest.fixture(autouse=True)
    def _set_jwt_secret(self, monkeypatch):
        monkeypatch.setattr("app.auth.JWT_SECRET_KEY", TEST_JWT_SECRET)
        # Story 26: registration requires invite code
        monkeypatch.setattr("app.config.settings.callme_invite_code", TEST_INVITE_CODE)

    async def test_register_creates_user(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/auth/register", json={
                "email": "newuser@example.com",
                "password": "strong-password-123",
                "name": "New User",
                "invite_code": TEST_INVITE_CODE,
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["token"] is not None
        assert body["user"]["email"] == "newuser@example.com"
        assert body["user"]["name"] == "New User"

        # Verify JWT is valid
        payload = decode_jwt(body["token"])
        assert payload["email"] == "newuser@example.com"

        # Verify user exists in DB
        user = db_session.exec(
            select(User).where(User.email == "newuser@example.com")
        ).first()
        assert user is not None
        assert user.name == "New User"
        assert user.password_hash != ""

    async def test_register_duplicate_email_rejected(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # First registration
            resp1 = await c.post("/api/auth/register", json={
                "email": "dup@example.com",
                "password": "password-1abc",
                "invite_code": TEST_INVITE_CODE,
            })
            assert resp1.status_code == 200

            # Duplicate
            resp2 = await c.post("/api/auth/register", json={
                "email": "dup@example.com",
                "password": "another-pw1",
                "invite_code": TEST_INVITE_CODE,
            })
            assert resp2.status_code == 409

    async def test_register_short_password_rejected(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/auth/register", json={
                "email": "short@example.com",
                "password": "12a",  # too short
                "invite_code": TEST_INVITE_CODE,
            })
            assert resp.status_code == 422

    async def test_register_invalid_email_rejected(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/auth/register", json={
                "email": "not-an-email",
                "password": "password-123",
                "invite_code": TEST_INVITE_CODE,
            })
            assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Login endpoint (email + password)
# ---------------------------------------------------------------------------


class TestEmailLogin:
    @pytest.fixture(autouse=True)
    def _set_jwt_secret(self, monkeypatch):
        monkeypatch.setattr("app.auth.JWT_SECRET_KEY", TEST_JWT_SECRET)

    async def test_login_with_email_password(self, db_session):
        # Create a user with a known password
        user = User(
            email="login@example.com",
            password_hash=hash_password("my-password"),
            name="Login User",
        )
        db_session.add(user)
        db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/auth/login", json={
                "email": "login@example.com",
                "password": "my-password",
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["user"]["email"] == "login@example.com"
        payload = decode_jwt(body["token"])
        assert payload["sub"] == str(user.id)

    async def test_login_wrong_password_rejected(self, db_session):
        user = User(
            email="wrong@example.com",
            password_hash=hash_password("correct"),
            name="Wrong",
        )
        db_session.add(user)
        db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/auth/login", json={
                "email": "wrong@example.com",
                "password": "incorrect",
            })
        assert resp.status_code == 401

    async def test_login_unknown_email_rejected(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/auth/login", json={
                "email": "nobody@example.com",
                "password": "whatever",
            })
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /me endpoint
# ---------------------------------------------------------------------------


class TestMe:
    @pytest.fixture(autouse=True)
    def _set_jwt_secret(self, monkeypatch):
        monkeypatch.setattr("app.auth.JWT_SECRET_KEY", TEST_JWT_SECRET)

    async def test_me_returns_current_user(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as c:
            resp = await c.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        # Using the overridden get_current_user which returns TEST_USER
        assert data["email"] == TEST_USER.email
        assert data["name"] == TEST_USER.name


# ---------------------------------------------------------------------------
# Tenant isolation — workflows
# ---------------------------------------------------------------------------


class TestWorkflowIsolation:
    """User A cannot see, edit, or delete User B's workflows."""

    @pytest.fixture(autouse=True)
    def _set_jwt_secret(self, monkeypatch):
        monkeypatch.setattr("app.auth.JWT_SECRET_KEY", TEST_JWT_SECRET)
        monkeypatch.setattr("app.auth._api_key", TEST_JWT_SECRET)

    def _make_client(self, user: User) -> AsyncClient:
        """Create an HTTP client authenticated as the given user."""
        token = create_jwt(user.id, user.email, user.name)
        transport = ASGITransport(app=app)
        return AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        )

    async def test_user_a_cannot_see_user_b_workflows(self, db_session):
        # Create two users
        user_a = User(email="a@test.com", password_hash="", name="A")
        user_b = User(email="b@test.com", password_hash="", name="B")
        db_session.add_all([user_a, user_b])
        db_session.commit()
        db_session.refresh(user_a)
        db_session.refresh(user_b)

        # Override get_current_user to return user_a
        async def _as_user_a():
            return user_a

        async def _as_user_b():
            return user_b

        graph = {
            "id": "wf_test",
            "name": "Test",
            "version": 1,
            "entry_node_id": "greeting",
            "nodes": [{"id": "greeting", "type": "conversation", "data": {"instructions": "Hi", "max_iterations": 3}}],
            "edges": [],
        }

        # User A creates a workflow
        app.dependency_overrides[get_current_user] = _as_user_a
        client_a = self._make_client(user_a)
        async with client_a:
            resp = await client_a.post("/api/workflows", json={
                "name": "A's Workflow",
                "graph_json": graph,
            })
            assert resp.status_code == 201, resp.json()
            wf_a_id = resp.json()["id"]

        # User B should see no workflows
        app.dependency_overrides[get_current_user] = _as_user_b
        client_b = self._make_client(user_b)
        async with client_b:
            resp = await client_b.get("/api/workflows")
            assert resp.status_code == 200
            assert resp.json() == []

            # User B trying to get A's workflow directly → 404 (not found, not 403)
            resp = await client_b.get(f"/api/workflows/{wf_a_id}")
            assert resp.status_code == 404

        # Restore override
        async def _test_user():
            return TEST_USER
        app.dependency_overrides[get_current_user] = _test_user

    async def test_user_cannot_delete_others_workflow(self, db_session):
        user_a = User(email="del_a@test.com", password_hash="", name="A")
        user_b = User(email="del_b@test.com", password_hash="", name="B")
        db_session.add_all([user_a, user_b])
        db_session.commit()
        db_session.refresh(user_a)
        db_session.refresh(user_b)

        # Create workflow owned by user_a directly
        wf = Workflow(
            name="A's private workflow",
            graph_json={"nodes": [], "edges": [], "entry_node_id": "n1"},
            user_id=user_a.id,
        )
        db_session.add(wf)
        db_session.commit()
        db_session.refresh(wf)

        # User B tries to delete it
        async def _as_user_b():
            return user_b
        app.dependency_overrides[get_current_user] = _as_user_b

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.delete(f"/api/workflows/{wf.id}")
            assert resp.status_code == 404

        # Restore
        async def _test_user():
            return TEST_USER
        app.dependency_overrides[get_current_user] = _test_user


# ---------------------------------------------------------------------------
# Tenant isolation — calls
# ---------------------------------------------------------------------------


class TestCallIsolation:
    """User A cannot see User B's call logs."""

    async def test_calls_filtered_by_user(self, db_session):
        user_a = User(email="calls_a@test.com", password_hash="", name="A")
        user_b = User(email="calls_b@test.com", password_hash="", name="B")
        db_session.add_all([user_a, user_b])
        db_session.commit()
        db_session.refresh(user_a)
        db_session.refresh(user_b)

        # Create calls for each user
        db_session.add(Call(call_sid="CA_A", from_number="+1", to_number="+2", user_id=user_a.id))
        db_session.add(Call(call_sid="CA_B", from_number="+3", to_number="+4", user_id=user_b.id))
        db_session.commit()

        # User A should only see their call
        async def _as_user_a():
            return user_a
        app.dependency_overrides[get_current_user] = _as_user_a

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/calls")
            assert resp.status_code == 200
            items = resp.json()
            assert len(items) == 1
            assert items[0]["call_sid"] == "CA_A"

        # User B should only see their call
        async def _as_user_b():
            return user_b
        app.dependency_overrides[get_current_user] = _as_user_b

        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/calls")
            assert resp.status_code == 200
            items = resp.json()
            assert len(items) == 1
            assert items[0]["call_sid"] == "CA_B"

        # Restore
        async def _test_user():
            return TEST_USER
        app.dependency_overrides[get_current_user] = _test_user


# ---------------------------------------------------------------------------
# Tenant isolation — settings
# ---------------------------------------------------------------------------


class TestSettingsIsolation:
    """Each user has their own settings."""

    async def test_settings_scoped_to_user(self, db_session):
        user_a = User(email="set_a@test.com", password_hash="", name="A")
        user_b = User(email="set_b@test.com", password_hash="", name="B")
        db_session.add_all([user_a, user_b])
        db_session.commit()
        db_session.refresh(user_a)
        db_session.refresh(user_b)

        async def _as_user_a():
            return user_a

        async def _as_user_b():
            return user_b

        transport = ASGITransport(app=app)

        # User A sets an API key
        app.dependency_overrides[get_current_user] = _as_user_a
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.put("/api/settings", json={
                "settings": {"openai_api_key": "sk-user-a-key"},
            })
            assert resp.status_code == 200

        # User B should not see it
        app.dependency_overrides[get_current_user] = _as_user_b
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/settings")
            assert resp.status_code == 200
            body = resp.json()
            assert body["settings"]["openai_api_key"] == ""

        # User A should see it (redacted)
        app.dependency_overrides[get_current_user] = _as_user_a
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/settings")
            assert resp.status_code == 200
            body = resp.json()
            assert body["settings"]["openai_api_key"] != ""
            assert body["settings"]["openai_api_key"].startswith("••••")

        # Restore
        async def _test_user():
            return TEST_USER
        app.dependency_overrides[get_current_user] = _test_user


# ---------------------------------------------------------------------------
# API key auth still works (admin mode)
# ---------------------------------------------------------------------------


class TestAPIKeyAdminAuth:
    """API key authentication returns admin user and grants access."""

    @pytest.fixture(autouse=True)
    def _set_api_key(self, monkeypatch):
        monkeypatch.setattr("app.auth._api_key", "admin-test-key-1234567890123456")
        monkeypatch.setattr("app.auth.JWT_SECRET_KEY", "admin-test-key-1234567890123456")

    async def test_api_key_login_returns_jwt(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/auth/login", json={
                "key": "admin-test-key-1234567890123456",
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["user"]["email"] == "admin@local"
        # Token is a JWT, not raw key
        payload = decode_jwt(body["token"])
        assert payload["email"] == "admin@local"


# ---------------------------------------------------------------------------
# Backfill helper
# ---------------------------------------------------------------------------


class TestBackfill:
    """Test that backfill_user_ids assigns orphaned rows to admin."""

    def test_backfill_assigns_orphans(self, db_session):
        from app.auth import backfill_user_ids

        admin = User(email="admin@local", name="Admin", password_hash="")
        db_session.add(admin)
        db_session.commit()
        db_session.refresh(admin)

        # Create orphaned workflow (no user_id)
        wf = Workflow(
            name="Orphan WF",
            graph_json={"nodes": [], "edges": [], "entry_node_id": "n1"},
        )
        db_session.add(wf)
        db_session.commit()
        db_session.refresh(wf)

        assert wf.user_id is None

        backfill_user_ids(db_session, admin.id)

        db_session.refresh(wf)
        assert wf.user_id == admin.id

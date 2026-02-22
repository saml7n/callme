"""Tests for the integrations CRUD API."""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Integration, IntegrationType
from app.main import app


@pytest.fixture
def sample_webhook_config() -> dict[str, Any]:
    return {
        "url": "https://example.com/hook",
        "method": "POST",
        "headers": {"X-Custom": "value"},
    }


@pytest.fixture
def sample_google_config() -> dict[str, Any]:
    return {
        "client_id": "test-client-id.apps.googleusercontent.com",
        "client_secret": "test-client-secret",
        "calendar_id": "primary",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_integration(
    client: AsyncClient,
    name: str = "Test Webhook",
    type_: str = "webhook",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or {
        "url": "https://example.com/hook",
        "method": "POST",
    }
    resp = await client.post(
        "/api/integrations",
        json={"type": type_, "name": name, "config": config},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreateIntegration:
    @pytest.mark.anyio
    async def test_create_webhook(self, db_session, sample_webhook_config):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/integrations",
                json={
                    "type": "webhook",
                    "name": "My Webhook",
                    "config": sample_webhook_config,
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["type"] == "webhook"
            assert data["name"] == "My Webhook"
            # Secret keys are redacted
            assert "url" in data["config_redacted"]

    @pytest.mark.anyio
    async def test_create_google_calendar(self, db_session, sample_google_config):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/integrations",
                json={
                    "type": "google_calendar",
                    "name": "My Calendar",
                    "config": sample_google_config,
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["type"] == "google_calendar"
            # client_secret should be redacted
            assert data["config_redacted"]["client_secret"].startswith("••••")

    @pytest.mark.anyio
    async def test_create_webhook_invalid_url(self, db_session):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/integrations",
                json={
                    "type": "webhook",
                    "name": "Bad Webhook",
                    "config": {"url": "not-a-url"},
                },
            )
            assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_create_google_missing_calendar_id(self, db_session):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/integrations",
                json={
                    "type": "google_calendar",
                    "name": "Bad Calendar",
                    "config": {"client_id": "abc"},
                },
            )
            assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_create_with_empty_name_rejected(self, db_session):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/integrations",
                json={
                    "type": "webhook",
                    "name": "",
                    "config": {"url": "https://example.com/hook"},
                },
            )
            assert resp.status_code == 422


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestListIntegrations:
    @pytest.mark.anyio
    async def test_list_empty(self, db_session):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/integrations")
            assert resp.status_code == 200
            assert resp.json() == []

    @pytest.mark.anyio
    async def test_list_returns_created(self, db_session, sample_webhook_config):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await _create_integration(client, config=sample_webhook_config)
            await _create_integration(
                client, name="Second", config=sample_webhook_config
            )
            resp = await client.get("/api/integrations")
            assert resp.status_code == 200
            assert len(resp.json()) == 2

    @pytest.mark.anyio
    async def test_list_redacts_secrets(self, db_session):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await _create_integration(
                client,
                name="Google Cal",
                type_="google_calendar",
                config={
                    "client_id": "id123",
                    "client_secret": "supersecret",
                    "calendar_id": "primary",
                },
            )
            resp = await client.get("/api/integrations")
            data = resp.json()
            assert len(data) == 1
            cfg = data[0]["config_redacted"]
            assert cfg["client_secret"].startswith("••••")
            # client_id is not in the sensitive list so should be visible
            assert cfg["client_id"] == "id123"


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


class TestUpdateIntegration:
    @pytest.mark.anyio
    async def test_update_name(self, db_session, sample_webhook_config):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await _create_integration(client, config=sample_webhook_config)
            iid = created["id"]
            resp = await client.put(
                f"/api/integrations/{iid}",
                json={"name": "Renamed"},
            )
            assert resp.status_code == 200
            assert resp.json()["name"] == "Renamed"

    @pytest.mark.anyio
    async def test_update_config(self, db_session, sample_webhook_config):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await _create_integration(client, config=sample_webhook_config)
            iid = created["id"]
            new_config = {"url": "https://new.example.com/hook", "method": "PUT"}
            resp = await client.put(
                f"/api/integrations/{iid}",
                json={"config": new_config},
            )
            assert resp.status_code == 200
            assert resp.json()["config_redacted"]["url"] == "https://new.example.com/hook"

    @pytest.mark.anyio
    async def test_update_nonexistent(self, db_session):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/integrations/00000000-0000-0000-0000-000000000000",
                json={"name": "nope"},
            )
            assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_update_with_invalid_config_rejected(self, db_session, sample_webhook_config):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await _create_integration(client, config=sample_webhook_config)
            iid = created["id"]
            resp = await client.put(
                f"/api/integrations/{iid}",
                json={"config": {"url": "bad"}},
            )
            assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDeleteIntegration:
    @pytest.mark.anyio
    async def test_delete(self, db_session, sample_webhook_config):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await _create_integration(client, config=sample_webhook_config)
            iid = created["id"]
            resp = await client.delete(f"/api/integrations/{iid}")
            assert resp.status_code == 204

            # Confirm gone
            resp = await client.get("/api/integrations")
            assert len(resp.json()) == 0

    @pytest.mark.anyio
    async def test_delete_nonexistent(self, db_session):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(
                "/api/integrations/00000000-0000-0000-0000-000000000000"
            )
            assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_delete_blocked_by_active_workflow(self, db_session, sample_webhook_config):
        """Cannot delete an integration used by an active workflow."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await _create_integration(client, config=sample_webhook_config)
            iid = created["id"]

            # Create a workflow that references this integration
            from app.db.models import Workflow

            wf = Workflow(
                name="Active WF",
                is_active=True,
                graph_json={
                    "id": "wf_int",
                    "name": "WF",
                    "version": 1,
                    "entry_node_id": "n1",
                    "nodes": [
                        {
                            "id": "n1",
                            "type": "action",
                            "data": {
                                "action_type": "integration",
                                "integration_id": iid,
                                "integration_action": "call_webhook",
                            },
                        }
                    ],
                    "edges": [],
                },
            )
            db_session.add(wf)
            db_session.commit()

            resp = await client.delete(f"/api/integrations/{iid}")
            assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


class TestTestIntegration:
    @pytest.mark.anyio
    async def test_test_webhook_unreachable(self, db_session):
        """Webhook test should report failure for unreachable URLs."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await _create_integration(
                client,
                config={"url": "https://localhost:19999/nonexistent", "method": "POST"},
            )
            iid = created["id"]
            resp = await client.post(f"/api/integrations/{iid}/test")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is False

    @pytest.mark.anyio
    async def test_test_google_no_refresh_token(self, db_session, sample_google_config):
        """Google test without refresh_token should report failure."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await _create_integration(
                client,
                name="GCal",
                type_="google_calendar",
                config=sample_google_config,
            )
            iid = created["id"]
            resp = await client.post(f"/api/integrations/{iid}/test")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is False
            assert "refresh_token" in data["detail"].lower() or "oauth" in data["detail"].lower()

    @pytest.mark.anyio
    async def test_test_nonexistent(self, db_session):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/integrations/00000000-0000-0000-0000-000000000000/test"
            )
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# OAuth endpoints
# ---------------------------------------------------------------------------


class TestOAuth:
    @pytest.mark.anyio
    async def test_oauth_start_returns_url(self, db_session, sample_google_config):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await _create_integration(
                client,
                name="GCal",
                type_="google_calendar",
                config=sample_google_config,
            )
            iid = created["id"]
            resp = await client.get(f"/api/integrations/{iid}/oauth/start")
            assert resp.status_code == 200
            data = resp.json()
            assert "url" in data
            assert "accounts.google.com" in data["url"]
            assert "test-client-id" in data["url"]

    @pytest.mark.anyio
    async def test_oauth_start_wrong_type(self, db_session, sample_webhook_config):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await _create_integration(client, config=sample_webhook_config)
            iid = created["id"]
            resp = await client.get(f"/api/integrations/{iid}/oauth/start")
            assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Config encryption at rest
# ---------------------------------------------------------------------------


class TestEncryptionAtRest:
    @pytest.mark.anyio
    async def test_config_stored_encrypted(self, db_session, sample_webhook_config):
        """The raw DB value should be encrypted, not plaintext JSON."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await _create_integration(client, config=sample_webhook_config)

        # Read directly from DB
        from uuid import UUID as _UUID
        integration = db_session.get(Integration, _UUID(created["id"]))
        raw = integration.config_encrypted

        # Should NOT be plain JSON
        try:
            parsed = json.loads(raw)
            # If it parses as JSON, it shouldn't match our config
            assert parsed != sample_webhook_config, "Config stored in plaintext!"
        except (json.JSONDecodeError, ValueError):
            pass  # expected — it's encrypted

        # But decryption should recover the original
        from app.crypto import decrypt

        decrypted = json.loads(decrypt(raw))
        assert decrypted == sample_webhook_config

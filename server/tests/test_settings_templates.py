"""Tests for Settings API and Templates API (Story 17)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def api_client(db_session):
    """Authenticated client with an in-memory DB (via conftest db_session)."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------


class TestSettingsGet:
    async def test_get_returns_empty_defaults(self, api_client):
        async with api_client as c:
            resp = await c.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "settings" in data
        assert "configured" in data
        assert data["configured"] is False
        # All keys should be empty when nothing configured
        for key in ["twilio_account_sid", "deepgram_api_key", "elevenlabs_api_key", "openai_api_key"]:
            assert data["settings"][key] == ""

    async def test_get_requires_auth(self):
        """Without db_session (no auth bypass), should require auth."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/settings")
        assert resp.status_code == 401


class TestSettingsPut:
    async def test_put_saves_and_redacts(self, api_client):
        async with api_client as c:
            resp = await c.put(
                "/api/settings",
                json={"settings": {"deepgram_api_key": "dg_test_abcdef1234"}},
            )
        assert resp.status_code == 200
        data = resp.json()
        # Should be redacted — shows last 4 chars
        assert data["settings"]["deepgram_api_key"].endswith("1234")
        assert data["settings"]["deepgram_api_key"].startswith("••••")

    async def test_put_multiple_keys(self, api_client):
        async with api_client as c:
            resp = await c.put(
                "/api/settings",
                json={
                    "settings": {
                        "twilio_account_sid": "AC_test_1234",
                        "deepgram_api_key": "dg_test_5678",
                        "elevenlabs_api_key": "el_test_9012",
                        "openai_api_key": "sk-test_3456",
                    }
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True  # all 4 core keys present

    async def test_put_ignores_unknown_keys(self, api_client):
        async with api_client as c:
            resp = await c.put(
                "/api/settings",
                json={"settings": {"bogus_key": "value", "deepgram_api_key": "dg_hello1234"}},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "bogus_key" not in data["settings"]
        assert data["settings"]["deepgram_api_key"].endswith("1234")

    async def test_put_requires_auth(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.put("/api/settings", json={"settings": {}})
        assert resp.status_code == 401


class TestSettingsValidate:
    async def test_validate_not_configured(self, api_client):
        async with api_client as c:
            resp = await c.post("/api/settings/validate")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert results["twilio"] == "not_configured"
        assert results["deepgram"] == "not_configured"
        assert results["elevenlabs"] == "not_configured"
        assert results["openai"] == "not_configured"

    async def test_validate_mocked_ok(self, api_client):
        """Save keys, then validate with mocked HTTP responses."""
        async with api_client as c:
            # First save all keys
            await c.put(
                "/api/settings",
                json={
                    "settings": {
                        "twilio_account_sid": "ACtest1234",
                        "twilio_auth_token": "auth_token_5678",
                        "deepgram_api_key": "dg_test_key",
                        "elevenlabs_api_key": "el_test_key",
                        "openai_api_key": "sk_test_key",
                    }
                },
            )

            # Mock HTTP calls
            mock_response = AsyncMock()
            mock_response.status_code = 200

            with patch("app.api.settings.httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                resp = await c.post("/api/settings/validate")

        assert resp.status_code == 200
        results = resp.json()["results"]
        assert results["twilio"] == "ok"
        assert results["deepgram"] == "ok"
        assert results["elevenlabs"] == "ok"
        assert results["openai"] == "ok"

    async def test_validate_missing_key_returns_not_configured(self, api_client):
        """If only some keys are set, missing ones should return not_configured."""
        async with api_client as c:
            await c.put(
                "/api/settings",
                json={"settings": {"deepgram_api_key": "dg_only_key"}},
            )

            mock_response = AsyncMock()
            mock_response.status_code = 200

            with patch("app.api.settings.httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                resp = await c.post("/api/settings/validate")

        results = resp.json()["results"]
        assert results["twilio"] == "not_configured"
        assert results["deepgram"] == "ok"


# ---------------------------------------------------------------------------
# Startup check — server starts with missing settings
# ---------------------------------------------------------------------------


class TestStartup:
    async def test_server_starts_without_settings(self):
        """The server should start fine without any settings configured."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "public_url" in data


# ---------------------------------------------------------------------------
# Templates API
# ---------------------------------------------------------------------------


class TestTemplates:
    async def test_list_templates(self, api_client):
        async with api_client as c:
            resp = await c.get("/api/templates")
        assert resp.status_code == 200
        templates = resp.json()
        assert isinstance(templates, list)
        assert len(templates) >= 3  # simple_receptionist, appointment_booking, faq_bot
        names = {t["name"] for t in templates}
        assert "Simple Receptionist" in names
        assert "Appointment Booking" in names
        assert "FAQ Bot" in names

    async def test_template_has_graph(self, api_client):
        async with api_client as c:
            resp = await c.get("/api/templates")
        templates = resp.json()
        for t in templates:
            assert "graph" in t
            assert "nodes" in t["graph"]
            assert "edges" in t["graph"]
            assert "entry_node_id" in t["graph"]

    async def test_template_has_metadata(self, api_client):
        async with api_client as c:
            resp = await c.get("/api/templates")
        templates = resp.json()
        for t in templates:
            assert "id" in t
            assert "name" in t
            assert "description" in t
            assert "icon" in t
            assert t["description"]  # should not be empty

    async def test_create_workflow_from_template(self, api_client):
        """Selecting a template should allow creating a workflow with its graph."""
        async with api_client as c:
            # Get templates
            resp = await c.get("/api/templates")
            templates = resp.json()
            template = templates[0]

            # Create workflow from template graph
            resp = await c.post(
                "/api/workflows",
                json={
                    "name": template["name"],
                    "graph_json": template["graph"],
                },
            )
        assert resp.status_code == 201
        wf = resp.json()
        assert wf["name"] == template["name"]
        assert wf["graph_json"]["entry_node_id"] == template["graph"]["entry_node_id"]

    async def test_templates_require_auth(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/templates")
        assert resp.status_code == 401

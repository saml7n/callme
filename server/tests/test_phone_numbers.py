"""Tests for phone number management API (Story 14)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_graph() -> dict[str, Any]:
    return {
        "id": "wf_test",
        "name": "Test",
        "version": 1,
        "entry_node_id": "greeting",
        "nodes": [
            {
                "id": "greeting",
                "type": "conversation",
                "data": {"instructions": "Hi.", "max_iterations": 3},
            },
        ],
        "edges": [],
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class TestPhoneNumberCRUD:
    @pytest.mark.asyncio
    async def test_create_and_list(self, db_session):
        """Register a phone number, list returns it."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/phone-numbers",
                json={"number": "+441234567890", "label": "Main Office"},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["number"] == "+441234567890"
            assert data["label"] == "Main Office"
            assert data["workflow_id"] is None
            assert data["workflow_name"] is None

            # List
            resp = await c.get("/api/phone-numbers")
            assert resp.status_code == 200
            items = resp.json()
            assert len(items) == 1
            assert items[0]["number"] == "+441234567890"

    @pytest.mark.asyncio
    async def test_duplicate_number_returns_409(self, db_session):
        """Registering the same number twice → 409."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await c.post("/api/phone-numbers", json={"number": "+44111"})
            resp = await c.post("/api/phone-numbers", json={"number": "+44111"})
            assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_delete_unassigned(self, db_session):
        """Deleting an unassigned phone number succeeds."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/phone-numbers", json={"number": "+44222"},
            )
            phone_id = resp.json()["id"]

            resp = await c.delete(f"/api/phone-numbers/{phone_id}")
            assert resp.status_code == 204

            # Confirm it's gone
            resp = await c.get("/api/phone-numbers")
            assert len(resp.json()) == 0

    @pytest.mark.asyncio
    async def test_delete_active_blocked(self, db_session):
        """Deleting a phone number assigned to an active workflow → 409."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # Create phone
            resp = await c.post(
                "/api/phone-numbers", json={"number": "+44333"},
            )
            phone_id = resp.json()["id"]

            # Create + publish workflow to that number
            resp = await c.post(
                "/api/workflows",
                json={"name": "Active WF", "graph_json": _minimal_graph()},
            )
            wf_id = resp.json()["id"]
            await c.post(
                f"/api/workflows/{wf_id}/publish",
                json={"phone_number_id": phone_id},
            )

            # Try to delete → blocked
            resp = await c.delete(f"/api/phone-numbers/{phone_id}")
            assert resp.status_code == 409
            assert "active workflow" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.delete(f"/api/phone-numbers/{uuid4()}")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_includes_workflow_name(self, db_session):
        """When a phone number is assigned, listing shows workflow_name."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # Create phone
            resp = await c.post(
                "/api/phone-numbers", json={"number": "+44444", "label": "Dental"},
            )
            phone_id = resp.json()["id"]

            # Create + publish workflow
            resp = await c.post(
                "/api/workflows",
                json={"name": "Dental Reception", "graph_json": _minimal_graph()},
            )
            wf_id = resp.json()["id"]
            await c.post(
                f"/api/workflows/{wf_id}/publish",
                json={"phone_number_id": phone_id},
            )

            # List phone numbers
            resp = await c.get("/api/phone-numbers")
            items = resp.json()
            assert len(items) == 1
            assert items[0]["workflow_name"] == "Dental Reception"
            assert items[0]["workflow_id"] == wf_id


# ---------------------------------------------------------------------------
# Publish with phone_number_id
# ---------------------------------------------------------------------------

class TestPublishWithPhoneNumberId:
    @pytest.mark.asyncio
    async def test_publish_with_phone_number_id(self, db_session):
        """Publish assigns the phone number to the workflow."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # Register phone
            resp = await c.post(
                "/api/phone-numbers", json={"number": "+44100"},
            )
            phone_id = resp.json()["id"]

            # Create workflow
            resp = await c.post(
                "/api/workflows",
                json={"name": "WF A", "graph_json": _minimal_graph()},
            )
            wf_id = resp.json()["id"]

            # Publish
            resp = await c.post(
                f"/api/workflows/{wf_id}/publish",
                json={"phone_number_id": phone_id},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_active"] is True
            assert data["phone_number"] == "+44100"

    @pytest.mark.asyncio
    async def test_publish_deactivates_previous_workflow(self, db_session):
        """Publishing B on a number already used by A → deactivates A."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # Phone
            resp = await c.post(
                "/api/phone-numbers", json={"number": "+44200"},
            )
            phone_id = resp.json()["id"]

            # Workflow A published
            resp = await c.post(
                "/api/workflows",
                json={"name": "WF A", "graph_json": _minimal_graph()},
            )
            id_a = resp.json()["id"]
            await c.post(
                f"/api/workflows/{id_a}/publish",
                json={"phone_number_id": phone_id},
            )

            # Workflow B published to same number
            resp = await c.post(
                "/api/workflows",
                json={"name": "WF B", "graph_json": _minimal_graph()},
            )
            id_b = resp.json()["id"]
            await c.post(
                f"/api/workflows/{id_b}/publish",
                json={"phone_number_id": phone_id},
            )

            # A deactivated
            resp = await c.get(f"/api/workflows/{id_a}")
            assert resp.json()["is_active"] is False

            # B active
            resp = await c.get(f"/api/workflows/{id_b}")
            assert resp.json()["is_active"] is True
            assert resp.json()["phone_number"] == "+44200"

    @pytest.mark.asyncio
    async def test_publish_stale_version_returns_409(self, db_session):
        """Publishing with wrong version → 409."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/phone-numbers", json={"number": "+44300"},
            )
            phone_id = resp.json()["id"]

            resp = await c.post(
                "/api/workflows",
                json={"name": "WF", "graph_json": _minimal_graph()},
            )
            wf_id = resp.json()["id"]

            # Publish with wrong version
            resp = await c.post(
                f"/api/workflows/{wf_id}/publish",
                json={"phone_number_id": phone_id, "version": 99},
            )
            assert resp.status_code == 409
            assert "version" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_publish_correct_version_succeeds(self, db_session):
        """Publishing with matching version → success."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/phone-numbers", json={"number": "+44400"},
            )
            phone_id = resp.json()["id"]

            resp = await c.post(
                "/api/workflows",
                json={"name": "WF", "graph_json": _minimal_graph()},
            )
            wf_id = resp.json()["id"]
            current_version = resp.json()["version"]

            resp = await c.post(
                f"/api/workflows/{wf_id}/publish",
                json={"phone_number_id": phone_id, "version": current_version},
            )
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_publish_nonexistent_phone_returns_404(self, db_session):
        """Publishing with a bogus phone_number_id → 404."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/workflows",
                json={"name": "WF", "graph_json": _minimal_graph()},
            )
            wf_id = resp.json()["id"]

            resp = await c.post(
                f"/api/workflows/{wf_id}/publish",
                json={"phone_number_id": str(uuid4())},
            )
            assert resp.status_code == 404
            assert "phone number" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_publish_without_version_skips_check(self, db_session):
        """Publishing without version field → no concurrency check."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/phone-numbers", json={"number": "+44500"},
            )
            phone_id = resp.json()["id"]

            resp = await c.post(
                "/api/workflows",
                json={"name": "WF", "graph_json": _minimal_graph()},
            )
            wf_id = resp.json()["id"]

            # No version field
            resp = await c.post(
                f"/api/workflows/{wf_id}/publish",
                json={"phone_number_id": phone_id},
            )
            assert resp.status_code == 200

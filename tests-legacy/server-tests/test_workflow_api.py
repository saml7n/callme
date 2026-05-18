"""Tests for workflow CRUD API endpoints (Story 10)."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import PhoneNumber, Workflow
from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_graph() -> dict[str, Any]:
    return {
        "id": "wf_test",
        "name": "Test Workflow",
        "version": 1,
        "entry_node_id": "greeting",
        "nodes": [
            {
                "id": "greeting",
                "type": "conversation",
                "data": {"instructions": "Greet the caller.", "max_iterations": 3},
            },
        ],
        "edges": [],
    }


def _updated_graph() -> dict[str, Any]:
    g = _minimal_graph()
    g["name"] = "Updated Workflow"
    g["nodes"][0]["data"]["instructions"] = "Updated instructions."
    return g


# ---------------------------------------------------------------------------
# CRUD lifecycle
# ---------------------------------------------------------------------------

class TestWorkflowCRUD:
    async def test_create_read_update_delete(self, db_session):
        """Full CRUD lifecycle: create → read → update → delete → 404."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # CREATE
            resp = await c.post(
                "/api/workflows",
                json={"name": "Test Flow", "graph_json": _minimal_graph()},
            )
            assert resp.status_code == 201
            data = resp.json()
            wf_id = data["id"]
            assert data["name"] == "Test Flow"
            assert data["version"] == 1
            assert data["is_active"] is False
            assert data["graph_json"]["entry_node_id"] == "greeting"

            # READ
            resp = await c.get(f"/api/workflows/{wf_id}")
            assert resp.status_code == 200
            assert resp.json()["name"] == "Test Flow"

            # UPDATE name only
            resp = await c.put(
                f"/api/workflows/{wf_id}",
                json={"name": "Renamed Flow"},
            )
            assert resp.status_code == 200
            assert resp.json()["name"] == "Renamed Flow"
            assert resp.json()["version"] == 1  # no graph change

            # UPDATE graph_json → version bumps
            resp = await c.put(
                f"/api/workflows/{wf_id}",
                json={"graph_json": _updated_graph()},
            )
            assert resp.status_code == 200
            assert resp.json()["version"] == 2

            # LIST
            resp = await c.get("/api/workflows")
            assert resp.status_code == 200
            items = resp.json()
            assert any(w["id"] == wf_id for w in items)

            # DELETE
            resp = await c.delete(f"/api/workflows/{wf_id}")
            assert resp.status_code == 204

            # READ after delete → 404
            resp = await c.get(f"/api/workflows/{wf_id}")
            assert resp.status_code == 404

    async def test_get_nonexistent_returns_404(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(f"/api/workflows/{uuid4()}")
            assert resp.status_code == 404

    async def test_delete_nonexistent_returns_404(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.delete(f"/api/workflows/{uuid4()}")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestWorkflowValidation:
    async def test_invalid_graph_json_returns_422(self, db_session):
        """Creating a workflow with invalid graph_json → 422."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/workflows",
                json={"name": "Bad", "graph_json": {"not": "valid"}},
            )
            assert resp.status_code == 422

    async def test_empty_name_returns_422(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/workflows",
                json={"name": "", "graph_json": _minimal_graph()},
            )
            assert resp.status_code == 422

    async def test_missing_name_returns_422(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/workflows",
                json={"graph_json": _minimal_graph()},
            )
            assert resp.status_code == 422

    async def test_update_with_invalid_graph_returns_422(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # Create valid first
            resp = await c.post(
                "/api/workflows",
                json={"name": "Valid", "graph_json": _minimal_graph()},
            )
            wf_id = resp.json()["id"]

            # Update with bad graph
            resp = await c.put(
                f"/api/workflows/{wf_id}",
                json={"graph_json": {"broken": True}},
            )
            assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

class TestWorkflowPublish:
    async def test_publish_sets_active_and_phone(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # Register phone number first
            resp = await c.post(
                "/api/phone-numbers",
                json={"number": "+441234", "label": "Test"},
            )
            phone_id = resp.json()["id"]

            resp = await c.post(
                "/api/workflows",
                json={"name": "Flow A", "graph_json": _minimal_graph()},
            )
            wf_id = resp.json()["id"]

            resp = await c.post(
                f"/api/workflows/{wf_id}/publish",
                json={"phone_number_id": phone_id},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_active"] is True
            assert data["phone_number"] == "+441234"

    async def test_publish_deactivates_previous(self, db_session):
        """Publishing workflow B on the same number deactivates workflow A."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # Register phone number
            resp = await c.post(
                "/api/phone-numbers",
                json={"number": "+441234", "label": "Test"},
            )
            phone_id = resp.json()["id"]

            # Create and publish A
            resp = await c.post(
                "/api/workflows",
                json={"name": "Flow A", "graph_json": _minimal_graph()},
            )
            id_a = resp.json()["id"]
            await c.post(f"/api/workflows/{id_a}/publish", json={"phone_number_id": phone_id})

            # Create and publish B on the same number
            resp = await c.post(
                "/api/workflows",
                json={"name": "Flow B", "graph_json": _minimal_graph()},
            )
            id_b = resp.json()["id"]
            await c.post(f"/api/workflows/{id_b}/publish", json={"phone_number_id": phone_id})

            # A should be deactivated
            resp = await c.get(f"/api/workflows/{id_a}")
            assert resp.json()["is_active"] is False

            # B should be active
            resp = await c.get(f"/api/workflows/{id_b}")
            assert resp.json()["is_active"] is True

    async def test_get_active_workflow(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # No active workflow → 404
            resp = await c.get("/api/workflows/active")
            assert resp.status_code == 404

            # Register phone number
            resp = await c.post(
                "/api/phone-numbers",
                json={"number": "+441234", "label": "Test"},
            )
            phone_id = resp.json()["id"]

            # Create and publish
            resp = await c.post(
                "/api/workflows",
                json={"name": "Active", "graph_json": _minimal_graph()},
            )
            wf_id = resp.json()["id"]
            await c.post(f"/api/workflows/{wf_id}/publish", json={"phone_number_id": phone_id})

            # Now active
            resp = await c.get("/api/workflows/active")
            assert resp.status_code == 200
            assert resp.json()["id"] == wf_id

    async def test_get_active_filtered_by_phone(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # Register two phone numbers
            resp = await c.post(
                "/api/phone-numbers",
                json={"number": "+44", "label": "UK"},
            )
            phone_uk = resp.json()["id"]

            resp = await c.post(
                "/api/phone-numbers",
                json={"number": "+1", "label": "US"},
            )
            phone_us = resp.json()["id"]

            # Create two workflows on different numbers
            resp = await c.post(
                "/api/workflows",
                json={"name": "UK", "graph_json": _minimal_graph()},
            )
            id_uk = resp.json()["id"]
            await c.post(f"/api/workflows/{id_uk}/publish", json={"phone_number_id": phone_uk})

            resp = await c.post(
                "/api/workflows",
                json={"name": "US", "graph_json": _minimal_graph()},
            )
            id_us = resp.json()["id"]
            await c.post(f"/api/workflows/{id_us}/publish", json={"phone_number_id": phone_us})

            # Filter by phone
            resp = await c.get("/api/workflows/active", params={"phone_number": "+44"})
            assert resp.json()["id"] == id_uk

            resp = await c.get("/api/workflows/active", params={"phone_number": "+1"})
            assert resp.json()["id"] == id_us

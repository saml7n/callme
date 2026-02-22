"""Tests for call log API endpoints (Story 10)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Call, CallEvent, EventType
from app.main import app


class TestCallLogAPI:
    async def test_list_calls_empty(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/calls")
            assert resp.status_code == 200
            assert resp.json() == []

    async def test_create_call_and_list(self, db_session):
        """Create a call record directly, then list via API."""
        call = Call(call_sid="CA123", from_number="+44", to_number="+1")
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/calls")
            assert resp.status_code == 200
            items = resp.json()
            assert len(items) == 1
            assert items[0]["call_sid"] == "CA123"

    async def test_call_detail_with_events(self, db_session):
        """Create call + events, then verify detail endpoint."""
        call = Call(call_sid="CA456", from_number="+44", to_number="+1")
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        # Add events
        db_session.add(CallEvent(
            call_id=call.id,
            event_type=EventType.transcript,
            data_json={"transcript": "Hello"},
        ))
        db_session.add(CallEvent(
            call_id=call.id,
            event_type=EventType.llm_response,
            data_json={"response": "Hi there!"},
        ))
        db_session.add(CallEvent(
            call_id=call.id,
            event_type=EventType.node_transition,
            data_json={"from_node": "greeting", "to_node": "booking", "edge_id": "e1"},
        ))
        db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(f"/api/calls/{call.id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["call_sid"] == "CA456"
            assert len(data["events"]) == 3
            assert data["events"][0]["event_type"] == "transcript"
            assert data["events"][1]["event_type"] == "llm_response"
            assert data["events"][2]["event_type"] == "node_transition"

    async def test_call_not_found(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(f"/api/calls/{uuid4()}")
            assert resp.status_code == 404

    async def test_list_calls_ordered_by_most_recent(self, db_session):
        """Calls returned most-recent first."""
        import time

        call_a = Call(call_sid="CA_old", from_number="+44", to_number="+1")
        db_session.add(call_a)
        db_session.commit()

        time.sleep(0.01)  # ensure different timestamps

        call_b = Call(call_sid="CA_new", from_number="+44", to_number="+1")
        db_session.add(call_b)
        db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/calls")
            items = resp.json()
            assert len(items) == 2
            assert items[0]["call_sid"] == "CA_new"
            assert items[1]["call_sid"] == "CA_old"

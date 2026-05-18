"""Tests for call log API endpoints (Story 10 + Story 12)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Call, CallEvent, EventType, Workflow
from app.main import app
from tests.conftest import TEST_USER_ID


class TestCallLogAPI:
    async def test_list_calls_empty(self, db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/calls")
            assert resp.status_code == 200
            assert resp.json() == []

    async def test_create_call_and_list(self, db_session):
        """Create a call record directly, then list via API."""
        call = Call(call_sid="CA123", from_number="+44", to_number="+1", user_id=TEST_USER_ID)
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
        call = Call(call_sid="CA456", from_number="+44", to_number="+1", user_id=TEST_USER_ID)
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

        call_a = Call(call_sid="CA_old", from_number="+44", to_number="+1", user_id=TEST_USER_ID)
        db_session.add(call_a)
        db_session.commit()

        time.sleep(0.01)  # ensure different timestamps

        call_b = Call(call_sid="CA_new", from_number="+44", to_number="+1", user_id=TEST_USER_ID)
        db_session.add(call_b)
        db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/calls")
            items = resp.json()
            assert len(items) == 2
            assert items[0]["call_sid"] == "CA_new"
            assert items[1]["call_sid"] == "CA_old"

    async def test_status_completed(self, db_session):
        """A call with ended_at and no error/transfer events → completed."""
        now = datetime.now(timezone.utc)
        call = Call(
            call_sid="CA_done",
            from_number="+44",
            to_number="+1",
            ended_at=now,
            duration_seconds=60,
            user_id=TEST_USER_ID,
        )
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(f"/api/calls/{call.id}")
            assert resp.json()["status"] == "completed"

    async def test_status_in_progress(self, db_session):
        """A call with no ended_at → in_progress."""
        call = Call(call_sid="CA_live", from_number="+44", to_number="+1", user_id=TEST_USER_ID)
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(f"/api/calls/{call.id}")
            assert resp.json()["status"] == "in_progress"

    async def test_status_error(self, db_session):
        """A call with an error event → error."""
        now = datetime.now(timezone.utc)
        call = Call(
            call_sid="CA_err",
            from_number="+44",
            to_number="+1",
            ended_at=now,
            user_id=TEST_USER_ID,
        )
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        db_session.add(CallEvent(
            call_id=call.id,
            event_type=EventType.error,
            data_json={"message": "Something went wrong"},
        ))
        db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(f"/api/calls/{call.id}")
            assert resp.json()["status"] == "error"

    async def test_status_transferred(self, db_session):
        """A call with a transfer action → transferred."""
        now = datetime.now(timezone.utc)
        call = Call(
            call_sid="CA_xfer",
            from_number="+44",
            to_number="+1",
            ended_at=now,
            user_id=TEST_USER_ID,
        )
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        db_session.add(CallEvent(
            call_id=call.id,
            event_type=EventType.action_executed,
            data_json={"action_type": "transfer", "destination": "+1999"},
        ))
        db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(f"/api/calls/{call.id}")
            assert resp.json()["status"] == "transferred"

    async def test_workflow_name_present(self, db_session):
        """Call linked to a workflow returns its name."""
        wf = Workflow(
            name="Reception",
            graph_json={"nodes": [], "edges": [], "entry_node_id": "n1"},
            user_id=TEST_USER_ID,
        )
        db_session.add(wf)
        db_session.commit()
        db_session.refresh(wf)

        call = Call(
            call_sid="CA_wf",
            from_number="+44",
            to_number="+1",
            workflow_id=wf.id,
            user_id=TEST_USER_ID,
        )
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # Detail
            resp = await c.get(f"/api/calls/{call.id}")
            assert resp.json()["workflow_name"] == "Reception"
            # List
            resp = await c.get("/api/calls")
            assert resp.json()[0]["workflow_name"] == "Reception"

    async def test_workflow_name_null(self, db_session):
        """Call without a workflow returns null workflow_name."""
        call = Call(call_sid="CA_nowf", from_number="+44", to_number="+1", user_id=TEST_USER_ID)
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(f"/api/calls/{call.id}")
            assert resp.json()["workflow_name"] is None

    async def test_offset_pagination(self, db_session):
        """offset param skips calls."""
        for i in range(3):
            import time
            time.sleep(0.01)
            db_session.add(Call(
                call_sid=f"CA_p{i}",
                from_number="+44",
                to_number="+1",
                user_id=TEST_USER_ID,
            ))
        db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # All
            resp = await c.get("/api/calls?limit=10&offset=0")
            assert len(resp.json()) == 3

            # Skip first
            resp = await c.get("/api/calls?limit=10&offset=1")
            assert len(resp.json()) == 2

            # Skip two
            resp = await c.get("/api/calls?limit=10&offset=2")
            assert len(resp.json()) == 1


class TestLiveCallCount:
    """Tests for GET /api/calls/live/count endpoint."""

    async def test_count_returns_zero_when_no_active_calls(self, db_session):
        from app.events import event_bus

        # Ensure empty
        event_bus._active_calls.clear()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/calls/live/count")
            assert resp.status_code == 200
            assert resp.json() == {"count": 0}

    async def test_count_returns_active_call_count(self, db_session):
        from app.events import event_bus

        event_bus._active_calls.clear()
        # Register some fake active calls
        event_bus._active_calls["call-1"] = {"call_id": "call-1"}
        event_bus._active_calls["call-2"] = {"call_id": "call-2"}
        event_bus._transcripts["call-1"] = []
        event_bus._transcripts["call-2"] = []

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/api/calls/live/count")
                assert resp.status_code == 200
                assert resp.json() == {"count": 2}
        finally:
            event_bus._active_calls.clear()
            event_bus._transcripts.clear()

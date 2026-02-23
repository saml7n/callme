"""Tests for the event bus, live WebSocket, and call transfer API (Story 18)."""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.events import EventBus, event_bus
from app.main import app


# =========================================================================
# EventBus unit tests
# =========================================================================

class TestEventBus:
    """Tests for the in-memory event bus."""

    def test_register_and_get_active_calls(self):
        bus = EventBus()
        bus.register_call("c1", call_sid="CS1", caller_number="+1234", workflow_name="Flow A")
        active = bus.get_active_calls()
        assert len(active) == 1
        assert active[0]["call_id"] == "c1"
        assert active[0]["workflow_name"] == "Flow A"

    def test_unregister_removes_call(self):
        bus = EventBus()
        bus.register_call("c1")
        assert bus.is_active("c1")
        bus.unregister_call("c1", duration=30.0)
        assert not bus.is_active("c1")
        assert bus.get_active_calls() == []

    def test_subscribe_receives_events(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.emit({"type": "test", "data": 42})
        assert not q.empty()
        event = q.get_nowait()
        assert event["type"] == "test"
        assert event["data"] == 42

    def test_multiple_subscribers(self):
        bus = EventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.emit({"type": "hello"})
        assert q1.get_nowait()["type"] == "hello"
        assert q2.get_nowait()["type"] == "hello"

    def test_unsubscribe(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.emit({"type": "missed"})
        assert q.empty()

    def test_register_emits_call_started(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.register_call("c1", caller_number="+1234", workflow_name="W")
        event = q.get_nowait()
        assert event["type"] == "call_started"
        assert event["call_id"] == "c1"
        assert event["caller_number"] == "+1234"

    def test_unregister_emits_call_ended(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.register_call("c1")
        _ = q.get_nowait()  # consume call_started
        bus.unregister_call("c1", duration=45.5)
        event = q.get_nowait()
        assert event["type"] == "call_ended"
        assert event["duration"] == 45.5

    def test_get_call_sid(self):
        bus = EventBus()
        bus.register_call("c1", call_sid="CS_abc")
        assert bus.get_call_sid("c1") == "CS_abc"
        assert bus.get_call_sid("nope") is None

    def test_queue_full_drops_event(self):
        """When a subscriber queue is full, events are dropped silently."""
        bus = EventBus()
        q = bus.subscribe()
        # Fill the queue (maxsize=256)
        for i in range(260):
            bus.emit({"type": "flood", "i": i})
        # Queue should be at capacity, not raise
        assert q.qsize() == 256


# =========================================================================
# REST /api/calls/live
# =========================================================================

class TestLiveCallsREST:
    """Tests for GET /api/calls/live."""

    def test_returns_empty_list(self, db_session):
        client = TestClient(app)
        resp = client.get("/api/calls/live")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_active_calls(self, db_session):
        event_bus.register_call("c1", call_sid="CS1", workflow_name="Test")
        try:
            client = TestClient(app)
            resp = client.get("/api/calls/live")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["call_id"] == "c1"
        finally:
            event_bus.unregister_call("c1")


# =========================================================================
# WebSocket /ws/calls/live
# =========================================================================

class TestLiveWebSocket:
    """Tests for the live events WebSocket."""

    def test_snapshot_on_connect(self, db_session):
        event_bus.register_call("c1", call_sid="CS1", workflow_name="W")
        try:
            client = TestClient(app)
            with client.websocket_connect("/ws/calls/live") as ws:
                data = ws.receive_json()
                assert data["type"] == "snapshot"
                assert len(data["calls"]) == 1
                assert data["calls"][0]["call_id"] == "c1"
        finally:
            event_bus.unregister_call("c1")

    def test_receives_events(self, db_session):
        client = TestClient(app)
        with client.websocket_connect("/ws/calls/live") as ws:
            # Consume snapshot
            ws.receive_json()
            # Emit an event
            event_bus.emit({"type": "transcript", "call_id": "c1", "role": "caller", "text": "Hello"})
            data = ws.receive_json()
            assert data["type"] == "transcript"
            assert data["text"] == "Hello"

    def test_multiple_clients(self, db_session):
        client = TestClient(app)
        with client.websocket_connect("/ws/calls/live") as ws1:
            with client.websocket_connect("/ws/calls/live") as ws2:
                ws1.receive_json()  # snapshot
                ws2.receive_json()  # snapshot
                event_bus.emit({"type": "test_event", "value": 1})
                assert ws1.receive_json()["type"] == "test_event"
                assert ws2.receive_json()["type"] == "test_event"


# =========================================================================
# Transfer API
# =========================================================================

class TestTransferAPI:
    """Tests for POST /api/calls/{call_id}/transfer."""

    def test_transfer_not_active(self, db_session):
        client = TestClient(app)
        fake_id = str(uuid4())
        resp = client.post(f"/api/calls/{fake_id}/transfer")
        assert resp.status_code == 404

    def test_transfer_no_admin_number(self, db_session):
        call_id = str(uuid4())
        event_bus.register_call(call_id, call_sid="CS123")
        try:
            client = TestClient(app)
            with patch("app.api.live.get_admin_phone_number", return_value=""):
                resp = client.post(f"/api/calls/{call_id}/transfer")
                assert resp.status_code == 422
                assert "admin phone number" in resp.json()["detail"].lower()
        finally:
            event_bus.unregister_call(call_id)

    def test_transfer_success(self, db_session):
        call_id = str(uuid4())
        event_bus.register_call(call_id, call_sid="CS123")
        q = event_bus.subscribe()
        # Drain the call_started event
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass

        try:
            client = TestClient(app)
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            with (
                patch("app.api.live.get_admin_phone_number", return_value="+447999000111"),
                patch("app.api.live.get_twilio_account_sid", return_value="AC_test"),
                patch("app.api.live.settings") as mock_settings,
                patch("httpx.AsyncClient") as mock_httpx,
            ):
                mock_settings.twilio_api_key_sid = "SK_test"
                mock_settings.twilio_api_key_secret = "secret"
                mock_httpx.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                    post=AsyncMock(return_value=mock_resp)
                ))
                mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)

                resp = client.post(f"/api/calls/{call_id}/transfer")
                assert resp.status_code == 200
                body = resp.json()
                assert body["ok"] is True
                assert "•" in body["transferred_to"]  # masked number

            # Check transfer event was emitted
            events = []
            while not q.empty():
                events.append(q.get_nowait())
            transfer_events = [e for e in events if e["type"] == "transfer_started"]
            assert len(transfer_events) == 1
            assert transfer_events[0]["call_id"] == call_id
        finally:
            event_bus.unregister_call(call_id)
            event_bus.unsubscribe(q)


# =========================================================================
# Phone masking helper
# =========================================================================

class TestMaskPhone:
    def test_mask_normal(self):
        from app.api.live import _mask_phone
        # +447123456890 = 13 chars → first 3 + 7 dots + last 3
        assert _mask_phone("+447123456890") == "+44•••••••890"

    def test_mask_short(self):
        from app.api.live import _mask_phone
        assert _mask_phone("+1234") == "+1234"  # too short to mask

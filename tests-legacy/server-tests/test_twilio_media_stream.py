"""Tests for the Twilio bidirectional media-stream WebSocket handler."""

import base64
import json

import pytest

from app.twilio.media_stream import (
    MediaStreamState,
    build_clear_message,
    build_mark_message,
    build_outbound_media_message,
    decode_media_payload,
    parse_start_event,
)


# ---------------------------------------------------------------------------
# Pure-function unit tests (no WebSocket needed)
# ---------------------------------------------------------------------------

class TestParseStartEvent:
    def test_extracts_stream_metadata(self):
        msg = {
            "event": "start",
            "streamSid": "MZ123",
            "start": {
                "callSid": "CA456",
                "accountSid": "AC789",
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000},
                "tracks": ["inbound"],
            },
        }
        state = parse_start_event(msg)

        assert state.stream_sid == "MZ123"
        assert state.call_sid == "CA456"
        assert state.account_sid == "AC789"
        assert state.codec == "audio/x-mulaw"
        assert state.tracks == ["inbound"]
        assert state.is_connected is True

    def test_handles_missing_fields_gracefully(self):
        """If Twilio omits optional fields, parsing still succeeds with defaults."""
        state = parse_start_event({"event": "start"})
        assert state.stream_sid == ""
        assert state.call_sid == ""
        assert state.codec == ""


class TestDecodeMediaPayload:
    def test_decodes_base64_audio(self):
        raw_audio = b"\x00\xff" * 160  # 320 bytes of dummy μ-law
        payload = base64.b64encode(raw_audio).decode("ascii")
        msg = {"media": {"payload": payload}}

        decoded = decode_media_payload(msg)
        assert decoded == raw_audio

    def test_empty_payload_returns_empty_bytes(self):
        msg = {"media": {"payload": ""}}
        assert decode_media_payload(msg) == b""


class TestBuildOutboundMediaMessage:
    def test_builds_valid_json_with_base64_audio(self):
        audio = b"\x80\x81\x82\x83"
        result = json.loads(build_outbound_media_message("MZ123", audio))

        assert result["event"] == "media"
        assert result["streamSid"] == "MZ123"
        # Round-trip: decode the payload and compare
        decoded = base64.b64decode(result["media"]["payload"])
        assert decoded == audio


class TestBuildClearMessage:
    def test_builds_clear_event(self):
        result = json.loads(build_clear_message("MZ123"))
        assert result == {"event": "clear", "streamSid": "MZ123"}


class TestBuildMarkMessage:
    def test_builds_mark_event_with_name(self):
        result = json.loads(build_mark_message("MZ123", "end-of-greeting"))
        assert result["event"] == "mark"
        assert result["streamSid"] == "MZ123"
        assert result["mark"]["name"] == "end-of-greeting"


# ---------------------------------------------------------------------------
# WebSocket integration tests (FastAPI TestClient)
# ---------------------------------------------------------------------------

class TestMediaStreamWebSocket:
    @pytest.mark.asyncio
    async def test_start_event_is_parsed(self):
        """Sending a 'start' event doesn't crash and the connection stays open."""
        from httpx import ASGITransport, AsyncClient
        from starlette.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        with client.websocket_connect("/twilio/media-stream") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "event": "start",
                        "streamSid": "MZ_test",
                        "start": {
                            "callSid": "CA_test",
                            "accountSid": "AC_test",
                            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000},
                            "tracks": ["inbound"],
                        },
                    }
                )
            )
            # Send stop so the handler exits cleanly
            ws.send_text(json.dumps({"event": "stop"}))

    @pytest.mark.asyncio
    async def test_media_event_is_accepted(self):
        """Sending media events with base64 audio doesn't crash."""
        from starlette.testclient import TestClient

        from app.main import app

        audio = base64.b64encode(b"\x00" * 160).decode()
        client = TestClient(app)
        with client.websocket_connect("/twilio/media-stream") as ws:
            ws.send_text(
                json.dumps({"event": "media", "media": {"payload": audio}})
            )
            ws.send_text(json.dumps({"event": "stop"}))

    @pytest.mark.asyncio
    async def test_stop_event_closes_cleanly(self):
        """A 'stop' event ends the handler without error."""
        from starlette.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        with client.websocket_connect("/twilio/media-stream") as ws:
            ws.send_text(json.dumps({"event": "stop"}))

    @pytest.mark.asyncio
    async def test_connected_event_is_handled(self):
        """A 'connected' event is accepted without error."""
        from starlette.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        with client.websocket_connect("/twilio/media-stream") as ws:
            ws.send_text(
                json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"})
            )
            ws.send_text(json.dumps({"event": "stop"}))

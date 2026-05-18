"""Tests for the Deepgram streaming STT client (mocked WebSocket)."""

from __future__ import annotations

import json
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.stt.deepgram import (
    DeepgramAuthError,
    DeepgramClosedError,
    DeepgramConnectionError,
    DeepgramSTTClient,
    TranscriptEvent,
)


def _make_result_msg(
    transcript: str,
    is_final: bool = True,
    speech_final: bool = False,
    confidence: float = 0.98,
) -> str:
    """Build a realistic Deepgram 'Results' JSON message."""
    return json.dumps(
        {
            "type": "Results",
            "channel_index": [0, 1],
            "duration": 1.5,
            "start": 0.0,
            "is_final": is_final,
            "speech_final": speech_final,
            "channel": {
                "alternatives": [
                    {
                        "transcript": transcript,
                        "confidence": confidence,
                        "words": [],
                    }
                ]
            },
        }
    )


class _AsyncWSIter:
    """Fake async-iterable WebSocket that yields pre-canned messages."""

    def __init__(self, messages: list[str]) -> None:
        self._messages = messages
        self.send = AsyncMock()
        self.close = AsyncMock()

    def __aiter__(self):
        return self._iter_messages()

    async def _iter_messages(self):
        for m in self._messages:
            yield m


class _AsyncWSIterRaise:
    """Fake async-iterable WebSocket that raises on iteration."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.send = AsyncMock()
        self.close = AsyncMock()

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        raise self._exc
        yield  # noqa: F401 — unreachable, makes this an async generator


class TestDeepgramSTTClient:
    """Unit tests for DeepgramSTTClient with mocked WebSocket."""

    def test_build_url_includes_all_params(self):
        client = DeepgramSTTClient(api_key="test-key", endpointing=500)
        url = client._build_url()
        assert "model=nova-3" in url
        assert "encoding=mulaw" in url
        assert "sample_rate=8000" in url
        assert "channels=1" in url
        assert "punctuate=true" in url
        assert "endpointing=500" in url
        assert "smart_format=true" in url
        assert "interim_results=true" in url

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Successful connection sets the internal WebSocket."""
        client = DeepgramSTTClient(api_key="test-key")
        mock_ws = AsyncMock()

        async def _fake_connect(*a, **kw):
            return mock_ws

        with patch("app.stt.deepgram.websockets.asyncio.client.connect", side_effect=_fake_connect):
            await client.connect()

        assert client._ws is mock_ws

    @pytest.mark.asyncio
    async def test_connect_auth_failure_raises(self):
        """401 from Deepgram raises DeepgramAuthError."""
        from websockets.exceptions import InvalidStatus
        from websockets.http11 import Response

        client = DeepgramSTTClient(api_key="bad-key")
        exc = InvalidStatus(Response(401, "Unauthorized", {}))

        with patch("app.stt.deepgram.websockets.asyncio.client.connect", side_effect=exc):
            with pytest.raises(DeepgramAuthError, match="401"):
                await client.connect()

    @pytest.mark.asyncio
    async def test_connect_other_failure_raises(self):
        """Non-401 HTTP errors raise DeepgramConnectionError."""
        from websockets.exceptions import InvalidStatus
        from websockets.http11 import Response

        client = DeepgramSTTClient(api_key="test-key")
        exc = InvalidStatus(Response(500, "Internal Server Error", {}))

        with patch("app.stt.deepgram.websockets.asyncio.client.connect", side_effect=exc):
            with pytest.raises(DeepgramConnectionError, match="500"):
                await client.connect()

    @pytest.mark.asyncio
    async def test_send_audio_forwards_bytes(self):
        """send_audio passes raw bytes to the WebSocket."""
        client = DeepgramSTTClient(api_key="test-key")
        mock_ws = AsyncMock()
        client._ws = mock_ws

        audio = b"\x00\xff" * 160
        await client.send_audio(audio)

        mock_ws.send.assert_awaited_once_with(audio)

    @pytest.mark.asyncio
    async def test_send_audio_after_close_raises(self):
        """Calling send_audio after close() raises DeepgramClosedError."""
        client = DeepgramSTTClient(api_key="test-key")
        client._closed = True

        with pytest.raises(DeepgramClosedError):
            await client.send_audio(b"\x00")

    @pytest.mark.asyncio
    async def test_send_audio_without_connect_raises(self):
        """Calling send_audio before connect() raises DeepgramConnectionError."""
        client = DeepgramSTTClient(api_key="test-key")

        with pytest.raises(DeepgramConnectionError, match="Not connected"):
            await client.send_audio(b"\x00")

    @pytest.mark.asyncio
    async def test_receive_transcript_yields_events(self):
        """receive_transcripts yields TranscriptEvent for each Results message."""
        client = DeepgramSTTClient(api_key="test-key")

        messages = [
            _make_result_msg("hello", is_final=False, speech_final=False),
            _make_result_msg("hello world", is_final=True, speech_final=False),
            _make_result_msg("hello world", is_final=True, speech_final=True, confidence=0.99),
        ]

        mock_ws = _AsyncWSIter(messages)
        client._ws = mock_ws

        events: list[TranscriptEvent] = []
        async for event in client.receive_transcripts():
            events.append(event)

        assert len(events) == 3
        assert events[0].transcript == "hello"
        assert events[0].is_final is False
        assert events[1].is_final is True
        assert events[1].speech_final is False
        assert events[2].speech_final is True
        assert events[2].confidence == 0.99

    @pytest.mark.asyncio
    async def test_receive_skips_non_result_messages(self):
        """Non-Results messages (e.g. Metadata) are silently skipped."""
        client = DeepgramSTTClient(api_key="test-key")

        messages = [
            json.dumps({"type": "Metadata", "request_id": "abc"}),
            _make_result_msg("hello", is_final=True, speech_final=True),
        ]

        mock_ws = _AsyncWSIter(messages)
        client._ws = mock_ws

        events = [e async for e in client.receive_transcripts()]
        assert len(events) == 1
        assert events[0].transcript == "hello"

    @pytest.mark.asyncio
    async def test_unexpected_disconnect_raises(self):
        """An unexpected WebSocket close raises DeepgramConnectionError."""
        from websockets.exceptions import ConnectionClosedError
        from websockets.frames import Close

        client = DeepgramSTTClient(api_key="test-key")
        mock_ws = _AsyncWSIterRaise(ConnectionClosedError(Close(1006, "abnormal"), None))
        client._ws = mock_ws

        with pytest.raises(DeepgramConnectionError, match="unexpectedly"):
            async for _ in client.receive_transcripts():
                pass

    @pytest.mark.asyncio
    async def test_close_sends_empty_bytes_and_closes(self):
        """close() sends an empty-byte message and closes the WebSocket."""
        client = DeepgramSTTClient(api_key="test-key")
        mock_ws = AsyncMock()
        client._ws = mock_ws

        await client.close()

        mock_ws.send.assert_awaited_once_with(b"")
        mock_ws.close.assert_awaited_once()
        assert client._ws is None
        assert client._closed is True

    @pytest.mark.asyncio
    async def test_connect_after_close_raises(self):
        """Cannot reconnect after close(); must create a new client."""
        client = DeepgramSTTClient(api_key="test-key")
        client._closed = True

        with pytest.raises(DeepgramClosedError):
            await client.connect()


class TestParseResponse:
    """Tests for the static _parse_response helper."""

    def test_valid_result(self):
        msg = json.loads(_make_result_msg("test", is_final=True, speech_final=True, confidence=0.95))
        event = DeepgramSTTClient._parse_response(msg)
        assert event is not None
        assert event.transcript == "test"
        assert event.is_final is True
        assert event.speech_final is True
        assert event.confidence == 0.95

    def test_non_result_returns_none(self):
        msg = {"type": "Metadata", "request_id": "abc"}
        assert DeepgramSTTClient._parse_response(msg) is None

    def test_empty_alternatives_returns_none(self):
        msg = {"type": "Results", "channel": {"alternatives": []}}
        assert DeepgramSTTClient._parse_response(msg) is None

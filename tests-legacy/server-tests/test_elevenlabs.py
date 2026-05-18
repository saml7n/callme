"""Unit tests for ElevenLabs TTS client — all HTTP calls mocked."""

import pytest
import httpx

from app.tts.elevenlabs import (
    ElevenLabsTTSClient,
    TTSAuthError,
    TTSRateLimitError,
    TTSEmptyTextError,
    TTSError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_AUDIO = b"\xff" * 1600  # 200ms of μ-law silence at 8kHz


def _make_client(**kwargs) -> ElevenLabsTTSClient:
    """Create a client with a fake API key."""
    defaults = {"api_key": "fake-key", "voice_id": "test-voice"}
    defaults.update(kwargs)
    return ElevenLabsTTSClient(**defaults)


def _mock_transport(status: int = 200, content: bytes = FAKE_AUDIO, headers: dict | None = None):
    """Return an httpx transport that returns a fixed response."""
    _headers = {"request-id": "req_123"}
    if headers:
        _headers.update(headers)

    async def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=content, headers=_headers)

    return httpx.MockTransport(_handler)


# ---------------------------------------------------------------------------
# synthesize (non-streaming)
# ---------------------------------------------------------------------------


class TestSynthesize:
    async def test_returns_audio_bytes(self):
        client = _make_client()
        client._client = httpx.AsyncClient(
            transport=_mock_transport(), base_url="https://api.elevenlabs.io/v1"
        )
        audio = await client.synthesize("Hello")
        assert audio == FAKE_AUDIO
        assert len(audio) == 1600

    async def test_request_url_contains_output_format(self):
        """Verify the URL includes ulaw_8000 output format."""
        captured_requests: list[httpx.Request] = []

        async def _handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(200, content=FAKE_AUDIO, headers={"request-id": "r1"})

        client = _make_client()
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(_handler), base_url="https://api.elevenlabs.io/v1"
        )
        await client.synthesize("Hello")

        assert len(captured_requests) == 1
        url = str(captured_requests[0].url)
        assert "output_format=ulaw_8000" in url
        assert "optimize_streaming_latency=3" in url

    async def test_request_body_contains_model_id(self):
        """Verify the body includes model_id."""
        import json

        captured_bodies: list[dict] = []

        async def _handler(request: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(request.content))
            return httpx.Response(200, content=FAKE_AUDIO, headers={"request-id": "r1"})

        client = _make_client()
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(_handler), base_url="https://api.elevenlabs.io/v1"
        )
        await client.synthesize("Hello world")

        assert len(captured_bodies) == 1
        assert captured_bodies[0]["text"] == "Hello world"
        assert captured_bodies[0]["model_id"] == "eleven_flash_v2_5"

    async def test_auth_failure_raises(self):
        client = _make_client()
        client._client = httpx.AsyncClient(
            transport=_mock_transport(status=401, content=b'{"detail":"Unauthorized"}'),
            base_url="https://api.elevenlabs.io/v1",
        )
        with pytest.raises(TTSAuthError, match="401"):
            await client.synthesize("Hello")

    async def test_rate_limit_raises(self):
        client = _make_client()
        client._client = httpx.AsyncClient(
            transport=_mock_transport(status=429, content=b'{"detail":"Rate limited"}'),
            base_url="https://api.elevenlabs.io/v1",
        )
        with pytest.raises(TTSRateLimitError, match="429"):
            await client.synthesize("Hello")

    async def test_server_error_raises(self):
        client = _make_client()
        client._client = httpx.AsyncClient(
            transport=_mock_transport(status=500, content=b"Internal server error"),
            base_url="https://api.elevenlabs.io/v1",
        )
        with pytest.raises(TTSError, match="500"):
            await client.synthesize("Hello")

    async def test_empty_text_raises(self):
        client = _make_client()
        with pytest.raises(TTSEmptyTextError, match="empty"):
            await client.synthesize("")

    async def test_whitespace_only_text_raises(self):
        client = _make_client()
        with pytest.raises(TTSEmptyTextError, match="empty"):
            await client.synthesize("   ")

    async def test_previous_request_ids_stitching(self):
        """After multiple calls, previous_request_ids are sent for continuity."""
        import json

        captured_bodies: list[dict] = []

        async def _handler(request: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(request.content))
            return httpx.Response(200, content=FAKE_AUDIO, headers={"request-id": f"r{len(captured_bodies)}"})

        client = _make_client()
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(_handler), base_url="https://api.elevenlabs.io/v1"
        )

        await client.synthesize("Sentence one.")
        await client.synthesize("Sentence two.")

        # First call: no previous IDs
        assert "previous_request_ids" not in captured_bodies[0]
        # Second call: has previous ID from first call
        assert captured_bodies[1]["previous_request_ids"] == ["r1"]


# ---------------------------------------------------------------------------
# synthesize_stream (streaming)
# ---------------------------------------------------------------------------


class TestSynthesizeStream:
    async def test_yields_chunks(self):
        """Streaming variant yields multiple chunks."""
        chunk1 = b"\xff" * 512
        chunk2 = b"\xff" * 512
        all_audio = chunk1 + chunk2

        async def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=all_audio, headers={"request-id": "r1"})

        client = _make_client()
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(_handler), base_url="https://api.elevenlabs.io/v1"
        )

        chunks = []
        async for chunk in client.synthesize_stream("Hello"):
            chunks.append(chunk)

        assert len(chunks) >= 1
        assert b"".join(chunks) == all_audio

    async def test_stream_url_contains_stream_path(self):
        """Streaming uses the /stream endpoint."""
        captured_requests: list[httpx.Request] = []

        async def _handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(200, content=FAKE_AUDIO, headers={"request-id": "r1"})

        client = _make_client()
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(_handler), base_url="https://api.elevenlabs.io/v1"
        )

        async for _ in client.synthesize_stream("Hello"):
            pass

        assert len(captured_requests) == 1
        url = str(captured_requests[0].url)
        assert "/stream" in url
        assert "output_format=ulaw_8000" in url

    async def test_stream_auth_failure_raises(self):
        client = _make_client()
        client._client = httpx.AsyncClient(
            transport=_mock_transport(status=401, content=b'{"detail":"Unauthorized"}'),
            base_url="https://api.elevenlabs.io/v1",
        )
        with pytest.raises(TTSAuthError, match="401"):
            async for _ in client.synthesize_stream("Hello"):
                pass

    async def test_stream_empty_text_raises(self):
        client = _make_client()
        with pytest.raises(TTSEmptyTextError, match="empty"):
            async for _ in client.synthesize_stream(""):
                pass


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    async def test_close_succeeds(self):
        client = _make_client()
        client._client = httpx.AsyncClient(
            transport=_mock_transport(), base_url="https://api.elevenlabs.io/v1"
        )
        await client.close()  # Should not raise

"""Deepgram streaming speech-to-text client.

Connects to Deepgram's real-time WebSocket STT endpoint and provides
an async interface for sending audio and receiving transcript events.

Reference: https://developers.deepgram.com/docs/getting-started-with-live-streaming-audio
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncGenerator

import websockets
import websockets.asyncio.client
from websockets.exceptions import ConnectionClosed, InvalidStatus

from app.credentials import get_deepgram_api_key

logger = logging.getLogger(__name__)

DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"


class DeepgramError(Exception):
    """Base exception for Deepgram client errors."""


class DeepgramAuthError(DeepgramError):
    """Raised when Deepgram rejects the API key."""


class DeepgramConnectionError(DeepgramError):
    """Raised when the WebSocket connection fails or drops unexpectedly."""


class DeepgramClosedError(DeepgramError):
    """Raised when trying to use a closed client."""


@dataclass
class TranscriptEvent:
    """A single transcript result from Deepgram."""

    transcript: str
    is_final: bool
    speech_final: bool
    confidence: float
    start: float  # seconds into the audio
    duration: float  # seconds


class DeepgramSTTClient:
    """Async Deepgram streaming STT client.

    Usage::

        client = DeepgramSTTClient()
        await client.connect()

        # In one task — send audio:
        await client.send_audio(chunk)

        # In another task — receive transcripts:
        async for event in client.receive_transcripts():
            print(event.transcript, event.is_final, event.speech_final)

        await client.close()
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "nova-3",
        encoding: str = "mulaw",
        sample_rate: int = 8000,
        channels: int = 1,
        punctuate: bool = True,
        endpointing: int = 300,
        smart_format: bool = True,
        interim_results: bool = True,
    ) -> None:
        self._api_key = api_key or get_deepgram_api_key()
        self._model = model
        self._encoding = encoding
        self._sample_rate = sample_rate
        self._channels = channels
        self._punctuate = punctuate
        self._endpointing = endpointing
        self._smart_format = smart_format
        self._interim_results = interim_results
        self._ws: websockets.asyncio.client.ClientConnection | None = None
        self._closed = False

    def _build_url(self) -> str:
        params = (
            f"model={self._model}"
            f"&encoding={self._encoding}"
            f"&sample_rate={self._sample_rate}"
            f"&channels={self._channels}"
            f"&punctuate={str(self._punctuate).lower()}"
            f"&endpointing={self._endpointing}"
            f"&smart_format={str(self._smart_format).lower()}"
            f"&interim_results={str(self._interim_results).lower()}"
        )
        return f"{DEEPGRAM_WS_URL}?{params}"

    async def connect(self) -> None:
        """Open a WebSocket connection to Deepgram's streaming STT endpoint."""
        if self._closed:
            raise DeepgramClosedError("Client has been closed; create a new instance.")

        url = self._build_url()
        headers = {"Authorization": f"Token {self._api_key}"}

        try:
            self._ws = await websockets.asyncio.client.connect(
                url,
                additional_headers=headers,
            )
        except InvalidStatus as exc:
            status = exc.response.status_code
            if status == 401:
                raise DeepgramAuthError("Invalid Deepgram API key (401 Unauthorized).") from exc
            raise DeepgramConnectionError(
                f"Deepgram connection failed with status {status}"
            ) from exc
        except Exception as exc:
            raise DeepgramConnectionError(f"Failed to connect to Deepgram: {exc}") from exc

        logger.info("Connected to Deepgram STT (model=%s, encoding=%s)", self._model, self._encoding)

    async def send_audio(self, chunk: bytes) -> None:
        """Send a raw audio chunk to Deepgram."""
        if self._closed:
            raise DeepgramClosedError("Cannot send audio on a closed client.")
        if self._ws is None:
            raise DeepgramConnectionError("Not connected. Call connect() first.")

        await self._ws.send(chunk)

    async def receive_transcripts(self) -> AsyncGenerator[TranscriptEvent, None]:
        """Async generator that yields TranscriptEvent objects as they arrive."""
        if self._ws is None:
            raise DeepgramConnectionError("Not connected. Call connect() first.")

        try:
            async for raw in self._ws:
                msg: dict[str, Any] = json.loads(raw)
                event = self._parse_response(msg)
                if event is not None:
                    yield event
        except ConnectionClosed as exc:
            if not self._closed:
                raise DeepgramConnectionError(
                    f"Deepgram WebSocket disconnected unexpectedly: {exc}"
                ) from exc

    @staticmethod
    def _parse_response(msg: dict[str, Any]) -> TranscriptEvent | None:
        """Parse a Deepgram JSON response into a TranscriptEvent (or None if not a result)."""
        msg_type = msg.get("type")
        if msg_type != "Results":
            return None

        channel = msg.get("channel", {})
        alternatives = channel.get("alternatives", [])
        if not alternatives:
            return None

        best = alternatives[0]
        transcript = best.get("transcript", "")

        return TranscriptEvent(
            transcript=transcript,
            is_final=msg.get("is_final", False),
            speech_final=msg.get("speech_final", False),
            confidence=best.get("confidence", 0.0),
            start=msg.get("start", 0.0),
            duration=msg.get("duration", 0.0),
        )

    async def close(self) -> None:
        """Close the Deepgram WebSocket connection gracefully."""
        self._closed = True
        if self._ws is not None:
            try:
                # Send a close-stream message (empty byte payload) per Deepgram docs
                await self._ws.send(b"")
                await self._ws.close()
            except Exception:
                pass  # Best-effort close
            finally:
                self._ws = None
            logger.info("Deepgram STT connection closed.")

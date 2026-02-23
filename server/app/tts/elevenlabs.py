"""ElevenLabs TTS client with streaming and non-streaming synthesis.

Outputs μ-law 8kHz audio suitable for Twilio Media Streams.

Reference: https://elevenlabs.io/docs/api-reference/text-to-speech
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

import httpx

from app.config import settings
from app.credentials import get_elevenlabs_api_key

logger = logging.getLogger(__name__)

BASE_URL = "https://api.elevenlabs.io/v1"


class TTSError(Exception):
    """Base exception for TTS client errors."""


class TTSAuthError(TTSError):
    """Raised when the API key is invalid."""


class TTSRateLimitError(TTSError):
    """Raised when rate-limited by ElevenLabs."""


class TTSEmptyTextError(TTSError):
    """Raised when empty text is passed for synthesis."""


class ElevenLabsTTSClient:
    """Async ElevenLabs TTS client producing μ-law 8kHz audio for Twilio.

    Usage::

        client = ElevenLabsTTSClient()
        audio = await client.synthesize("Hello, how can I help?")

        async for chunk in client.synthesize_stream("Hello!"):
            send_to_twilio(chunk)
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        voice_id: str | None = None,
        model_id: str = "eleven_flash_v2_5",
        output_format: str = "ulaw_8000",
        optimize_streaming_latency: int = 3,
    ) -> None:
        self._api_key = api_key or get_elevenlabs_api_key()
        self._voice_id = voice_id or settings.elevenlabs_voice_id
        self._model_id = model_id
        self._output_format = output_format
        self._optimize_streaming_latency = optimize_streaming_latency
        self._previous_request_ids: list[str] = []
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def synthesize(self, text: str) -> bytes:
        """Synthesize text to complete μ-law audio bytes.

        Args:
            text: The text to convert to speech.

        Returns:
            Raw μ-law 8kHz audio bytes.

        Raises:
            TTSEmptyTextError: If text is empty.
            TTSAuthError: If the API key is invalid.
            TTSRateLimitError: If rate-limited.
            TTSError: On other API errors.
        """
        if not text or not text.strip():
            raise TTSEmptyTextError("Cannot synthesize empty text")

        url = self._tts_url()
        body = self._build_body(text)

        response = await self._client.post(url, json=body)
        self._handle_error(response)

        request_id = response.headers.get("request-id")
        if request_id:
            self._previous_request_ids.append(request_id)

        audio = response.content
        logger.info(
            "Synthesized %d bytes of audio for %d chars of text",
            len(audio),
            len(text),
        )
        return audio

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """Stream μ-law audio chunks as they become available.

        Args:
            text: The text to convert to speech.

        Yields:
            Raw μ-law 8kHz audio byte chunks.

        Raises:
            TTSEmptyTextError: If text is empty.
            TTSAuthError: If the API key is invalid.
            TTSRateLimitError: If rate-limited.
            TTSError: On other API errors.
        """
        if not text or not text.strip():
            raise TTSEmptyTextError("Cannot synthesize empty text")

        url = self._tts_stream_url()
        body = self._build_body(text)

        async with self._client.stream("POST", url, json=body) as response:
            if response.status_code != 200:
                # Need to read the body for error details
                await response.aread()
                self._handle_error(response)

            request_id = response.headers.get("request-id")
            if request_id:
                self._previous_request_ids.append(request_id)

            chunk_count = 0
            total_bytes = 0
            async for chunk in response.aiter_bytes(chunk_size=1024):
                chunk_count += 1
                total_bytes += len(chunk)
                yield chunk

            logger.info(
                "Streamed %d chunks (%d bytes) for %d chars of text",
                chunk_count,
                total_bytes,
                len(text),
            )

    def _tts_url(self) -> str:
        """Build the non-streaming TTS endpoint URL."""
        return (
            f"/text-to-speech/{self._voice_id}"
            f"?output_format={self._output_format}"
            f"&optimize_streaming_latency={self._optimize_streaming_latency}"
        )

    def _tts_stream_url(self) -> str:
        """Build the streaming TTS endpoint URL."""
        return (
            f"/text-to-speech/{self._voice_id}/stream"
            f"?output_format={self._output_format}"
            f"&optimize_streaming_latency={self._optimize_streaming_latency}"
        )

    def _build_body(self, text: str) -> dict:
        """Build the request body for the TTS API."""
        body: dict = {
            "text": text,
            "model_id": self._model_id,
        }
        if self._previous_request_ids:
            # Send up to the last 3 request IDs for stitching continuity
            body["previous_request_ids"] = self._previous_request_ids[-3:]
        return body

    def _handle_error(self, response: httpx.Response) -> None:
        """Raise appropriate exceptions for error responses."""
        if response.status_code == 200:
            return

        status = response.status_code
        try:
            detail = response.json()
        except Exception:
            detail = response.text

        if status == 401:
            raise TTSAuthError(f"Invalid ElevenLabs API key (401): {detail}")
        if status == 429:
            raise TTSRateLimitError(f"ElevenLabs rate limit (429): {detail}")
        raise TTSError(f"ElevenLabs API error ({status}): {detail}")

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

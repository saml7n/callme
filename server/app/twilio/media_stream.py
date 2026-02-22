"""Twilio bidirectional media-stream WebSocket handler.

Twilio sends JSON messages over the WebSocket with the following event types:
- connected  — WebSocket connection established
- start      — stream metadata (streamSid, callSid, codec, etc.)
- media      — base64-encoded μ-law audio chunk
- stop       — stream is ending
- mark       — a previously-sent mark event has been played

Reference: https://www.twilio.com/docs/voice/media-streams/websocket-messages
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.pipeline import CallPipeline

logger = logging.getLogger(__name__)

# Default workflow JSON — loaded once at import time.
# Set to None to fall back to Story 6 hardcoded prompt.
_WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent / "schemas" / "examples" / "simple_receptionist.json"
)
_DEFAULT_WORKFLOW: dict[str, Any] | None = None
if _WORKFLOW_PATH.exists():
    _DEFAULT_WORKFLOW = json.loads(_WORKFLOW_PATH.read_text())
    logger.info("Loaded default workflow from %s", _WORKFLOW_PATH)

router = APIRouter(tags=["twilio"])


@dataclass
class MediaStreamState:
    """Tracks state for a single Twilio media stream."""

    stream_sid: str = ""
    call_sid: str = ""
    account_sid: str = ""
    codec: str = ""
    tracks: list[str] = field(default_factory=list)
    chunks_received: int = 0
    is_connected: bool = False


def parse_start_event(msg: dict[str, Any]) -> MediaStreamState:
    """Extract stream metadata from a Twilio 'start' event."""
    start = msg.get("start", {})
    return MediaStreamState(
        stream_sid=msg.get("streamSid", ""),
        call_sid=start.get("callSid", ""),
        account_sid=start.get("accountSid", ""),
        codec=start.get("mediaFormat", {}).get("encoding", ""),
        tracks=start.get("tracks", []),
        is_connected=True,
    )


def decode_media_payload(msg: dict[str, Any]) -> bytes:
    """Decode the base64 audio payload from a Twilio 'media' event."""
    payload = msg.get("media", {}).get("payload", "")
    return base64.b64decode(payload)


def build_outbound_media_message(stream_sid: str, audio: bytes) -> str:
    """Build a JSON message to send audio back to Twilio.

    The audio must be base64-encoded μ-law 8kHz mono.
    """
    return json.dumps(
        {
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": base64.b64encode(audio).decode("ascii")},
        }
    )


def build_clear_message(stream_sid: str) -> str:
    """Build a JSON 'clear' message to stop Twilio playback immediately."""
    return json.dumps({"event": "clear", "streamSid": stream_sid})


def build_mark_message(stream_sid: str, name: str) -> str:
    """Build a JSON 'mark' message so Twilio notifies us when playback reaches this point."""
    return json.dumps({"event": "mark", "streamSid": stream_sid, "mark": {"name": name}})


@router.websocket("/twilio/media-stream")
async def media_stream(ws: WebSocket) -> None:
    """Handle a bidirectional Twilio media stream WebSocket connection."""
    await ws.accept()
    state = MediaStreamState()
    pipeline: CallPipeline | None = None

    try:
        while True:
            raw = await ws.receive_text()
            msg: dict[str, Any] = json.loads(raw)
            event = msg.get("event", "")

            if event == "connected":
                logger.info("Twilio WebSocket connected (protocol=%s)", msg.get("protocol"))

            elif event == "start":
                state = parse_start_event(msg)
                logger.info(
                    "Stream started: streamSid=%s callSid=%s codec=%s tracks=%s",
                    state.stream_sid,
                    state.call_sid,
                    state.codec,
                    state.tracks,
                )
                # Start the full voice pipeline
                try:
                    pipeline = CallPipeline(
                        ws=ws,
                        stream_sid=state.stream_sid,
                        workflow=_DEFAULT_WORKFLOW,
                    )
                    await pipeline.start()
                    logger.info("CallPipeline started for call %s (workflow=%s)", state.call_sid, "yes" if _DEFAULT_WORKFLOW else "no")
                except Exception:
                    logger.exception("Failed to start CallPipeline")
                    pipeline = None

            elif event == "media":
                audio = decode_media_payload(msg)
                state.chunks_received += 1
                # Forward audio to pipeline (STT → LLM → TTS)
                if pipeline is not None:
                    try:
                        await pipeline.send_audio(audio)
                    except Exception:
                        logger.exception("Error sending audio to pipeline")

            elif event == "stop":
                logger.info(
                    "Stream stopped: streamSid=%s  chunks_received=%d",
                    state.stream_sid,
                    state.chunks_received,
                )
                break

            elif event == "mark":
                mark_name = msg.get("mark", {}).get("name", "")
                logger.debug("Mark reached: %s", mark_name)

            elif event == "dtmf":
                digit = msg.get("dtmf", {}).get("digit", "")
                logger.info("DTMF received: %s", digit)

            else:
                logger.warning("Unknown Twilio event: %s", event)

    except WebSocketDisconnect:
        logger.info(
            "Twilio WebSocket disconnected: streamSid=%s  chunks_received=%d",
            state.stream_sid,
            state.chunks_received,
        )
    finally:
        # Clean up pipeline
        if pipeline is not None:
            await pipeline.close()
        state.is_connected = False

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
from sqlmodel import Session, select

from app.db.call_logger import CallLogger
from app.db.models import Call, Workflow as WorkflowModel
from app.db.session import get_session
from app.events import event_bus
from app.pipeline import CallPipeline

logger = logging.getLogger(__name__)

# Fallback workflow JSON — loaded once from disk for when DB has no active workflow.
_WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent / "schemas" / "examples" / "reception_flow.json"
)
_FALLBACK_WORKFLOW: dict[str, Any] | None = None
if _WORKFLOW_PATH.exists():
    _FALLBACK_WORKFLOW = json.loads(_WORKFLOW_PATH.read_text())
    logger.info("Loaded fallback workflow from %s", _WORKFLOW_PATH)

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


def _load_active_workflow() -> tuple[dict[str, Any] | None, Any, str]:
    """Load the active workflow from the DB, with fallback to disk.

    Returns (workflow_dict, workflow_db_id, workflow_name).
    """
    try:
        session = next(get_session())
        db_wf = session.exec(
            select(WorkflowModel).where(WorkflowModel.is_active == True)  # noqa: E712
        ).first()
        if db_wf is not None:
            logger.info("Loaded active workflow from DB: %s (id=%s)", db_wf.name, db_wf.id)
            return db_wf.graph_json, db_wf.id, db_wf.name
    except Exception:
        logger.exception("Failed to load workflow from DB")

    if _FALLBACK_WORKFLOW is not None:
        logger.info("Using fallback workflow from disk")
        return _FALLBACK_WORKFLOW, None, "Fallback"
    return None, None, ""


def _create_call_record(
    call_sid: str,
    from_number: str,
    to_number: str,
    workflow_id: Any | None,
) -> Call | None:
    """Create a Call record in the database. Returns the Call or None on error."""
    try:
        session = next(get_session())
        call = Call(
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
            workflow_id=workflow_id,
        )
        session.add(call)
        session.commit()
        session.refresh(call)
        logger.info("Created call record %s for call_sid=%s", call.id, call_sid)
        return call
    except Exception:
        logger.exception("Failed to create call record")
        return None


@router.websocket("/twilio/media-stream")
async def media_stream(ws: WebSocket) -> None:
    """Handle a bidirectional Twilio media stream WebSocket connection."""
    await ws.accept()
    state = MediaStreamState()
    pipeline: CallPipeline | None = None
    call_id_str: str = ""

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
                    # Load active workflow from DB (falls back to disk)
                    workflow_dict, workflow_db_id, workflow_name = _load_active_workflow()

                    # Create a call record in the database
                    call_record = _create_call_record(
                        call_sid=state.call_sid,
                        from_number="",  # populated by Twilio webhook if needed
                        to_number="",
                        workflow_id=workflow_db_id,
                    )
                    call_logger = CallLogger(call_record.id) if call_record else None
                    call_id_str = str(call_record.id) if call_record else ""

                    # Register call with event bus for live dashboard
                    if call_id_str:
                        event_bus.register_call(
                            call_id=call_id_str,
                            call_sid=state.call_sid,
                            caller_number="",
                            workflow_name=workflow_name,
                        )

                    pipeline = CallPipeline(
                        ws=ws,
                        stream_sid=state.stream_sid,
                        call_sid=state.call_sid,
                        workflow=workflow_dict,
                        call_logger=call_logger,
                        call_id=call_id_str,
                    )
                    await pipeline.start()
                    logger.info("CallPipeline started for call %s (workflow=%s)", state.call_sid, "yes" if workflow_dict else "no")
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
        # Unregister call from event bus
        if call_id_str:
            event_bus.unregister_call(call_id_str)
        # Clean up pipeline
        if pipeline is not None:
            await pipeline.close()
        state.is_connected = False

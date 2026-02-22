"""Twilio incoming-call webhook — returns TwiML to open a bidirectional media stream."""

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.config import settings

router = APIRouter(prefix="/twilio", tags=["twilio"])


def build_twiml(stream_url: str) -> str:
    """Return TwiML XML that connects the call to a bidirectional WebSocket stream."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="{stream_url}" />'
        "</Connect>"
        "</Response>"
    )


@router.post("/incoming")
async def incoming_call(request: Request) -> Response:
    """Handle an inbound Twilio call.

    Returns TwiML instructing Twilio to open a bidirectional media stream
    back to our WebSocket endpoint.
    """
    public_url = settings.public_url.rstrip("/")
    # Convert http(s) to ws(s) for the WebSocket URL
    ws_url = public_url.replace("https://", "wss://").replace("http://", "ws://")
    stream_url = f"{ws_url}/twilio/media-stream"

    twiml = build_twiml(stream_url)
    return Response(content=twiml, media_type="application/xml")

"""Twilio incoming-call webhook — returns TwiML to open a bidirectional media stream.

Validates the X-Twilio-Signature header when twilio_auth_token is configured.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from twilio.request_validator import RequestValidator

from app.config import settings
from app.credentials import get_twilio_auth_token

logger = logging.getLogger(__name__)

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


def validate_twilio_signature(request_url: str, params: dict, signature: str) -> bool:
    """Validate X-Twilio-Signature using the configured auth token.

    Returns True if validation passes or if no auth token is configured
    (skip validation in development).
    """
    auth_token = get_twilio_auth_token()
    if not auth_token:
        logger.debug("No twilio_auth_token configured — skipping signature validation")
        return True
    validator = RequestValidator(auth_token)
    return validator.validate(request_url, params, signature)


@router.post("/incoming")
async def incoming_call(request: Request) -> Response:
    """Handle an inbound Twilio call.

    Returns TwiML instructing Twilio to open a bidirectional media stream
    back to our WebSocket endpoint.
    """
    # Validate Twilio signature
    signature = request.headers.get("X-Twilio-Signature", "")
    form_data = dict(await request.form())
    request_url = str(request.url)

    if not validate_twilio_signature(request_url, form_data, signature):
        logger.warning("Invalid Twilio signature on /twilio/incoming")
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    public_url = settings.public_url.rstrip("/")
    # Convert http(s) to ws(s) for the WebSocket URL
    ws_url = public_url.replace("https://", "wss://").replace("http://", "ws://")
    stream_url = f"{ws_url}/twilio/media-stream"

    twiml = build_twiml(stream_url)
    return Response(content=twiml, media_type="application/xml")

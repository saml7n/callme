"""Twilio incoming-call webhook — returns TwiML to open a bidirectional media stream.

Validates the X-Twilio-Signature header when twilio_auth_token is configured.
Routes calls based on the dialled number (``To``) to the correct user's workflow.
"""

import logging
from html import escape as html_escape
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from twilio.request_validator import RequestValidator

from credentials import get_twilio_auth_token
from public_url import get_public_url

logger = logging.getLogger(__name__)

router = APIRouter(tags=["twilio"])


def build_twiml(stream_url: str) -> str:
    """Return TwiML XML that connects the call to a bidirectional WebSocket stream."""
    safe_url = html_escape(stream_url)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="{safe_url}" />'
        "</Connect>"
        "</Response>"
    )


def _public_request_url(request: Request) -> str:
    """Rebuild the public URL Twilio signed against.

    Behind a reverse proxy (nginx/Fly), ``request.url`` is the internal
    URL (e.g. ``http://127.0.0.1:3000/...``). Twilio signs against the
    *public* webhook URL, so we must reconstruct it for validation.
    """
    public_url = get_public_url().rstrip("/")
    request_url = f"{public_url}{request.url.path}"
    if request.url.query:
        request_url = f"{request_url}?{request.url.query}"
    return request_url


async def twilio_auth(request: Request) -> None:
    """FastAPI dependency — validate the X-Twilio-Signature header (HMAC-SHA1).

    Skips validation entirely when no ``twilio_auth_token`` is configured —
    useful in dev where the token isn't yet wired. Raises 403 on mismatch.
    The dependency reads the request body via ``request.form()``; FastAPI
    caches the form so the handler can re-await it without consuming twice.
    """
    auth_token = get_twilio_auth_token()
    if not auth_token:
        logger.debug("No twilio_auth_token configured — skipping signature validation")
        return

    signature = request.headers.get("X-Twilio-Signature", "")
    form_data = dict(await request.form())
    request_url = _public_request_url(request)

    validator = RequestValidator(auth_token)
    if not validator.validate(request_url, form_data, signature):
        logger.warning("Invalid Twilio signature on %s (url=%s)", request.url.path, request_url)
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


@router.post("")
async def incoming_call(
    request: Request,
    _: None = Depends(twilio_auth),
) -> Response:
    """Handle an inbound Twilio call.

    Returns TwiML instructing Twilio to open a bidirectional media stream
    back to our WebSocket endpoint. The dialled number (``To``) and caller
    (``From``) are forwarded as query parameters so the media-stream handler
    can route calls to the correct user's workflow.
    """
    form_data = dict(await request.form())
    public_url = get_public_url().rstrip("/")
    # Convert http(s) to ws(s) for the WebSocket URL
    ws_url = public_url.replace("https://", "wss://").replace("http://", "ws://")

    # Pass call metadata as query params so the media stream can route correctly
    to_number = form_data.get("To", "")
    from_number = form_data.get("From", "")
    qs = urlencode({"to": to_number, "from": from_number})
    stream_url = f"{ws_url}/twilio/media-stream?{qs}"

    twiml = build_twiml(stream_url)
    return Response(content=twiml, media_type="application/xml")

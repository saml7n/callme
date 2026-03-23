"""Live calls WebSocket and transfer API.

- ``GET /ws/calls/live``  — WebSocket that streams real-time call events.
- ``GET /api/calls/live``  — REST snapshot of currently active calls.
- ``POST /api/calls/{call_id}/transfer`` — Transfer an active call to the
  admin's registered phone number via Twilio.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from app.auth import get_current_user, require_auth
from app.credentials import (
    get_admin_phone_number,
    get_twilio_account_sid,
    get_twilio_api_key_secret,
    get_twilio_api_key_sid,
    get_twilio_auth_token,
)
from app.db.models import User
from app.events import event_bus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live"])

# ---------------------------------------------------------------------------
# WebSocket — live event stream
# ---------------------------------------------------------------------------


@router.websocket("/ws/calls/live")
async def live_events_ws(ws: WebSocket) -> None:
    """Stream live call events to the dashboard.

    The client receives JSON messages for: ``call_started``, ``transcript``,
    ``node_transition``, ``call_ended``, ``transfer_started``.

    Requires a ``token`` query parameter containing a valid JWT or API key.
    Invalid tokens are rejected with ``ws.close(code=4001)``.

    On connect, the server immediately sends the current active calls as
    a ``snapshot`` message so the UI can render ongoing calls.
    """
    # Validate token before accepting the connection
    token = ws.query_params.get("token", "")
    if not token:
        await ws.close(code=4001, reason="Unauthorized")
        return

    from app.auth import decode_jwt, get_api_key
    import secrets as _secrets

    # Check API key first
    api_key = get_api_key()
    is_valid = _secrets.compare_digest(token, api_key)

    # If not API key, try JWT
    if not is_valid:
        try:
            decode_jwt(token)
            is_valid = True
        except Exception:
            is_valid = False

    if not is_valid:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()
    queue = event_bus.subscribe()

    try:
        # Send current active calls snapshot
        active = event_bus.get_active_calls()
        await ws.send_text(json.dumps({"type": "snapshot", "calls": active}))

        # Stream events
        while True:
            event = await queue.get()
            await ws.send_text(json.dumps(event))
    except WebSocketDisconnect:
        logger.debug("Live WS client disconnected")
    except Exception:
        logger.debug("Live WS error", exc_info=True)
    finally:
        event_bus.unsubscribe(queue)


# ---------------------------------------------------------------------------
# Transfer
# ---------------------------------------------------------------------------


def _mask_phone(number: str) -> str:
    """Mask a phone number for display: +44•••••890."""
    if len(number) <= 6:
        return number
    return number[:3] + "•" * (len(number) - 6) + number[-3:]


@router.post("/api/calls/{call_id}/transfer", dependencies=[Depends(require_auth)])
async def transfer_call(
    call_id: UUID,
    user: User = Depends(get_current_user),
) -> dict:
    """Transfer an active call to the admin's registered phone number.

    Uses Twilio REST API to update the call with <Dial> TwiML pointing
    to ``admin_phone_number`` from the settings store.
    """
    call_id_str = str(call_id)

    if not event_bus.is_active(call_id_str):
        raise HTTPException(status_code=404, detail="Call not active or already ended")

    admin_number = get_admin_phone_number(user_id=user.id)
    if not admin_number:
        raise HTTPException(
            status_code=422,
            detail="No admin phone number configured. Set it in Setup → Phone Number.",
        )

    call_sid = event_bus.get_call_sid(call_id_str)
    if not call_sid:
        raise HTTPException(status_code=404, detail="Call SID not available")

    # Build Twilio credentials — prefer API Key, fall back to Auth Token
    account_sid = get_twilio_account_sid(user_id=user.id)
    api_key_sid = get_twilio_api_key_sid(user_id=user.id)
    api_key_secret = get_twilio_api_key_secret(user_id=user.id)
    auth_token = get_twilio_auth_token(user_id=user.id)

    if api_key_sid and api_key_secret:
        auth_pair = (api_key_sid, api_key_secret)
    elif auth_token:
        auth_pair = (account_sid, auth_token)
    else:
        auth_pair = None

    if not account_sid or not auth_pair:
        raise HTTPException(status_code=500, detail="Twilio credentials not configured")

    # Build TwiML to dial the admin
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        '<Say voice="alice">One moment please, I\'m transferring you now.</Say>'
        f"<Dial>{admin_number}</Dial>"
        "</Response>"
    )

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls/{call_sid}.json"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                data={"Twiml": twiml},
                auth=auth_pair,
            )
            if resp.status_code >= 300:
                logger.error("Twilio transfer failed (%d): %s", resp.status_code, resp.text)
                raise HTTPException(status_code=502, detail="Twilio transfer failed")
    except httpx.HTTPError as exc:
        logger.exception("HTTP error transferring call")
        raise HTTPException(status_code=502, detail=str(exc))

    # Broadcast transfer event
    import time
    event_bus.emit({
        "type": "transfer_started",
        "call_id": call_id_str,
        "target_number": _mask_phone(admin_number),
        "timestamp": time.time(),
    })

    logger.info("Transferred call %s → %s", call_id_str, _mask_phone(admin_number))

    return {
        "ok": True,
        "call_id": call_id_str,
        "transferred_to": _mask_phone(admin_number),
    }

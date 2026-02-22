"""Tests for the Twilio incoming-call webhook (TwiML endpoint)."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_incoming_returns_twiml_xml(monkeypatch):
    """POST /twilio/incoming returns valid TwiML with a <Connect><Stream> element."""
    monkeypatch.setenv("PUBLIC_URL", "https://abc123.ngrok.io")

    # Re-import settings so the monkeypatched env var takes effect
    from app.config import Settings

    monkeypatch.setattr("app.twilio.webhook.settings", Settings())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/twilio/incoming")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"

    body = response.text
    assert "<Response>" in body
    assert "<Connect>" in body
    assert "<Stream" in body
    assert 'url="wss://abc123.ngrok.io/twilio/media-stream"' in body


@pytest.mark.asyncio
async def test_incoming_converts_http_to_ws(monkeypatch):
    """HTTP public URLs are converted to ws:// (not wss://)."""
    monkeypatch.setenv("PUBLIC_URL", "http://localhost:3000")

    from app.config import Settings

    monkeypatch.setattr("app.twilio.webhook.settings", Settings())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/twilio/incoming")

    assert 'url="ws://localhost:3000/twilio/media-stream"' in response.text

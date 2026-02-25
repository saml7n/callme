"""Tests for the Twilio incoming-call webhook (TwiML endpoint)."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_incoming_returns_twiml_xml(monkeypatch):
    """POST /twilio/incoming returns valid TwiML with a <Connect><Stream> element."""
    monkeypatch.setattr("app.twilio.webhook.get_public_url", lambda: "https://abc123.ngrok.io")
    # Ensure signature validation is skipped (no auth token)
    monkeypatch.setattr("app.twilio.webhook.get_twilio_auth_token", lambda: "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/twilio/incoming")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"

    body = response.text
    assert "<Response>" in body
    assert "<Connect>" in body
    assert "<Stream" in body
    assert 'url="wss://abc123.ngrok.io/twilio/media-stream?' in body


@pytest.mark.asyncio
async def test_incoming_converts_http_to_ws(monkeypatch):
    """HTTP public URLs are converted to ws:// (not wss://)."""
    monkeypatch.setattr("app.twilio.webhook.get_public_url", lambda: "http://localhost:3000")
    # Ensure signature validation is skipped (no auth token)
    monkeypatch.setattr("app.twilio.webhook.get_twilio_auth_token", lambda: "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/twilio/incoming")

    assert 'url="ws://localhost:3000/twilio/media-stream?' in response.text

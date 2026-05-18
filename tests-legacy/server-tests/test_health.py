"""Tests for the /health endpoint."""

import os
from unittest.mock import patch, AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

TEST_API_KEY = "test-api-key-for-health-tests"


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """Set a known API key so Bearer auth works in detail tests."""
    monkeypatch.setattr("app.auth._api_key", TEST_API_KEY)
    monkeypatch.setattr("app.auth.JWT_SECRET_KEY", TEST_API_KEY)
    monkeypatch.setattr("app.auth.settings.callme_api_key", TEST_API_KEY)


@pytest.mark.asyncio
async def test_health_liveness():
    """Health endpoint without ?detail returns minimal {"status": "ok"} only."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "ok"}
    # Story 26: detailed info moved to ?detail=true (requires auth)
    assert "public_url" not in data
    assert "services" not in data


@pytest.mark.asyncio
async def test_health_detail_requires_auth():
    """Health endpoint with ?detail=true returns 401 without Bearer token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health?detail=true")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_detail_returns_service_status():
    """Health endpoint with ?detail=true + valid token returns full service info."""
    mock_services = {
        "twilio": {"status": "ok"},
        "deepgram": {"status": "ok"},
        "elevenlabs": {"status": "ok"},
        "openai": {"status": "ok"},
    }
    with patch("app.health.check_all_services", new_callable=AsyncMock, return_value=mock_services):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {TEST_API_KEY}"},
        ) as client:
            response = await client.get("/health?detail=true")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "services" in data
    assert "public_url" in data
    assert "demo_mode" in data
    assert data["services"]["twilio"]["status"] == "ok"


@pytest.mark.asyncio
async def test_health_degraded_when_service_down():
    """Health endpoint returns 'degraded' when any service is not ok."""
    mock_services = {
        "twilio": {"status": "ok"},
        "deepgram": {"status": "error", "detail": "timeout"},
        "elevenlabs": {"status": "ok"},
        "openai": {"status": "not_configured"},
    }
    with patch("app.health.check_all_services", new_callable=AsyncMock, return_value=mock_services):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {TEST_API_KEY}"},
        ) as client:
            response = await client.get("/health?detail=true")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_demo_mode_flag():
    """Health detail endpoint reflects SEED_DEMO env var in demo_mode field."""
    mock_services = {
        "twilio": {"status": "ok"},
        "deepgram": {"status": "ok"},
        "elevenlabs": {"status": "ok"},
        "openai": {"status": "ok"},
    }
    with patch("app.health.check_all_services", new_callable=AsyncMock, return_value=mock_services):
        # Demo mode ON
        with patch.dict(os.environ, {"SEED_DEMO": "true"}):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                headers={"Authorization": f"Bearer {TEST_API_KEY}"},
            ) as client:
                response = await client.get("/health?detail=true")
            assert response.json()["demo_mode"] is True

        # Demo mode OFF
        with patch.dict(os.environ, {"SEED_DEMO": ""}, clear=False):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                headers={"Authorization": f"Bearer {TEST_API_KEY}"},
            ) as client:
                response = await client.get("/health?detail=true")
            assert response.json()["demo_mode"] is False

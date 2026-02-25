"""Tests for the /health endpoint."""

import os
from unittest.mock import patch, AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_liveness():
    """Health endpoint without ?detail returns fast liveness (no external calls)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "public_url" in data
    assert "demo_mode" in data
    assert "services" not in data


@pytest.mark.asyncio
async def test_health_detail_returns_service_status():
    """Health endpoint with ?detail=true returns full service connectivity."""
    mock_services = {
        "twilio": {"status": "ok"},
        "deepgram": {"status": "ok"},
        "elevenlabs": {"status": "ok"},
        "openai": {"status": "ok"},
    }
    with patch("app.health.check_all_services", new_callable=AsyncMock, return_value=mock_services):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
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
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health?detail=true")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_demo_mode_flag():
    """Health endpoint reflects SEED_DEMO env var in demo_mode field."""
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
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/health")
            assert response.json()["demo_mode"] is True

        # Demo mode OFF
        with patch.dict(os.environ, {"SEED_DEMO": ""}, clear=False):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/health")
            assert response.json()["demo_mode"] is False

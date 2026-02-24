"""Tests for PUBLIC_URL auto-detection (Story 24)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

import app.public_url as pub_mod


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear the cached URL between tests."""
    pub_mod._resolved_url = ""
    yield
    pub_mod._resolved_url = ""


@pytest.mark.asyncio
async def test_resolve_from_env():
    """When PUBLIC_URL env var is set, that value is used directly."""
    with patch.object(pub_mod.settings, "public_url", "https://example.com/"):
        result = await pub_mod.resolve_public_url()
    assert result == "https://example.com"
    assert pub_mod.get_public_url() == "https://example.com"


@pytest.mark.asyncio
async def test_resolve_from_ngrok_api():
    """When PUBLIC_URL is empty but ngrok API returns tunnels, use the https tunnel."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "tunnels": [
            {"public_url": "http://abc123.ngrok.io"},
            {"public_url": "https://abc123.ngrok.io"},
        ]
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(pub_mod.settings, "public_url", ""),
        patch("app.public_url.httpx.AsyncClient", return_value=mock_client),
        patch.dict("os.environ", {"NGROK_HOST": "tunnels"}),
    ):
        result = await pub_mod.resolve_public_url()

    assert result == "https://abc123.ngrok.io"


@pytest.mark.asyncio
async def test_resolve_fallback_to_localhost():
    """When no env var and ngrok is unavailable, fall back to localhost."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(pub_mod.settings, "public_url", ""),
        patch("app.public_url.httpx.AsyncClient", return_value=mock_client),
        patch.object(pub_mod.settings, "port", 3000),
    ):
        result = await pub_mod.resolve_public_url()

    assert result == "http://localhost:3000"


def test_get_public_url_returns_cached():
    """get_public_url() returns the last resolved value."""
    pub_mod._resolved_url = "https://cached.example.com"
    assert pub_mod.get_public_url() == "https://cached.example.com"


def test_get_public_url_empty_before_resolve():
    """get_public_url() returns empty string before resolve_public_url is called."""
    assert pub_mod.get_public_url() == ""

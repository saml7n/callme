"""Tests for the webhook integration runtime."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.integrations.webhook import call_webhook


class TestCallWebhook:
    @pytest.mark.anyio
    async def test_successful_json_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_success = True
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.integrations.webhook.httpx.AsyncClient", return_value=mock_client):
            result = await call_webhook(
                config={"url": "https://example.com/hook", "method": "POST"},
                params={"key": "value"},
            )

        assert result["success"] is True
        assert result["status_code"] == 200
        assert result["body"] == {"ok": True}

    @pytest.mark.anyio
    async def test_timeout_returns_error(self):
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.integrations.webhook.httpx.AsyncClient", return_value=mock_client):
            result = await call_webhook(
                config={"url": "https://example.com/hook"},
                params={},
            )

        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    @pytest.mark.anyio
    async def test_http_error_returns_status(self):
        error_response = httpx.Response(500)
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error",
                request=httpx.Request("POST", "https://example.com"),
                response=error_response,
            )
        )

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.integrations.webhook.httpx.AsyncClient", return_value=mock_client):
            result = await call_webhook(
                config={"url": "https://example.com/hook"},
                params={},
            )

        assert result["success"] is False
        assert "500" in str(result.get("error", "")) or result.get("status_code") == 500

    @pytest.mark.anyio
    async def test_auth_header_injected(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_success = True
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.integrations.webhook.httpx.AsyncClient", return_value=mock_client):
            await call_webhook(
                config={
                    "url": "https://example.com/hook",
                    "auth_header": "Bearer token123",
                },
                params={},
            )

        # Verify the Authorization header was included
        call_args = mock_client.request.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer token123"

    @pytest.mark.anyio
    async def test_put_method(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_success = True
        mock_resp.json.return_value = {"updated": True}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.integrations.webhook.httpx.AsyncClient", return_value=mock_client):
            result = await call_webhook(
                config={"url": "https://example.com/hook", "method": "PUT"},
                params={"data": "hello"},
            )

        assert result["success"] is True
        call_args = mock_client.request.call_args
        assert call_args[0][0] == "PUT"  # method arg

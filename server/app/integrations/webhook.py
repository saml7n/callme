"""Generic webhook integration — call external HTTP endpoints.

Sends a POST (or PUT) request to a configured URL with JSON payload
and returns the result. Timeout is capped at 5 seconds.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def call_webhook(
    config: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Fire a webhook request and return the response.

    *config* fields:
      - url (str) — target URL (required)
      - method (str) — POST or PUT, default POST
      - headers (dict) — extra HTTP headers
      - auth_header (str) — value for Authorization header

    *params* is the JSON body sent to the webhook.  The engine injects
    contextual data (caller number, current node, transcript excerpt, etc.)
    into params before calling.
    """
    url: str = config["url"]
    method: str = config.get("method", "POST").upper()
    headers: dict[str, str] = dict(config.get("headers", {}))
    headers.setdefault("Content-Type", "application/json")

    auth = config.get("auth_header")
    if auth:
        headers["Authorization"] = auth

    logger.info("Webhook %s %s", method, url)

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.request(method, url, json=params, headers=headers)
            resp.raise_for_status()

            # Try to parse JSON response; fall back to text
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text[:2000]}

            return {
                "status_code": resp.status_code,
                "body": body,
                "success": True,
            }
    except httpx.TimeoutException:
        logger.warning("Webhook timed out: %s", url)
        return {"success": False, "error": "Webhook timed out (5s)"}
    except httpx.HTTPStatusError as exc:
        logger.warning("Webhook HTTP error %s: %s", exc.response.status_code, url)
        return {
            "success": False,
            "status_code": exc.response.status_code,
            "error": f"HTTP {exc.response.status_code}",
        }
    except Exception as exc:
        logger.exception("Webhook error: %s", url)
        return {"success": False, "error": str(exc)}


# Registry of supported actions for this integration type
ACTIONS: dict[str, Any] = {
    "call_webhook": call_webhook,
}

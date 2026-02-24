"""PUBLIC_URL auto-detection — resolve the externally reachable base URL.

Resolution order:
1. ``PUBLIC_URL`` environment variable (if set and non-empty).
2. ngrok local API at ``http://<NGROK_HOST>:4040/api/tunnels``.
3. Fallback to ``http://localhost:<PORT>``.

The resolved URL is cached in-process and also stored in the DB settings
table so other parts of the app (webhook handler, etc.) can read it.
"""

from __future__ import annotations

import logging
import os

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_resolved_url: str = ""


async def resolve_public_url() -> str:
    """Detect the public URL, cache it in-module, and return it.

    Safe to call multiple times — re-resolves each time (cheap).
    """
    global _resolved_url

    # 1. Explicit env var
    if settings.public_url:
        _resolved_url = settings.public_url.rstrip("/")
        logger.info("PUBLIC_URL from env: %s", _resolved_url)
        return _resolved_url

    # 2. ngrok local API
    ngrok_host = os.environ.get("NGROK_HOST", "localhost")
    ngrok_api = f"http://{ngrok_host}:4040/api/tunnels"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(ngrok_api)
            if resp.status_code == 200:
                tunnels = resp.json().get("tunnels", [])
                for t in tunnels:
                    public = t.get("public_url", "")
                    if public.startswith("https://"):
                        _resolved_url = public.rstrip("/")
                        logger.info("PUBLIC_URL from ngrok API (%s): %s", ngrok_api, _resolved_url)
                        return _resolved_url
                    if public.startswith("http://") and not _resolved_url:
                        _resolved_url = public.rstrip("/")
                # If we only found http, use it
                if _resolved_url:
                    logger.info("PUBLIC_URL from ngrok API (http only): %s", _resolved_url)
                    return _resolved_url
    except Exception:
        logger.debug("ngrok API not available at %s — skipping", ngrok_api)

    # 3. Fallback
    _resolved_url = f"http://localhost:{settings.port}"
    logger.info("PUBLIC_URL fallback: %s", _resolved_url)
    return _resolved_url


def get_public_url() -> str:
    """Return the last resolved PUBLIC_URL (empty string if never resolved)."""
    return _resolved_url

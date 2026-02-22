"""Authentication middleware for the CallMe API.

Uses a simple API key approach:
- `CALLME_API_KEY` env var defines the shared secret
- Dashboard login sends the key, stored in localStorage
- API requests use `Authorization: Bearer <key>`
- `/twilio/*` endpoints are exempt (use Twilio signature validation)
- `/health` is exempt
"""

from __future__ import annotations

import logging
import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


def _get_api_key() -> str:
    """Return the configured API key, auto-generating if not set."""
    key = settings.callme_api_key
    if not key:
        # Generate a random key and warn — in production, set CALLME_API_KEY
        key = secrets.token_urlsafe(32)
        settings.callme_api_key = key
        logger.warning(
            "No CALLME_API_KEY set — auto-generated key: %s  "
            "(set CALLME_API_KEY env var for production)",
            key,
        )
    return key


# Eager initialization so the key is logged at startup
_api_key: str = ""


def init_api_key() -> str:
    """Initialize the API key. Called during app startup."""
    global _api_key
    _api_key = _get_api_key()
    return _api_key


def get_api_key() -> str:
    """Return the current API key (for use in login endpoint)."""
    return _api_key or init_api_key()


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency that validates the Bearer token.

    Returns the API key if valid, raises 401/403 otherwise.
    """
    key = get_api_key()

    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authentication")

    if not secrets.compare_digest(credentials.credentials, key):
        raise HTTPException(status_code=403, detail="Invalid API key")

    return credentials.credentials

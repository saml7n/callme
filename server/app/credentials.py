"""Runtime credential resolver.

Provides API keys to the STT, TTS, LLM, and Twilio clients by checking:
1. User's own database settings (set via the setup wizard) — takes precedence.
2. Platform environment variables (via ``app.config.settings``) — used when
   the user has opted in via ``use_platform_keys`` or when ``user_id`` is None.

Resolution rules:
- ``user_id is None`` → DB fallback (any row) then env (backward compat).
- ``user_id is not None`` → user's DB setting, then platform env **only if**
  the user has ``use_platform_keys`` enabled.

This module is the single source of truth for runtime credentials.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.config import settings

logger = logging.getLogger(__name__)


def _from_db(key: str, user_id: UUID | None = None) -> str:
    """Read a setting from the DB settings store. Returns '' on failure."""
    try:
        from app.db.session import get_session
        from app.api.settings import get_setting
        session = next(get_session())
        return get_setting(session, key, user_id=user_id) or ""
    except Exception:
        return ""


def _user_wants_platform_keys(user_id: UUID) -> bool:
    """Check whether the user has opted in to using platform keys."""
    return _from_db("use_platform_keys", user_id) == "true"


def _resolve(key: str, env_value: str, user_id: UUID | None = None) -> str:
    """Resolve a credential by checking user DB, platform env, and fallbacks.

    1. User's own DB setting (if ``user_id`` given).
    2. Platform env value — if user opted in *or* ``user_id`` is None.
    """
    db_val = _from_db(key, user_id)
    if db_val:
        return db_val
    # Fall back to platform env when allowed
    if user_id is None or _user_wants_platform_keys(user_id):
        return env_value
    return ""


def get_twilio_account_sid(user_id: UUID | None = None) -> str:
    """Return the Twilio Account SID."""
    return _resolve("twilio_account_sid", settings.twilio_account_sid, user_id)


def get_twilio_auth_token(user_id: UUID | None = None) -> str:
    """Return the Twilio Auth Token."""
    return _resolve("twilio_auth_token", settings.twilio_auth_token, user_id)


def get_twilio_api_key_sid(user_id: UUID | None = None) -> str:
    """Return the Twilio API Key SID."""
    return _resolve("twilio_api_key_sid", settings.twilio_api_key_sid, user_id)


def get_twilio_api_key_secret(user_id: UUID | None = None) -> str:
    """Return the Twilio API Key Secret."""
    return _resolve("twilio_api_key_secret", settings.twilio_api_key_secret, user_id)


def get_twilio_phone_number(user_id: UUID | None = None) -> str:
    """Return the Twilio phone number."""
    return _resolve("twilio_phone_number", settings.twilio_phone_number, user_id)


def get_deepgram_api_key(user_id: UUID | None = None) -> str:
    """Return the Deepgram API key."""
    return _resolve("deepgram_api_key", settings.deepgram_api_key, user_id)


def get_elevenlabs_api_key(user_id: UUID | None = None) -> str:
    """Return the ElevenLabs API key."""
    return _resolve("elevenlabs_api_key", settings.elevenlabs_api_key, user_id)


def get_openai_api_key(user_id: UUID | None = None) -> str:
    """Return the OpenAI API key."""
    return _resolve("openai_api_key", settings.openai_api_key, user_id)


def get_admin_phone_number(user_id: UUID | None = None) -> str:
    """Return the admin phone number for alerts."""
    return _resolve("admin_phone_number", "", user_id)

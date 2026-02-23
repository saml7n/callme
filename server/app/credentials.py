"""Runtime credential resolver.

Provides API keys to the STT, TTS, LLM, and Twilio clients by checking:
1. Database settings store (set via the setup wizard) — takes precedence.
2. Environment variables (via ``app.config.settings``) — local dev fallback.

This ensures that in production the user's keys (entered through the UI)
always win, while the ``.env`` file remains a convenience for local
development when the database is empty.

This module is the single source of truth for runtime credentials.
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


def _from_db(key: str) -> str:
    """Read a setting from the DB settings store. Returns '' on failure."""
    try:
        from app.db.session import get_session
        from app.api.settings import get_setting
        session = next(get_session())
        return get_setting(session, key) or ""
    except Exception:
        return ""


def get_twilio_account_sid() -> str:
    """Return the Twilio Account SID."""
    return _from_db("twilio_account_sid") or settings.twilio_account_sid


def get_twilio_auth_token() -> str:
    """Return the Twilio Auth Token."""
    return _from_db("twilio_auth_token") or settings.twilio_auth_token


def get_twilio_api_key_sid() -> str:
    """Return the Twilio API Key SID."""
    return _from_db("twilio_api_key_sid") or settings.twilio_api_key_sid


def get_twilio_api_key_secret() -> str:
    """Return the Twilio API Key Secret."""
    return _from_db("twilio_api_key_secret") or settings.twilio_api_key_secret


def get_twilio_phone_number() -> str:
    """Return the Twilio phone number."""
    return _from_db("twilio_phone_number") or settings.twilio_phone_number


def get_deepgram_api_key() -> str:
    """Return the Deepgram API key."""
    return _from_db("deepgram_api_key") or settings.deepgram_api_key


def get_elevenlabs_api_key() -> str:
    """Return the ElevenLabs API key."""
    return _from_db("elevenlabs_api_key") or settings.elevenlabs_api_key


def get_openai_api_key() -> str:
    """Return the OpenAI API key."""
    return _from_db("openai_api_key") or settings.openai_api_key


def get_admin_phone_number() -> str:
    """Return the admin phone number for alerts."""
    return _from_db("admin_phone_number")

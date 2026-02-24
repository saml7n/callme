"""Authentication middleware for the CallMe API.

Supports two authentication methods:
1. **JWT tokens** — issued on register/login, contain ``user_id`` claim.
2. **API key** — ``CALLME_API_KEY`` env var for admin/superuser bypass.

``get_current_user()`` is the main FastAPI dependency. It returns the
authenticated ``User`` object (or a synthetic admin user for API key auth).
``require_auth`` is kept as an alias for backwards compat during migration.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from app.config import settings
from app.db.models import User
from app.db.session import get_session as _original_get_session

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

# JWT configuration
JWT_SECRET_KEY: str = ""  # set from CALLME_API_KEY or random at startup
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 7


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_jwt(user_id: UUID, email: str, name: str) -> str:
    """Create a JWT token for the given user."""
    payload = {
        "sub": str(user_id),
        "email": email,
        "name": name,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRY_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    """Decode and validate a JWT token. Returns the payload dict."""
    return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])


# ---------------------------------------------------------------------------
# API key (admin bypass) — legacy support
# ---------------------------------------------------------------------------

_api_key: str = ""


def _get_api_key() -> str:
    """Return the configured API key, auto-generating if not set."""
    key = settings.callme_api_key
    if not key:
        key = secrets.token_urlsafe(32)
        settings.callme_api_key = key
        logger.warning(
            "No CALLME_API_KEY set — auto-generated key: %s  "
            "(set CALLME_API_KEY env var for production)",
            key,
        )
    return key


def init_api_key() -> str:
    """Initialize the API key and JWT secret. Called during app startup."""
    global _api_key, JWT_SECRET_KEY
    _api_key = _get_api_key()
    # Use the API key as JWT signing secret (deterministic & stable across restarts)
    JWT_SECRET_KEY = _api_key
    return _api_key


def get_api_key() -> str:
    """Return the current API key (for use in login endpoint)."""
    return _api_key or init_api_key()


# ---------------------------------------------------------------------------
# Admin user helper
# ---------------------------------------------------------------------------

# Cached admin user ID (plain UUID, safe across sessions)
_admin_user_id: UUID | None = None


def ensure_admin_user(session: Session) -> User:
    """Get or create the admin user used for API key auth & data backfill.

    When ``SEED_DEMO`` is enabled the admin user is created with a friendly
    demo email (``demo@callme.ai`` / ``demo1234``) so that the web-UI login
    works out of the box.  Otherwise it uses ``admin@local`` with no password.
    """
    import os
    from sqlmodel import select

    global _admin_user_id
    if _admin_user_id is not None:
        existing = session.get(User, _admin_user_id)
        if existing is not None:
            return existing

    demo_mode = os.environ.get("SEED_DEMO", "").lower() in ("true", "1", "yes")
    admin_email = "demo@callme.ai" if demo_mode else "admin@local"

    # Check both emails so we find the user regardless of mode switch
    existing = session.exec(
        select(User).where(User.email.in_(["admin@local", "demo@callme.ai"]))  # type: ignore[union-attr]
    ).first()
    if existing is not None:
        _admin_user_id = existing.id
        return existing

    # Create with demo credentials when SEED_DEMO is active
    if demo_mode:
        from app.seed import DEMO_PASSWORD, DEMO_NAME
        admin = User(
            email=admin_email,
            name=DEMO_NAME,
            password_hash=hash_password(DEMO_PASSWORD),
        )
    else:
        admin = User(email=admin_email, name="Admin", password_hash="")

    session.add(admin)
    session.commit()
    session.refresh(admin)
    _admin_user_id = admin.id
    logger.info("Created admin user: %s (email=%s)", admin.id, admin_email)
    return admin


def backfill_user_ids(session: Session, admin_user_id: UUID) -> None:
    """Assign orphaned rows (user_id=NULL) to the admin user."""
    from sqlalchemy import text

    tables = ("workflows", "phone_numbers", "integrations", "calls", "settings")
    for table in tables:
        result = session.exec(
            text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),  # type: ignore[arg-type]
            params={"uid": str(admin_user_id)},
        )
        if result.rowcount:  # type: ignore[union-attr]
            logger.info("Backfilled %d rows in %s → admin user", result.rowcount, table)  # type: ignore[union-attr]
    session.commit()


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: Session = Depends(_original_get_session),
) -> User:
    """FastAPI dependency — authenticate via JWT or API key.

    Returns the ``User`` object. For API key auth, returns the admin user.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authentication")

    token = credentials.credentials

    # Try API key first (fast path)
    api_key = get_api_key()
    if secrets.compare_digest(token, api_key):
        return ensure_admin_user(session)

    # Try JWT
    try:
        payload = decode_jwt(token)
        user_id = UUID(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    return user


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Legacy auth dependency — validates Bearer token (JWT or API key).

    Returns the token string. Kept for backwards compatibility with
    router-level ``dependencies=[Depends(require_auth)]``.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authentication")

    token = credentials.credentials

    # API key check
    api_key = get_api_key()
    if secrets.compare_digest(token, api_key):
        return token

    # JWT check
    try:
        decode_jwt(token)
        return token
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

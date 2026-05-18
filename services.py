"""Shared helpers used by multiple route files.

Kernel-runtime route auto-discovery doesn't put ``routes/`` on ``sys.path``
as an importable package, so ``from routes.api.foo import …`` won't work
across route files. Helpers used by more than one route module live here
at the project root, next to ``models.py``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from sqlmodel import Session, select

from crypto import decrypt
from models import Setting

logger = logging.getLogger(__name__)


def get_engine():
    """Return the active parbaked SQLAlchemy engine.

    Used by background-task code (the websocket media-stream, the call
    logger, the credentials resolver) that opens its own ``Session`` outside
    of a request scope. Inside a request, prefer the
    ``Depends(get_session)`` injection from ``parbaked``.
    """
    from parbaked.runtime import _get_active

    return _get_active().engine


def get_setting(session: Session, key: str, user_id: Optional[UUID] = None) -> str:
    """Read a single setting by key for the given user. Returns ``""`` if missing.

    Values are stored Fernet-encrypted; this helper decrypts before returning.
    Falls back to a global (``user_id IS NULL``) row when none is set for the user.
    """
    stmt = select(Setting).where(Setting.key == key)
    if user_id is not None:
        stmt = stmt.where(Setting.user_id == user_id)
    row = session.exec(stmt).first()
    if row is None and user_id is not None:
        # Fallback to global setting
        row = session.exec(select(Setting).where(Setting.key == key, Setting.user_id.is_(None))).first()  # type: ignore[union-attr]
    if row is None or not row.value_encrypted:
        return ""
    try:
        return decrypt(row.value_encrypted)
    except Exception:
        logger.exception("Failed to decrypt setting %s", key)
        return ""


def get_all_settings(session: Session, user_id: Optional[UUID] = None) -> dict[str, str]:
    """Read all settings for the given user, decrypted. Empty values are skipped."""
    stmt = select(Setting)
    if user_id is not None:
        stmt = stmt.where(Setting.user_id == user_id)
    rows = session.exec(stmt).all()
    out: dict[str, str] = {}
    for r in rows:
        if not r.value_encrypted:
            continue
        try:
            out[r.key] = decrypt(r.value_encrypted)
        except Exception:
            logger.exception("Failed to decrypt setting %s", r.key)
    return out


# ---------------------------------------------------------------------------
# Admin gate — parbaked's User model doesn't have ``is_admin``. The admin in
# parbaked is the local-only admin (first user, password in .parbaked.json,
# UI at /admin). Application-level admin gating uses "first user wins"
# semantics: the earliest-created active user is the admin.
# ---------------------------------------------------------------------------


def is_app_admin(session: Session, user: Any) -> bool:
    """Return True if ``user`` is the first registered user (i.e. app admin)."""
    from parbaked.auth.models import User as PBUser

    first = session.exec(select(PBUser).order_by(PBUser.created_at).limit(1)).first()
    if first is None:
        return False
    return getattr(first, "id", None) == getattr(user, "id", None)

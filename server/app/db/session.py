"""Database engine and session management.

Uses SQLite via SQLModel (built on SQLAlchemy).
Call ``init_db()`` once at startup to create tables.
Use ``get_session()`` as a FastAPI dependency for request-scoped sessions.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

# Import models so SQLModel.metadata knows about them
import app.db.models  # noqa: F401

logger = logging.getLogger(__name__)

_engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},  # needed for SQLite
    poolclass=StaticPool,  # single shared connection — avoids pool exhaustion
)


def _migrate_existing_data() -> None:
    """Add user_id columns and migrate legacy data after schema upgrade.

    Since we don't use Alembic, this runs on every startup. It:
    1. Adds missing ``user_id`` columns to tenant tables (safe if already present).
    2. Migrates the old single-PK ``settings`` table to the new UUID-PK schema.
    3. Creates a default admin user and backfills orphaned rows.
    """
    inspector = inspect(_engine)
    tables = inspector.get_table_names()

    with Session(_engine) as session:
        # --- 1. Add user_id columns where missing ---
        for table_name in ("workflows", "phone_numbers", "integrations", "calls"):
            if table_name not in tables:
                continue
            cols = {c["name"] for c in inspector.get_columns(table_name)}
            if "user_id" not in cols:
                logger.info("Adding user_id column to %s", table_name)
                session.exec(text(f"ALTER TABLE {table_name} ADD COLUMN user_id TEXT"))  # type: ignore[arg-type]

        # --- 2. Migrate old settings table (key as PK → id as PK + user_id) ---
        if "settings" in tables:
            cols = {c["name"] for c in inspector.get_columns("settings")}
            if "id" not in cols:
                # Old schema: PK=key.  Rename → migrate → drop old.
                logger.info("Migrating settings table to new schema (adding id + user_id)")
                session.exec(text("ALTER TABLE settings RENAME TO _settings_old"))  # type: ignore[arg-type]
                session.commit()

                # Create new table via SQLModel metadata
                from app.db.models import Setting  # noqa: F811
                Setting.metadata.create_all(_engine, tables=[Setting.__table__])

                # Copy rows from old table
                old_rows = session.exec(text("SELECT key, value_encrypted, updated_at FROM _settings_old")).all()  # type: ignore[arg-type]
                for row in old_rows:
                    session.exec(
                        text(
                            "INSERT INTO settings (id, key, user_id, value_encrypted, updated_at) "
                            "VALUES (:id, :key, NULL, :val, :upd)"
                        ),
                        params={"id": str(uuid4()), "key": row[0], "val": row[1], "upd": row[2]},
                    )
                session.exec(text("DROP TABLE _settings_old"))  # type: ignore[arg-type]
                session.commit()
            elif "user_id" not in cols:
                logger.info("Adding user_id column to settings")
                session.exec(text("ALTER TABLE settings ADD COLUMN user_id TEXT"))  # type: ignore[arg-type]

        # --- 3. Add is_admin column to users table if missing ---
        if "users" in tables:
            user_cols = {c["name"] for c in inspector.get_columns("users")}
            if "is_admin" not in user_cols:
                logger.info("Adding is_admin column to users")
                session.exec(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"))  # type: ignore[arg-type]

        # Backfill happens in auth init (see app.auth.ensure_admin_user)
        session.commit()


def init_db() -> None:
    """Create all tables if they don't exist, then run migrations."""
    SQLModel.metadata.create_all(_engine)
    _migrate_existing_data()


def get_engine():
    """Return the module-level SQLAlchemy engine."""
    return _engine


def get_session() -> Generator[Session, None, None]:
    """Yield a SQLModel session — use as a FastAPI ``Depends``."""
    with Session(_engine) as session:
        yield session

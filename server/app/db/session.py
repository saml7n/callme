"""Database engine and session management.

Uses SQLite via SQLModel (built on SQLAlchemy).
Call ``init_db()`` once at startup to create tables.
Use ``get_session()`` as a FastAPI dependency for request-scoped sessions.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

# Import models so SQLModel.metadata knows about them
import app.db.models  # noqa: F401

_engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},  # needed for SQLite
)


def init_db() -> None:
    """Create all tables if they don't exist."""
    SQLModel.metadata.create_all(_engine)


def get_session() -> Generator[Session, None, None]:
    """Yield a SQLModel session — use as a FastAPI ``Depends``."""
    with Session(_engine) as session:
        yield session

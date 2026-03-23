"""Shared test fixtures for database-backed tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generator
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.db.session as session_mod
from app.auth import get_current_user, require_admin, require_auth
import app.auth as auth_mod
from app.db.models import Call, CallEvent, EventType, Integration, IntegrationType, PhoneNumber, User, Workflow
from app.db.session import get_session as _original_get_session
from app.main import app

# Lazy import — seed may not exist yet in older branches
try:
    import app.seed as seed_mod
except ImportError:
    seed_mod = None  # type: ignore[assignment]

# Fixed test API key
TEST_API_KEY = "test-api-key-for-tests"

# Fixed test user for API tests
TEST_USER_ID = uuid4()
TEST_USER = User(id=TEST_USER_ID, email="test@example.com", name="Test User", password_hash="", is_admin=True)


def _minimal_graph() -> dict[str, Any]:
    """Return a minimal valid workflow graph_json."""
    return {
        "id": "wf_test",
        "name": "Test Workflow",
        "version": 1,
        "entry_node_id": "greeting",
        "nodes": [
            {
                "id": "greeting",
                "type": "conversation",
                "data": {
                    "instructions": "Greet the caller.",
                    "max_iterations": 3,
                },
            },
        ],
        "edges": [],
    }


def _reception_flow() -> dict[str, Any]:
    """Load the reception_flow.json example."""
    path = (
        Path(__file__).resolve().parent.parent
        / "schemas"
        / "examples"
        / "reception_flow.json"
    )
    return json.loads(path.read_text())


@pytest.fixture
def minimal_graph() -> dict[str, Any]:
    return _minimal_graph()


@pytest.fixture
def reception_flow() -> dict[str, Any]:
    return _reception_flow()


@pytest.fixture(autouse=False)
def db_session() -> Generator[Session, None, None]:
    """Create an in-memory SQLite database for each test.

    Also disables auth for API tests so they don't need a token.
    Patches ``get_session`` everywhere it was imported:
    - ``app.db.session`` module (canonical)
    - ``app.db.call_logger`` module (imported directly)
    - FastAPI dependency overrides (for API endpoints)
    """
    engine = create_engine(
        "sqlite://",  # in-memory
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)

    def _override() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    # Disable auth for API tests by default
    async def _no_auth() -> str:
        return TEST_API_KEY

    # Return a test user for endpoints using get_current_user or require_admin
    async def _test_user() -> User:
        return TEST_USER

    # Override require_admin to return the test user (who is admin)
    async def _test_admin() -> User:
        return TEST_USER

    # Monkey-patch at every import site
    original_session = session_mod.get_session
    original_engine = session_mod._engine
    original_get_engine = session_mod.get_engine
    session_mod.get_session = _override
    session_mod._engine = engine          # call_logger & media_stream import _engine lazily
    session_mod.get_engine = lambda: engine  # type: ignore[assignment]
    # Also patch get_engine where seed.py imported it
    if seed_mod is not None:
        original_seed_get_engine = seed_mod.get_engine
        seed_mod.get_engine = lambda: engine  # type: ignore[assignment]

    # FastAPI dependency override for endpoints using Depends(get_session)
    app.dependency_overrides[_original_get_session] = _override
    app.dependency_overrides[require_auth] = _no_auth
    app.dependency_overrides[get_current_user] = _test_user
    app.dependency_overrides[require_admin] = _test_admin

    with Session(engine) as session:
        # Create the test user in the DB so FK references work
        existing = session.get(User, TEST_USER.id)
        if existing is None:
            session.add(User(id=TEST_USER.id, email=TEST_USER.email, name=TEST_USER.name, password_hash=""))
            session.commit()
        yield session

    # Restore everything
    session_mod.get_session = original_session
    session_mod._engine = original_engine
    session_mod.get_engine = original_get_engine
    if seed_mod is not None:
        seed_mod.get_engine = original_seed_get_engine
    app.dependency_overrides.pop(_original_get_session, None)
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(require_admin, None)
    # Clear the admin user cache so it doesn't leak across tests
    auth_mod._admin_user_id = None

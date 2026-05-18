"""Post-migration smoke tests.

Pin the contract that the kernel-runtime migration didn't break the basics:
- parbaked boots
- callme's route files mount at the expected paths
- callme's domain tables register with SQLModel.metadata
- /health, /auth/*, and the gated routes return their expected codes
"""

from __future__ import annotations

import os
import sys
from io import StringIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from parbaked import runtime
from parbaked.email import ConsoleEmail

SERVER_ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """Boot parbaked once for the whole module.

    SQLModel keeps a process-wide ``metadata`` so re-importing ``models.py``
    after a previous boot would raise "Table 'workflows' is already defined";
    we sidestep that by running every assertion against one app instance.
    """
    server_root = SERVER_ROOT
    if str(server_root) not in sys.path:
        sys.path.insert(0, str(server_root))
    prev_cwd = os.getcwd()
    os.chdir(server_root)
    for k in list(os.environ):
        if k.startswith("PARBAKED_") or k == "DATABASE_URL":
            os.environ.pop(k, None)
    os.environ.setdefault("CALLME_ENCRYPTION_KEY", "smoke-test-key-not-secret")

    runtime._reset_for_tests()

    tmp_path = tmp_path_factory.mktemp("callme-smoke")
    try:
        app = runtime.create_app(
            secrets_file=tmp_path / ".parbaked.json",
            database_url=f"sqlite:///{tmp_path / 'callme-test.db'}",
            admin_password="testadmin",
            email=ConsoleEmail(buffer=StringIO()),
            banner=False,
        )
        yield app
    finally:
        os.chdir(prev_cwd)
        runtime._reset_for_tests()


def test_health_and_signup(app):
    """``/health`` is open, ``/auth/signup`` creates a pending user."""
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    r = client.post(
        "/auth/signup",
        json={"email": "alice@example.com", "password": "correcthorse123", "name": "Alice"},
    )
    assert r.status_code == 201, f"signup failed: {r.status_code} {r.text[:200]}"


def test_api_routes_are_auth_gated(app):
    """Every callme API route mounted and rejects anonymous GETs with 401."""
    client = TestClient(app)
    for path in (
        "/api/workflows",
        "/api/phone-numbers",
        "/api/calls",
        "/api/integrations",
        "/api/settings",
        "/api/templates",
    ):
        r = client.get(path)
        assert r.status_code == 401, f"{path} should require auth, got {r.status_code}: {r.text[:200]}"

    # /api/platform/status is intentionally public.
    r = client.get("/api/platform/status")
    assert r.status_code == 200, f"/api/platform/status should be public, got {r.status_code}"


def test_twilio_routes_mount(app):
    """The Twilio incoming + media-stream routes are discovered and mounted."""
    client = TestClient(app)
    # Twilio incoming: POST without form-data must NOT 404 (route is mounted).
    # Without a configured twilio_auth_token signature check is skipped, so the
    # endpoint should return 200 with empty form body.
    r = client.post("/twilio/incoming", data={})
    assert r.status_code == 200, f"/twilio/incoming missing or broken: {r.status_code} {r.text[:200]}"
    assert "<Response>" in r.text

    # Media stream is a WebSocket — check the route is registered.
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/twilio/media-stream" in paths, f"/twilio/media-stream not mounted; saw {sorted(p for p in paths if p)}"
    assert "/api/live/ws" in paths, "/api/live/ws (live event WS) not mounted"


def test_callme_tables_registered(app):
    """callme's domain tables are SQLModel tables registered on metadata at boot.

    ``parbaked.runtime._autoload_consumer_models`` imports ``models.py`` for
    us; we just check the registration.
    """
    from sqlmodel import SQLModel

    tables = set(SQLModel.metadata.tables.keys())
    for t in ("workflows", "phone_numbers", "integrations", "calls", "call_events", "settings"):
        assert t in tables, f"{t} not registered: {sorted(tables)}"


def test_user_table_belongs_to_parbaked(app):
    """callme's ``models.py`` must NOT redefine the ``users`` table.

    parbaked owns it; rebinding it here would break FK resolution.
    """
    from sqlmodel import SQLModel
    from parbaked.auth.models import User as PBUser

    users_table = SQLModel.metadata.tables.get("users")
    assert users_table is not None, "users table missing — parbaked.auth.models.User must be imported"
    assert users_table is PBUser.__table__, "users table belongs to a different model than parbaked.auth.models.User"

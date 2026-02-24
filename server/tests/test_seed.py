"""Tests for demo seed data and admin reset endpoints (Story 24)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from app.db.models import Call, CallEvent, PhoneNumber, Setting, User, Workflow
from app.main import app
from app.seed import DEMO_EMAIL, seed_demo_data, wipe_demo_data


# ---------------------------------------------------------------------------
# Unit tests for seed module (use db_session fixture)
# ---------------------------------------------------------------------------

class TestSeedDemoData:
    def test_seed_creates_user(self, db_session):
        """Seeding creates a demo user."""
        seed_demo_data()
        user = db_session.exec(select(User).where(User.email == DEMO_EMAIL)).first()
        assert user is not None
        assert user.name == "Demo User"

    def test_seed_creates_workflow(self, db_session):
        """Seeding creates the Dental Reception Flow workflow."""
        seed_demo_data()
        wf = db_session.exec(
            select(Workflow).where(Workflow.name == "Dental Reception Flow")
        ).first()
        assert wf is not None
        assert wf.is_active is True

    def test_seed_creates_phone_number(self, db_session):
        """Seeding creates a phone number linked to the workflow."""
        seed_demo_data()
        pn = db_session.exec(select(PhoneNumber)).first()
        assert pn is not None
        assert pn.label == "Main Line"

    def test_seed_creates_calls(self, db_session):
        """Seeding creates 3 synthetic calls."""
        seed_demo_data()
        calls = db_session.exec(select(Call)).all()
        assert len(calls) == 3

    def test_seed_creates_call_events(self, db_session):
        """Seeding creates events for each call."""
        seed_demo_data()
        events = db_session.exec(select(CallEvent)).all()
        # 6 + 6 + 3 = 15 events across the 3 scenarios
        assert len(events) == 15

    def test_seed_is_idempotent(self, db_session):
        """Running seed twice doesn't duplicate data."""
        seed_demo_data()
        seed_demo_data()
        users = db_session.exec(select(User).where(User.email == DEMO_EMAIL)).all()
        assert len(users) == 1
        workflows = db_session.exec(
            select(Workflow).where(Workflow.name == "Dental Reception Flow")
        ).all()
        assert len(workflows) == 1


class TestWipeDemoData:
    def test_wipe_removes_all_data(self, db_session):
        """Wipe clears all user data from all tables."""
        seed_demo_data()
        # Verify data exists
        assert db_session.exec(select(User)).first() is not None
        wipe_demo_data()
        # Everything should be gone
        # Need to expire cached objects so we see the wiped state
        db_session.expire_all()
        assert db_session.exec(select(User).where(User.email == DEMO_EMAIL)).first() is None
        assert db_session.exec(select(Workflow)).first() is None
        assert db_session.exec(select(Call)).first() is None

    def test_wipe_then_reseed(self, db_session):
        """Wipe followed by seed re-creates fresh data."""
        seed_demo_data()
        wipe_demo_data()
        seed_demo_data()
        db_session.expire_all()
        users = db_session.exec(select(User).where(User.email == DEMO_EMAIL)).all()
        assert len(users) == 1


# ---------------------------------------------------------------------------
# API tests for admin endpoints
# ---------------------------------------------------------------------------

class TestAdminEndpoints:
    @pytest.mark.asyncio
    async def test_admin_reset(self, db_session):
        """POST /api/admin/reset wipes and re-seeds."""
        # Seed some data first
        seed_demo_data()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/admin/reset")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "reset" in data["message"].lower() or "re-seed" in data["message"].lower()
        assert data["user"] == DEMO_EMAIL

    @pytest.mark.asyncio
    async def test_admin_seed(self, db_session):
        """POST /api/admin/seed creates demo data."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/admin/seed")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["user"] == DEMO_EMAIL

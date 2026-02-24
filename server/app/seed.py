"""Demo seed data — creates a sample user, workflow, phone number, and call logs.

Used by ``SEED_DEMO=true`` on startup and by the ``POST /api/admin/reset``
endpoint.  Idempotent — safe to run repeatedly.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, select

from app.auth import hash_password
from app.db.models import (
    Call,
    CallEvent,
    EventType,
    PhoneNumber,
    Setting,
    User,
    Workflow,
)
from app.db.session import get_engine
from app.config import settings as app_settings
from app.crypto import encrypt

logger = logging.getLogger(__name__)

DEMO_EMAIL = "demo@callme.ai"
DEMO_PASSWORD = "demo1234"
DEMO_NAME = "Demo User"
SCHEMA_DIR = Path(__file__).parent.parent / "schemas" / "examples"


def seed_demo_data() -> dict[str, str]:
    """Seed a demo user, workflow, phone number, and synthetic calls.

    Returns a summary dict for API response.
    """
    engine = get_engine()
    with Session(engine) as session:
        # 1. User
        user = session.exec(select(User).where(User.email == DEMO_EMAIL)).first()
        if user is None:
            user = User(
                email=DEMO_EMAIL,
                password_hash=hash_password(DEMO_PASSWORD),
                name=DEMO_NAME,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            logger.info("Seeded demo user: %s", user.email)
        user_id = user.id

        # 2. Workflow — use the reception_flow.json example
        wf = session.exec(
            select(Workflow).where(
                Workflow.user_id == user_id,
                Workflow.name == "Dental Reception Flow",
            )
        ).first()
        if wf is None:
            flow_path = SCHEMA_DIR / "reception_flow.json"
            if flow_path.exists():
                graph = json.loads(flow_path.read_text())
            else:
                graph = {"id": "seed_wf", "name": "Dental Reception Flow",
                         "version": 1, "entry_node_id": "greeting",
                         "nodes": [], "edges": []}
            wf = Workflow(
                name="Dental Reception Flow",
                version=1,
                graph_json=graph,
                is_active=True,
                user_id=user_id,
            )
            session.add(wf)
            session.commit()
            session.refresh(wf)
            logger.info("Seeded workflow: %s (id=%s)", wf.name, wf.id)

        # 3. Phone number (from env or placeholder)
        phone = app_settings.twilio_phone_number or "+15551234567"
        pn = session.exec(
            select(PhoneNumber).where(PhoneNumber.number == phone)
        ).first()
        if pn is None:
            pn = PhoneNumber(
                number=phone,
                label="Main Line",
                workflow_id=wf.id,
                user_id=user_id,
            )
            session.add(pn)
            session.commit()
            logger.info("Seeded phone number: %s", phone)
        elif pn.workflow_id != wf.id:
            pn.workflow_id = wf.id
            session.add(pn)
            session.commit()

        # 4. Seed API keys from env into settings (if configured in env)
        _seed_settings_from_env(session, user_id)

        # 5. Synthetic call logs (3 recent calls)
        existing_calls = session.exec(
            select(Call).where(Call.user_id == user_id)
        ).all()
        if len(existing_calls) == 0:
            _seed_synthetic_calls(session, user_id, wf.id, phone)

    return {
        "user": DEMO_EMAIL,
        "workflow": "Dental Reception Flow",
        "phone": phone,
        "calls_seeded": "3",
    }


def wipe_demo_data() -> None:
    """Delete all user data (users, workflows, calls, settings, etc.).

    Used by the admin reset endpoint before re-seeding.
    """
    engine = get_engine()
    with Session(engine) as session:
        # Order matters due to FK constraints
        from app.db.models import Integration
        for model in [CallEvent, Call, PhoneNumber, Integration, Setting, Workflow, User]:
            rows = session.exec(select(model)).all()  # type: ignore[arg-type]
            for row in rows:
                session.delete(row)
        session.commit()
        logger.info("Wiped all user data")


def _seed_settings_from_env(session: Session, user_id) -> None:
    """Copy API keys from environment into the settings table if not already set."""
    env_map = {
        "twilio_account_sid": app_settings.twilio_account_sid,
        "twilio_api_key_sid": app_settings.twilio_api_key_sid,
        "twilio_api_key_secret": app_settings.twilio_api_key_secret,
        "twilio_auth_token": app_settings.twilio_auth_token,
        "deepgram_api_key": app_settings.deepgram_api_key,
        "elevenlabs_api_key": app_settings.elevenlabs_api_key,
        "openai_api_key": app_settings.openai_api_key,
        "admin_phone_number": app_settings.callme_fallback_number,
    }
    for key, value in env_map.items():
        if not value:
            continue
        existing = session.exec(
            select(Setting).where(Setting.key == key, Setting.user_id == user_id)
        ).first()
        if existing is None:
            setting = Setting(key=key, user_id=user_id, value_encrypted=encrypt(value))
            session.add(setting)
    session.commit()


def _seed_synthetic_calls(session: Session, user_id, workflow_id, phone: str) -> None:
    """Create 3 synthetic call records with events so the dashboard isn't empty."""
    now = datetime.now(timezone.utc)
    scenarios = [
        {
            "from": "+15551110001",
            "duration": 45.0,
            "offset_hours": -2,
            "events": [
                (EventType.transcript, {"role": "caller", "text": "Hi, I'd like to book a cleaning"}),
                (EventType.llm_response, {"text": "Of course! I can help with that. When works best for you?"}),
                (EventType.transcript, {"role": "caller", "text": "Next Tuesday at 10am"}),
                (EventType.llm_response, {"text": "Perfect, I have Tuesday at 10am available. Could I get your name?"}),
                (EventType.transcript, {"role": "caller", "text": "Sarah Johnson"}),
                (EventType.llm_response, {"text": "You're all set, Sarah! Cleaning appointment confirmed for Tuesday at 10am."}),
            ],
        },
        {
            "from": "+15551110002",
            "duration": 30.0,
            "offset_hours": -5,
            "events": [
                (EventType.transcript, {"role": "caller", "text": "How much does a checkup cost?"}),
                (EventType.llm_response, {"text": "A standard checkup is $60. Would you like to schedule one?"}),
                (EventType.transcript, {"role": "caller", "text": "What about whitening?"}),
                (EventType.llm_response, {"text": "Teeth whitening is $250. We use a professional-grade system."}),
                (EventType.transcript, {"role": "caller", "text": "Thanks, I'll think about it"}),
                (EventType.llm_response, {"text": "No problem! Feel free to call back anytime. Have a great day!"}),
            ],
        },
        {
            "from": "+15551110003",
            "duration": 20.0,
            "offset_hours": -24,
            "events": [
                (EventType.transcript, {"role": "caller", "text": "I need to speak with someone about my bill"}),
                (EventType.llm_response, {"text": "I'll connect you with our billing team. One moment please."}),
                (EventType.action_executed, {"action": "transfer", "target": "+15559999999"}),
            ],
        },
    ]

    for scenario in scenarios:
        started = now + timedelta(hours=scenario["offset_hours"])
        ended = started + timedelta(seconds=scenario["duration"])
        call = Call(
            call_sid=f"CA_demo_{uuid4().hex[:12]}",
            from_number=scenario["from"],
            to_number=phone,
            workflow_id=workflow_id,
            user_id=user_id,
            started_at=started,
            ended_at=ended,
            duration_seconds=scenario["duration"],
        )
        session.add(call)
        session.commit()
        session.refresh(call)

        for i, (etype, data) in enumerate(scenario["events"]):
            event = CallEvent(
                call_id=call.id,
                timestamp=started + timedelta(seconds=i * 5),
                event_type=etype,
                data_json=data,
            )
            session.add(event)
        session.commit()

    logger.info("Seeded %d synthetic calls", len(scenarios))

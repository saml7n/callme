"""SQLModel database models for CallMe.

Tables:
- Workflow — workflow definitions with graph JSON.
- PhoneNumber — registered phone numbers with workflow assignment.
- Integration — external service integrations (Google Calendar, webhook, etc.).
- Call — call records with metadata.
- CallEvent — timestamped events within a call.
"""

import enum
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlmodel import JSON, Column, Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

class Workflow(SQLModel, table=True):
    """A workflow definition stored in the database."""

    __tablename__ = "workflows"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    version: int = Field(default=1)
    graph_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    is_active: bool = Field(default=False, index=True)
    phone_number: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# PhoneNumber
# ---------------------------------------------------------------------------

class PhoneNumber(SQLModel, table=True):
    """A registered phone number that can be assigned to a workflow."""

    __tablename__ = "phone_numbers"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    number: str = Field(index=True, unique=True)  # E.164 format
    label: str = Field(default="")
    workflow_id: Optional[UUID] = Field(default=None, foreign_key="workflows.id")
    updated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class IntegrationType(str, enum.Enum):
    """Supported integration types."""

    google_calendar = "google_calendar"
    webhook = "webhook"


class Integration(SQLModel, table=True):
    """An external service integration with encrypted credentials."""

    __tablename__ = "integrations"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    type: IntegrationType
    name: str = Field(index=True)
    config_encrypted: str = Field(
        default="",
        description="Fernet-encrypted JSON blob of credentials/config.",
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Call
# ---------------------------------------------------------------------------

class Call(SQLModel, table=True):
    """A phone call record."""

    __tablename__ = "calls"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    call_sid: str = Field(index=True, default="")
    from_number: str = Field(default="")
    to_number: str = Field(default="")
    workflow_id: Optional[UUID] = Field(default=None, foreign_key="workflows.id")
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: Optional[datetime] = Field(default=None)
    duration_seconds: Optional[float] = Field(default=None)


# ---------------------------------------------------------------------------
# CallEvent
# ---------------------------------------------------------------------------

class EventType(str, enum.Enum):
    """Types of events logged during a call."""

    transcript = "transcript"
    llm_response = "llm_response"
    node_transition = "node_transition"
    summary_generated = "summary_generated"
    action_executed = "action_executed"
    error = "error"


class CallEvent(SQLModel, table=True):
    """A timestamped event within a call."""

    __tablename__ = "call_events"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    call_id: UUID = Field(foreign_key="calls.id", index=True)
    timestamp: datetime = Field(default_factory=_utcnow)
    event_type: EventType
    data_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


# ---------------------------------------------------------------------------
# Setting (key-value store for API keys & service config)
# ---------------------------------------------------------------------------

class Setting(SQLModel, table=True):
    """A key-value setting with encrypted value.

    Used for API keys (Twilio, Deepgram, ElevenLabs, OpenAI) and service
    configuration (phone numbers, admin phone). Values are Fernet-encrypted
    at rest.
    """

    __tablename__ = "settings"

    key: str = Field(primary_key=True)
    value_encrypted: str = Field(default="", description="Fernet-encrypted value.")
    updated_at: datetime = Field(default_factory=_utcnow)

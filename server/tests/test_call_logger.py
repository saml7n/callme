"""Tests for CallLogger (Story 10)."""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.db.call_logger import CallLogger
from app.db.models import Call, CallEvent, EventType


class TestCallLogger:
    def test_log_transcript_and_flush(self, db_session):
        call = Call(call_sid="CA_LOG1")
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        cl = CallLogger(call.id)
        cl.log_transcript("Hello there")
        cl.log_transcript("I need help")
        cl.flush()

        events = db_session.exec(
            select(CallEvent).where(CallEvent.call_id == call.id)
        ).all()
        assert len(events) == 2
        assert events[0].event_type == EventType.transcript
        assert events[0].data_json["transcript"] == "Hello there"

    def test_log_llm_response(self, db_session):
        call = Call(call_sid="CA_LOG2")
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        cl = CallLogger(call.id)
        cl.log_llm_response("Sure, I can help!")
        cl.flush()

        events = db_session.exec(
            select(CallEvent).where(CallEvent.call_id == call.id)
        ).all()
        assert len(events) == 1
        assert events[0].event_type == EventType.llm_response
        assert events[0].data_json["response"] == "Sure, I can help!"

    def test_log_node_transition(self, db_session):
        call = Call(call_sid="CA_LOG3")
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        cl = CallLogger(call.id)
        cl.log_node_transition("greeting", "booking", "e1")
        cl.flush()

        events = db_session.exec(
            select(CallEvent).where(CallEvent.call_id == call.id)
        ).all()
        assert len(events) == 1
        assert events[0].data_json["from_node"] == "greeting"
        assert events[0].data_json["to_node"] == "booking"

    def test_log_action(self, db_session):
        call = Call(call_sid="CA_LOG4")
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        cl = CallLogger(call.id)
        cl.log_action("end_call", {"message": "Goodbye!"})
        cl.flush()

        events = db_session.exec(
            select(CallEvent).where(CallEvent.call_id == call.id)
        ).all()
        assert len(events) == 1
        assert events[0].event_type == EventType.action_executed
        assert events[0].data_json["action_type"] == "end_call"

    def test_log_error(self, db_session):
        call = Call(call_sid="CA_LOG5")
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        cl = CallLogger(call.id)
        cl.log_error("Something went wrong", {"detail": "oops"})
        cl.flush()

        events = db_session.exec(
            select(CallEvent).where(CallEvent.call_id == call.id)
        ).all()
        assert len(events) == 1
        assert events[0].event_type == EventType.error
        assert events[0].data_json["error"] == "Something went wrong"

    def test_finalise_sets_ended_at_and_duration(self, db_session):
        call = Call(call_sid="CA_LOG6")
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        cl = CallLogger(call.id)
        cl.finalise()

        db_session.refresh(call)
        assert call.ended_at is not None
        assert call.duration_seconds is not None
        assert call.duration_seconds >= 0

    def test_flush_with_no_events_is_noop(self, db_session):
        call = Call(call_sid="CA_LOG7")
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        cl = CallLogger(call.id)
        cl.flush()  # should not raise

        events = db_session.exec(
            select(CallEvent).where(CallEvent.call_id == call.id)
        ).all()
        assert len(events) == 0

    def test_multiple_flushes_accumulate(self, db_session):
        call = Call(call_sid="CA_LOG8")
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)

        cl = CallLogger(call.id)
        cl.log_transcript("First")
        cl.flush()
        cl.log_transcript("Second")
        cl.flush()

        events = db_session.exec(
            select(CallEvent).where(CallEvent.call_id == call.id)
        ).all()
        assert len(events) == 2

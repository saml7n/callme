"""Tests for the WorkflowEngine — Router + Responder LLM orchestration."""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock

import pytest

from app.workflow.engine import WorkflowEngine, NodeSummary, WorkflowError


# ---------------------------------------------------------------------------
# Fake LLM clients
# ---------------------------------------------------------------------------

class FakeLLM:
    """LLM stub that returns canned responses in order."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._call_index = 0
        self.calls: list[list[dict[str, Any]]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        self.calls.append(messages)
        if self._call_index < len(self._responses):
            resp = self._responses[self._call_index]
            self._call_index += 1
            return resp
        return "Fallback response."

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[str, None]:
        result = await self.chat(messages)
        yield result


# ---------------------------------------------------------------------------
# Workflow fixtures
# ---------------------------------------------------------------------------

def _single_node_wf() -> dict:
    return {
        "id": "wf_1",
        "name": "Single Node",
        "version": 1,
        "entry_node_id": "n1",
        "nodes": [
            {
                "id": "n1",
                "type": "conversation",
                "data": {
                    "instructions": "Greet the caller warmly.",
                    "examples": [
                        {"role": "user", "content": "Hi"},
                        {"role": "assistant", "content": "Welcome!"},
                    ],
                    "max_iterations": 10,
                },
            },
        ],
        "edges": [],
    }


def _two_node_wf() -> dict:
    return {
        "id": "wf_2",
        "name": "Two Nodes",
        "version": 1,
        "entry_node_id": "n1",
        "nodes": [
            {
                "id": "n1",
                "type": "conversation",
                "data": {
                    "instructions": "Greet the caller and find out what they need.",
                    "max_iterations": 3,
                },
            },
            {
                "id": "n2",
                "type": "conversation",
                "data": {
                    "instructions": "Help the caller book an appointment.",
                },
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": "n1",
                "target": "n2",
                "label": "Caller has stated their need",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Engine start
# ---------------------------------------------------------------------------

class TestEngineStart:
    async def test_enters_entry_node_and_returns_response(self):
        responder = FakeLLM(["Hello! How can I help you?"])
        router = FakeLLM([])

        engine = WorkflowEngine(_single_node_wf(), responder=responder, router=router)
        response = await engine.start()

        assert response == "Hello! How can I help you?"
        assert engine.current_node.id == "n1"

    async def test_responder_receives_node_instructions(self):
        responder = FakeLLM(["Welcome!"])
        router = FakeLLM([])

        engine = WorkflowEngine(_single_node_wf(), responder=responder, router=router)
        await engine.start()

        # Responder was called with system message containing node instructions
        messages = responder.calls[0]
        system_msg = messages[0]["content"]
        assert "Greet the caller warmly" in system_msg

    async def test_responder_receives_examples(self):
        responder = FakeLLM(["Hi there!"])
        router = FakeLLM([])

        engine = WorkflowEngine(_single_node_wf(), responder=responder, router=router)
        await engine.start()

        messages = responder.calls[0]
        # Examples should be in messages (after system, before history)
        roles = [m["role"] for m in messages]
        assert "user" in roles  # from examples


# ---------------------------------------------------------------------------
# Handle input — STAY
# ---------------------------------------------------------------------------

class TestHandleInputStay:
    async def test_router_stay_returns_responder_response(self):
        responder = FakeLLM(["Welcome!", "We're open 9 to 5."])
        router = FakeLLM(["STAY"])

        engine = WorkflowEngine(_single_node_wf(), responder=responder, router=router)
        await engine.start()

        response, ended = await engine.handle_input("What are your hours?")

        assert response == "We're open 9 to 5."
        assert ended is False
        assert engine.current_node.id == "n1"

    async def test_chat_history_grows_on_stay(self):
        responder = FakeLLM(["Hi!", "Sure thing."])
        router = FakeLLM(["STAY"])

        engine = WorkflowEngine(_single_node_wf(), responder=responder, router=router)
        await engine.start()
        await engine.handle_input("Hello")

        # Second responder call should include growing history
        messages = responder.calls[1]
        # Should contain: system, examples (2), assistant greeting, user message
        contents = [m["content"] for m in messages]
        assert "Hello" in contents  # user message in history


# ---------------------------------------------------------------------------
# Handle input — TRANSITION
# ---------------------------------------------------------------------------

class TestHandleInputTransition:
    async def test_router_transition_moves_to_new_node(self):
        # Responder: greeting, then response in new node
        # Router: returns edge ID, then summary generation
        responder = FakeLLM(["Welcome!", "Let me help with booking."])
        router = FakeLLM([
            "e1",  # router decision: transition
            '{"summary": "Caller greeted", "key_info": {"intent": "booking"}}',  # summary
        ])

        engine = WorkflowEngine(_two_node_wf(), responder=responder, router=router)
        await engine.start()

        response, ended = await engine.handle_input("I need to book an appointment")

        assert engine.current_node.id == "n2"
        assert response == "Let me help with booking."
        assert ended is False

    async def test_summary_generated_on_transition(self):
        responder = FakeLLM(["Hi!", "Booking help."])
        router = FakeLLM([
            "e1",
            '{"summary": "Caller wants appointment", "key_info": {"name": "Alex"}}',
        ])

        engine = WorkflowEngine(_two_node_wf(), responder=responder, router=router)
        await engine.start()
        await engine.handle_input("Book please")

        assert len(engine.summaries) == 1
        assert engine.summaries[0].summary == "Caller wants appointment"
        assert engine.summaries[0].key_info == {"name": "Alex"}

    async def test_summaries_passed_to_new_node_responder(self):
        responder = FakeLLM(["Hi!", "Booking time."])
        router = FakeLLM([
            "e1",
            '{"summary": "Caller wants to book", "key_info": {}}',
        ])

        engine = WorkflowEngine(_two_node_wf(), responder=responder, router=router)
        await engine.start()
        await engine.handle_input("I want to book")

        # Second responder call (in node n2) should have summaries in system prompt
        messages = responder.calls[1]
        system_msg = messages[0]["content"]
        assert "Caller wants to book" in system_msg
        assert "Help the caller book an appointment" in system_msg


# ---------------------------------------------------------------------------
# Max iterations
# ---------------------------------------------------------------------------

class TestMaxIterations:
    async def test_forces_transition_at_max_iterations(self):
        wf = _two_node_wf()
        wf["nodes"][0]["data"]["max_iterations"] = 2

        responder = FakeLLM(["Hi!", "Sure.", "Now booking."])
        router = FakeLLM([
            "STAY",  # turn 1
            # turn 2: max_iterations reached, forced transition (no router call)
            '{"summary": "Caller greeted", "key_info": {}}',  # summary
        ])

        engine = WorkflowEngine(wf, responder=responder, router=router)
        await engine.start()

        # Turn 1: under limit
        await engine.handle_input("Hello")
        assert engine.current_node.id == "n1"

        # Turn 2: max_iterations=2 reached → forced transition
        response, ended = await engine.handle_input("Book please")
        assert engine.current_node.id == "n2"


# ---------------------------------------------------------------------------
# Single node — no outgoing edges
# ---------------------------------------------------------------------------

class TestSingleNodeNoEdges:
    async def test_stays_indefinitely(self):
        responder = FakeLLM(["Hi!", "Sure.", "Of course.", "Absolutely."])
        router = FakeLLM(["STAY", "STAY", "STAY"])

        engine = WorkflowEngine(_single_node_wf(), responder=responder, router=router)
        await engine.start()

        for _ in range(3):
            _, ended = await engine.handle_input("More please")
            assert ended is False
            assert engine.current_node.id == "n1"

    async def test_max_iterations_no_edges_stays(self):
        """With no outgoing edges, max_iterations doesn't force a transition."""
        wf = _single_node_wf()
        wf["nodes"][0]["data"]["max_iterations"] = 1

        responder = FakeLLM(["Hi!", "Still here."])
        router = FakeLLM(["STAY"])

        engine = WorkflowEngine(wf, responder=responder, router=router)
        await engine.start()

        # max_iterations=1 but no edges → router called, stays
        response, ended = await engine.handle_input("Hello")
        assert engine.current_node.id == "n1"
        assert ended is False


# ---------------------------------------------------------------------------
# Router context verification
# ---------------------------------------------------------------------------

class TestRouterContext:
    async def test_router_receives_edge_labels(self):
        responder = FakeLLM(["Hi!", "OK."])
        router = FakeLLM(["STAY"])

        engine = WorkflowEngine(_two_node_wf(), responder=responder, router=router)
        await engine.start()
        await engine.handle_input("Hello")

        # Router was called — check its messages
        router_messages = router.calls[0]
        system = router_messages[0]["content"]
        assert "e1" in system
        assert "Caller has stated their need" in system

    async def test_router_receives_chat_history(self):
        responder = FakeLLM(["Hi!", "OK."])
        router = FakeLLM(["STAY"])

        engine = WorkflowEngine(_two_node_wf(), responder=responder, router=router)
        await engine.start()
        await engine.handle_input("I have a question")

        router_messages = router.calls[0]
        # Chat history messages should include the greeting and user input
        contents = [m["content"] for m in router_messages]
        assert "Hi!" in contents  # assistant greeting
        assert "I have a question" in contents  # user input

    async def test_no_edges_skips_router(self):
        responder = FakeLLM(["Hi!", "Sure."])
        router = FakeLLM([])

        engine = WorkflowEngine(_single_node_wf(), responder=responder, router=router)
        await engine.start()
        await engine.handle_input("Hello")

        # Router should not have been called (no edges)
        assert len(router.calls) == 0


# ---------------------------------------------------------------------------
# Unknown router decision
# ---------------------------------------------------------------------------

class TestUnknownRouterDecision:
    async def test_unknown_decision_stays(self):
        responder = FakeLLM(["Hi!", "Still here."])
        router = FakeLLM(["GIBBERISH"])

        engine = WorkflowEngine(_two_node_wf(), responder=responder, router=router)
        await engine.start()

        response, ended = await engine.handle_input("Hello")
        assert engine.current_node.id == "n1"
        assert ended is False

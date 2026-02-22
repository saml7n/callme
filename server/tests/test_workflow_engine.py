"""Tests for the WorkflowEngine — Router + Responder LLM orchestration."""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock

import pytest

from app.workflow.engine import WorkflowEngine, ActionResult, NodeSummary, WorkflowError


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
        # Examples should be embedded in the system prompt (not as separate messages)
        system_msg = messages[0]["content"]
        assert "Example exchanges" in system_msg
        assert "Welcome!" in system_msg  # from the example assistant response


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


# ---------------------------------------------------------------------------
# Decision node workflow fixtures
# ---------------------------------------------------------------------------

def _decision_wf() -> dict:
    """Greeting → Decision → Booking / Inquiry."""
    return {
        "id": "wf_decision",
        "name": "Decision Flow",
        "version": 1,
        "entry_node_id": "greeting",
        "nodes": [
            {
                "id": "greeting",
                "type": "conversation",
                "data": {
                    "instructions": "Greet the caller and find out what they need.",
                    "max_iterations": 3,
                },
            },
            {
                "id": "router",
                "type": "decision",
                "data": {
                    "instruction": "Determine whether the caller wants to book or has a question.",
                },
            },
            {
                "id": "booking",
                "type": "conversation",
                "data": {
                    "instructions": "Help the caller book an appointment.",
                },
            },
            {
                "id": "inquiry",
                "type": "conversation",
                "data": {
                    "instructions": "Answer the caller's question about services.",
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "greeting", "target": "router", "label": "Caller has stated their need"},
            {"id": "e2", "source": "router", "target": "booking", "label": "Caller wants to book an appointment"},
            {"id": "e3", "source": "router", "target": "inquiry", "label": "Caller has a general question"},
        ],
    }


def _single_edge_decision_wf() -> dict:
    """Decision node with a single outgoing edge (no LLM call needed)."""
    return {
        "id": "wf_single_edge",
        "name": "Single Edge Decision",
        "version": 1,
        "entry_node_id": "greeting",
        "nodes": [
            {
                "id": "greeting",
                "type": "conversation",
                "data": {
                    "instructions": "Greet the caller.",
                    "max_iterations": 2,
                },
            },
            {
                "id": "gate",
                "type": "decision",
                "data": {
                    "instruction": "Route to the only available option.",
                },
            },
            {
                "id": "next",
                "type": "conversation",
                "data": {
                    "instructions": "Continue the conversation.",
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "greeting", "target": "gate", "label": "Done greeting"},
            {"id": "e2", "source": "gate", "target": "next", "label": "Only option"},
        ],
    }


# ---------------------------------------------------------------------------
# Decision node tests
# ---------------------------------------------------------------------------

class TestDecisionNode:
    async def test_decision_routes_to_correct_edge(self):
        """Router picks the correct edge at a decision node."""
        # Responses: greeting responder, STAY router (for handle_input), then
        # e1 router (for transition), summary, decision router → e2, booking responder
        responder = FakeLLM(["Hello!", "Welcome to booking!"])
        router = FakeLLM([
            "e1",                                                   # conversation router → transition to decision
            '{"summary": "Caller wants to book.", "key_info": {"intent": "booking"}}',  # summary
            "e2",                                                   # decision router → booking
        ])

        engine = WorkflowEngine(_decision_wf(), responder=responder, router=router)
        await engine.start()
        assert engine.current_node.id == "greeting"

        response, ended = await engine.handle_input("I'd like to book a cleaning")
        assert engine.current_node.id == "booking"
        assert "booking" in response.lower() or "Welcome" in response
        assert ended is False

    async def test_decision_no_matching_edge_falls_back_to_first(self):
        """Unknown decision edge falls back to first outgoing edge."""
        responder = FakeLLM(["Hello!", "Welcome to booking!"])
        router = FakeLLM([
            "e1",           # conversation router → transition to decision
            '{"summary": "Caller wants something.", "key_info": {}}',  # summary
            "GIBBERISH",    # decision router → unknown → falls back to first (e2 = booking)
        ])

        engine = WorkflowEngine(_decision_wf(), responder=responder, router=router)
        await engine.start()
        response, ended = await engine.handle_input("I need something")

        assert engine.current_node.id == "booking"  # fell back to first edge target
        assert ended is False

    async def test_decision_node_is_silent(self):
        """Decision node produces no spoken response to the caller."""
        responder = FakeLLM(["Hello!", "Welcome to booking!"])
        router = FakeLLM([
            "e1",
            '{"summary": "Caller wants to book.", "key_info": {}}',
            "e2",
        ])

        engine = WorkflowEngine(_decision_wf(), responder=responder, router=router)
        await engine.start()
        response, ended = await engine.handle_input("I'd like to book")

        # The response comes from the booking node's responder, not the decision node
        assert response == "Welcome to booking!"
        # Responder was called exactly twice: once for greeting, once for booking
        assert len(responder.calls) == 2

    async def test_multi_node_traversal_greeting_to_inquiry(self):
        """Greeting → decision → inquiry path works correctly."""
        responder = FakeLLM(["Hello!", "Here's our service info."])
        router = FakeLLM([
            "e1",
            '{"summary": "Caller has a question about prices.", "key_info": {"intent": "inquiry"}}',
            "e3",  # → inquiry
        ])

        engine = WorkflowEngine(_decision_wf(), responder=responder, router=router)
        await engine.start()
        response, ended = await engine.handle_input("How much is a cleaning?")

        assert engine.current_node.id == "inquiry"
        assert response == "Here's our service info."

    async def test_context_accumulation_across_nodes(self):
        """Summaries from greeting are passed to the node after the decision."""
        responder = FakeLLM(["Hello!", "Let me help."])
        router = FakeLLM([
            "e1",
            '{"summary": "Caller wants to book. Name is John.", "key_info": {"name": "John"}}',
            "e2",
        ])

        engine = WorkflowEngine(_decision_wf(), responder=responder, router=router)
        await engine.start()
        await engine.handle_input("I'm John and I want to book")

        # Booking node's responder should have received summary context
        booking_messages = responder.calls[1]
        system_msg = booking_messages[0]["content"]
        assert "Caller wants to book" in system_msg or "John" in system_msg

    async def test_summary_generated_on_transition(self):
        """Summary is generated when leaving a conversation node (not decision)."""
        responder = FakeLLM(["Hello!", "Booking time!"])
        router = FakeLLM([
            "e1",
            '{"summary": "Caller called about booking.", "key_info": {"intent": "book"}}',
            "e2",
        ])

        engine = WorkflowEngine(_decision_wf(), responder=responder, router=router)
        await engine.start()
        await engine.handle_input("Book please")

        assert len(engine.summaries) == 1
        assert engine.summaries[0].node_id == "greeting"
        assert "booking" in engine.summaries[0].summary.lower() or "book" in engine.summaries[0].summary.lower()

    async def test_fresh_chat_history_in_new_node(self):
        """New conversation node starts with fresh chat history."""
        responder = FakeLLM(["Hello!", "Welcome to booking!"])
        router = FakeLLM([
            "e1",
            '{"summary": "x", "key_info": {}}',
            "e2",
        ])

        engine = WorkflowEngine(_decision_wf(), responder=responder, router=router)
        await engine.start()
        await engine.handle_input("Book please")

        # The booking node's history should only have the assistant greeting (from booking)
        booking_history = engine._node_histories.get("booking", [])
        assert len(booking_history) == 1
        assert booking_history[0]["role"] == "assistant"
        assert booking_history[0]["content"] == "Welcome to booking!"

    async def test_decision_with_single_edge_skips_llm(self):
        """Decision node with one outgoing edge follows it without LLM call."""
        responder = FakeLLM(["Hello!", "Continuing!"])
        router = FakeLLM([
            "e1",  # conversation router → transition to decision gate
            '{"summary": "Greeting done.", "key_info": {}}',
            # NOTE: no decision router call expected — single edge
        ])

        engine = WorkflowEngine(_single_edge_decision_wf(), responder=responder, router=router)
        await engine.start()
        response, ended = await engine.handle_input("Hi there")

        assert engine.current_node.id == "next"
        assert response == "Continuing!"
        # Router was called only twice: conversation routing + summary
        # (no decision LLM call for single-edge decision)
        assert len(router.calls) == 2

    async def test_decision_node_no_outgoing_edges_raises(self):
        """Decision node with no outgoing edges raises WorkflowError."""
        wf = {
            "id": "wf_bad",
            "name": "Bad Decision",
            "version": 1,
            "entry_node_id": "d1",
            "nodes": [
                {
                    "id": "d1",
                    "type": "decision",
                    "data": {"instruction": "Route somewhere."},
                },
            ],
            "edges": [],
        }
        responder = FakeLLM([])
        router = FakeLLM([])

        engine = WorkflowEngine(wf, responder=responder, router=router)
        with pytest.raises(WorkflowError, match="no outgoing edges"):
            await engine.start()

    async def test_decision_router_receives_accumulated_context(self):
        """Decision router is called with summaries from prior nodes."""
        responder = FakeLLM(["Hello!", "Booking node."])
        router = FakeLLM([
            "e1",
            '{"summary": "Caller is John, wants a cleaning.", "key_info": {"name": "John"}}',
            "e2",
        ])

        engine = WorkflowEngine(_decision_wf(), responder=responder, router=router)
        await engine.start()
        await engine.handle_input("I'm John, I want a cleaning")

        # The decision router call (3rd call) should contain the summary context
        decision_call = router.calls[2]
        system_msg = decision_call[0]["content"]
        assert "John" in system_msg
        assert "cleaning" in system_msg


# ---------------------------------------------------------------------------
# Action node workflow fixtures
# ---------------------------------------------------------------------------

def _action_end_call_wf() -> dict:
    """Greeting → end_call action."""
    return {
        "id": "wf_end",
        "name": "End Call Flow",
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
            {
                "id": "end",
                "type": "action",
                "data": {
                    "action_type": "end_call",
                    "message": "Thank you for calling! Goodbye.",
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "greeting", "target": "end", "label": "Conversation done"},
        ],
    }


def _action_transfer_wf() -> dict:
    """Greeting → transfer action."""
    return {
        "id": "wf_transfer",
        "name": "Transfer Flow",
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
            {
                "id": "xfer",
                "type": "action",
                "data": {
                    "action_type": "transfer",
                    "target_number": "+447908121095",
                    "announcement": "I'll connect you now.",
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "greeting", "target": "xfer", "label": "Wants to speak to human"},
        ],
    }


def _decision_to_action_wf() -> dict:
    """Greeting → Decision → end_call / transfer."""
    return {
        "id": "wf_d2a",
        "name": "Decision to Action",
        "version": 1,
        "entry_node_id": "greeting",
        "nodes": [
            {
                "id": "greeting",
                "type": "conversation",
                "data": {"instructions": "Greet.", "max_iterations": 3},
            },
            {
                "id": "router",
                "type": "decision",
                "data": {"instruction": "End or transfer?"},
            },
            {
                "id": "end",
                "type": "action",
                "data": {"action_type": "end_call", "message": "Bye!"},
            },
            {
                "id": "xfer",
                "type": "action",
                "data": {
                    "action_type": "transfer",
                    "target_number": "+441234",
                    "announcement": "Connecting...",
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "greeting", "target": "router", "label": "Done"},
            {"id": "e2", "source": "router", "target": "end", "label": "End call"},
            {"id": "e3", "source": "router", "target": "xfer", "label": "Transfer"},
        ],
    }


# ---------------------------------------------------------------------------
# Action node tests
# ---------------------------------------------------------------------------

class TestActionNodeEndCall:
    async def test_end_call_returns_action_result(self):
        """Transitioning to end_call returns ActionResult with call_ended=True."""
        responder = FakeLLM(["Hello!"])
        router = FakeLLM([
            "e1",  # transition to end action
            '{"summary": "Greeting done.", "key_info": {}}',
        ])

        engine = WorkflowEngine(_action_end_call_wf(), responder=responder, router=router)
        await engine.start()

        result, ended = await engine.handle_input("Goodbye")
        assert isinstance(result, ActionResult)
        assert result.action_type == "end_call"
        assert result.message == "Thank you for calling! Goodbye."
        assert result.call_ended is True
        assert ended is True

    async def test_end_call_ignores_outgoing_edges(self):
        """end_call is terminal — no further transitions."""
        wf = _action_end_call_wf()
        # Add a spurious edge from end node
        wf["edges"].append(
            {"id": "e_spurious", "source": "end", "target": "greeting", "label": "Loop back"}
        )

        responder = FakeLLM(["Hello!"])
        router = FakeLLM([
            "e1",
            '{"summary": "Done.", "key_info": {}}',
        ])

        engine = WorkflowEngine(wf, responder=responder, router=router)
        await engine.start()

        result, ended = await engine.handle_input("Bye")
        # Still returns ActionResult — edges after end_call are ignored
        assert isinstance(result, ActionResult)
        assert result.call_ended is True


class TestActionNodeTransfer:
    async def test_transfer_returns_action_result(self):
        """Transitioning to transfer returns ActionResult with transfer_number."""
        responder = FakeLLM(["Hello!"])
        router = FakeLLM([
            "e1",
            '{"summary": "Wants human.", "key_info": {}}',
        ])

        engine = WorkflowEngine(_action_transfer_wf(), responder=responder, router=router)
        await engine.start()

        result, ended = await engine.handle_input("I want to talk to a person")
        assert isinstance(result, ActionResult)
        assert result.action_type == "transfer"
        assert result.message == "I'll connect you now."
        assert result.transfer_number == "+447908121095"
        assert result.call_ended is False
        assert ended is False


class TestDecisionToAction:
    async def test_decision_routes_to_end_call(self):
        """Decision node → end_call action."""
        responder = FakeLLM(["Hello!"])
        router = FakeLLM([
            "e1",  # conversation router → transition to decision
            '{"summary": "Done.", "key_info": {}}',
            "e2",  # decision router → end_call
        ])

        engine = WorkflowEngine(_decision_to_action_wf(), responder=responder, router=router)
        await engine.start()

        result, ended = await engine.handle_input("I'm done")
        assert isinstance(result, ActionResult)
        assert result.action_type == "end_call"
        assert result.call_ended is True

    async def test_decision_routes_to_transfer(self):
        """Decision node → transfer action."""
        responder = FakeLLM(["Hello!"])
        router = FakeLLM([
            "e1",
            '{"summary": "Wants agent.", "key_info": {}}',
            "e3",  # decision router → transfer
        ])

        engine = WorkflowEngine(_decision_to_action_wf(), responder=responder, router=router)
        await engine.start()

        result, ended = await engine.handle_input("Connect me to someone")
        assert isinstance(result, ActionResult)
        assert result.action_type == "transfer"
        assert result.transfer_number == "+441234"
        assert result.call_ended is False


class TestActionNodeEntry:
    async def test_action_as_entry_node(self):
        """Action node as entry node returns ActionResult immediately."""
        wf = {
            "id": "wf_instant_end",
            "name": "Instant End",
            "version": 1,
            "entry_node_id": "end",
            "nodes": [
                {
                    "id": "end",
                    "type": "action",
                    "data": {"action_type": "end_call", "message": "We're closed."},
                },
            ],
            "edges": [],
        }
        responder = FakeLLM([])
        router = FakeLLM([])

        engine = WorkflowEngine(wf, responder=responder, router=router)
        result = await engine.start()
        assert isinstance(result, ActionResult)
        assert result.action_type == "end_call"
        assert result.message == "We're closed."
        assert result.call_ended is True

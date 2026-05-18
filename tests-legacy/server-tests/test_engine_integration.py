"""Tests for integration action handling in the workflow engine."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workflow.engine import ActionResult, WorkflowEngine


def _integration_workflow() -> dict[str, Any]:
    """Workflow: greeting → integration action → follow-up."""
    return {
        "id": "wf_int",
        "name": "Integration Workflow",
        "version": 1,
        "entry_node_id": "greeting",
        "nodes": [
            {
                "id": "greeting",
                "type": "conversation",
                "data": {"instructions": "Greet the caller and ask what they need."},
            },
            {
                "id": "check_cal",
                "type": "action",
                "data": {
                    "action_type": "integration",
                    "integration_id": "int-001",
                    "integration_action": "check_availability",
                    "integration_message": "Let me check that for you.",
                    "integration_params": {"calendar_id": "primary"},
                },
            },
            {
                "id": "follow_up",
                "type": "conversation",
                "data": {"instructions": "Share the results and help the caller."},
            },
        ],
        "edges": [
            {"id": "e1", "source": "greeting", "target": "check_cal", "label": "Caller wants to check calendar"},
            {"id": "e2", "source": "check_cal", "target": "follow_up", "label": "After checking"},
        ],
    }


class TestEngineIntegrationAction:
    """Test that the engine correctly handles integration action nodes."""

    @pytest.mark.anyio
    async def test_execute_action_returns_hold_message(self):
        """When the engine reaches an integration node, it returns the hold message."""
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value="Hello! How can I help?")

        engine = WorkflowEngine(
            _integration_workflow(),
            responder=mock_llm,
            router=mock_llm,
        )
        await engine.start()

        # Simulate router deciding to transition to the integration node
        mock_llm.chat = AsyncMock(return_value="e1")
        result, ended = await engine.handle_input("I want to check my calendar")

        # Should get an ActionResult for the integration
        assert isinstance(result, ActionResult)
        assert result.action_type == "integration"
        assert result.message == "Let me check that for you."
        assert result.call_ended is False

    @pytest.mark.anyio
    async def test_run_integration_dispatches_and_transitions(self):
        """run_integration should call the handler and transition to next node."""
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value="Hello! How can I help?")

        engine = WorkflowEngine(
            _integration_workflow(),
            responder=mock_llm,
            router=mock_llm,
        )
        await engine.start()

        # Transition to integration node
        mock_llm.chat = AsyncMock(return_value="e1")
        await engine.handle_input("Check my calendar please")

        # Now run the integration with mocked dispatch
        mock_result = {"busy_slots": [], "busy_count": 0, "success": True}
        with patch.object(
            engine,
            "_dispatch_integration",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await engine.run_integration(db_session=MagicMock())

        assert isinstance(result, ActionResult)
        assert result.action_type == "integration"
        assert result.integration_result == mock_result
        # Should have auto-transitioned to follow_up node
        assert engine.current_node.id == "follow_up"

    @pytest.mark.anyio
    async def test_run_integration_error_injected_as_context(self):
        """If the integration fails, error is injected as context."""
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value="Hello!")

        engine = WorkflowEngine(
            _integration_workflow(),
            responder=mock_llm,
            router=mock_llm,
        )
        await engine.start()

        mock_llm.chat = AsyncMock(return_value="e1")
        await engine.handle_input("Check calendar")

        with patch.object(
            engine,
            "_dispatch_integration",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API down"),
        ):
            result = await engine.run_integration(db_session=MagicMock())

        assert result.integration_result is not None
        assert result.integration_result.get("success") is False
        assert "API down" in result.integration_result.get("error", "")
        # Should still transition to follow_up
        assert engine.current_node.id == "follow_up"

    @pytest.mark.anyio
    async def test_existing_action_types_unaffected(self):
        """end_call and transfer actions still work correctly."""
        wf = {
            "id": "wf_ec",
            "name": "End Call",
            "version": 1,
            "entry_node_id": "greeting",
            "nodes": [
                {
                    "id": "greeting",
                    "type": "conversation",
                    "data": {"instructions": "Greet."},
                },
                {
                    "id": "end",
                    "type": "action",
                    "data": {
                        "action_type": "end_call",
                        "message": "Goodbye!",
                    },
                },
            ],
            "edges": [
                {"id": "e1", "source": "greeting", "target": "end", "label": "Done"},
            ],
        }

        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value="Hi there!")
        engine = WorkflowEngine(wf, responder=mock_llm, router=mock_llm)
        await engine.start()

        mock_llm.chat = AsyncMock(return_value="e1")
        result, ended = await engine.handle_input("bye")
        assert isinstance(result, ActionResult)
        assert result.action_type == "end_call"
        assert result.call_ended is True

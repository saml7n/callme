"""Tests for integration action types in the workflow schema."""

import pytest

from app.workflow.schema import ActionNodeData, ActionType, Workflow


class TestIntegrationActionSchema:
    """Validate the new integration action type in the schema."""

    def test_integration_action_type_exists(self):
        assert ActionType.integration == "integration"

    def test_valid_integration_action(self):
        data = ActionNodeData(
            action_type=ActionType.integration,
            integration_id="00000000-0000-0000-0000-000000000001",
            integration_action="check_availability",
        )
        assert data.integration_id == "00000000-0000-0000-0000-000000000001"
        assert data.integration_action == "check_availability"
        assert data.integration_message == "One moment please while I check that for you."

    def test_integration_missing_id_raises(self):
        with pytest.raises(ValueError, match="integration_id"):
            ActionNodeData(
                action_type=ActionType.integration,
                integration_id="",
                integration_action="check_availability",
            )

    def test_integration_missing_action_raises(self):
        with pytest.raises(ValueError, match="integration_action"):
            ActionNodeData(
                action_type=ActionType.integration,
                integration_id="some-id",
                integration_action="",
            )

    def test_integration_custom_params(self):
        data = ActionNodeData(
            action_type=ActionType.integration,
            integration_id="abc",
            integration_action="call_webhook",
            integration_params={"extra": "stuff"},
            integration_message="Please hold.",
        )
        assert data.integration_params == {"extra": "stuff"}
        assert data.integration_message == "Please hold."

    def test_workflow_with_integration_action_node(self):
        """A full workflow graph containing an integration action node validates."""
        wf_dict = {
            "id": "wf_int",
            "name": "Integration Test",
            "version": 1,
            "entry_node_id": "greeting",
            "nodes": [
                {
                    "id": "greeting",
                    "type": "conversation",
                    "data": {"instructions": "Greet caller."},
                },
                {
                    "id": "check_cal",
                    "type": "action",
                    "data": {
                        "action_type": "integration",
                        "integration_id": "int-001",
                        "integration_action": "check_availability",
                        "integration_message": "Let me check that for you.",
                    },
                },
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "greeting",
                    "target": "check_cal",
                    "label": "Caller wants to book",
                },
            ],
        }
        wf = Workflow(**wf_dict)
        assert wf.get_node("check_cal").get_action_data().action_type == ActionType.integration

    def test_end_call_and_transfer_still_work(self):
        """Existing action types are not broken."""
        end = ActionNodeData(action_type=ActionType.end_call, message="Goodbye!")
        assert end.action_type == ActionType.end_call
        assert end.message == "Goodbye!"

        transfer = ActionNodeData(
            action_type=ActionType.transfer,
            target_number="+1234567890",
            announcement="Transferring you now.",
        )
        assert transfer.target_number == "+1234567890"

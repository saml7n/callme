"""Tests for the workflow schema validation."""

import pytest

from app.workflow.schema import (
    ConversationNodeData,
    DecisionNodeData,
    NodeType,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)


# ---------------------------------------------------------------------------
# Helpers — minimal valid workflow dicts
# ---------------------------------------------------------------------------

def _single_node_workflow(**overrides) -> dict:
    """Return a minimal valid single-node workflow dict."""
    wf = {
        "id": "wf_1",
        "name": "Test",
        "version": 1,
        "entry_node_id": "n1",
        "nodes": [
            {
                "id": "n1",
                "type": "conversation",
                "data": {
                    "instructions": "Greet the caller.",
                },
            }
        ],
        "edges": [],
    }
    wf.update(overrides)
    return wf


def _two_node_workflow() -> dict:
    return {
        "id": "wf_2",
        "name": "Two Nodes",
        "version": 1,
        "entry_node_id": "n1",
        "nodes": [
            {
                "id": "n1",
                "type": "conversation",
                "data": {"instructions": "Greet caller."},
            },
            {
                "id": "n2",
                "type": "conversation",
                "data": {"instructions": "Help with booking."},
            },
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "label": "Caller wants to book"},
        ],
    }


# ---------------------------------------------------------------------------
# Valid workflow tests
# ---------------------------------------------------------------------------

class TestWorkflowValid:
    def test_single_node_workflow_parses(self):
        wf = Workflow(**_single_node_workflow())
        assert wf.id == "wf_1"
        assert len(wf.nodes) == 1
        assert wf.entry_node_id == "n1"

    def test_two_node_workflow_parses(self):
        wf = Workflow(**_two_node_workflow())
        assert len(wf.nodes) == 2
        assert len(wf.edges) == 1

    def test_get_node(self):
        wf = Workflow(**_two_node_workflow())
        node = wf.get_node("n2")
        assert node.id == "n2"

    def test_get_outgoing_edges(self):
        wf = Workflow(**_two_node_workflow())
        edges = wf.get_outgoing_edges("n1")
        assert len(edges) == 1
        assert edges[0].target == "n2"

    def test_no_outgoing_edges(self):
        wf = Workflow(**_two_node_workflow())
        edges = wf.get_outgoing_edges("n2")
        assert edges == []


# ---------------------------------------------------------------------------
# Conversation node data
# ---------------------------------------------------------------------------

class TestConversationNodeData:
    def test_defaults(self):
        data = ConversationNodeData(instructions="Hello")
        assert data.max_iterations == 10
        assert data.examples == []

    def test_custom_values(self):
        data = ConversationNodeData(
            instructions="Help with booking.",
            examples=[{"role": "user", "content": "Hi"}],
            max_iterations=5,
        )
        assert data.max_iterations == 5
        assert len(data.examples) == 1

    def test_empty_instructions_rejected(self):
        with pytest.raises(Exception):
            ConversationNodeData(instructions="")


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

class TestWorkflowValidation:
    def test_missing_entry_node(self):
        with pytest.raises(Exception, match="entry_node_id"):
            Workflow(**_single_node_workflow(entry_node_id="nonexistent"))

    def test_dangling_edge_source(self):
        data = _two_node_workflow()
        data["edges"][0]["source"] = "ghost"
        with pytest.raises(Exception, match="ghost"):
            Workflow(**data)

    def test_dangling_edge_target(self):
        data = _two_node_workflow()
        data["edges"][0]["target"] = "ghost"
        with pytest.raises(Exception, match="ghost"):
            Workflow(**data)

    def test_empty_nodes_rejected(self):
        with pytest.raises(Exception):
            Workflow(
                id="w",
                name="Empty",
                version=1,
                entry_node_id="n1",
                nodes=[],
                edges=[],
            )

    def test_invalid_conversation_data(self):
        """Node with type=conversation but missing instructions → error."""
        data = _single_node_workflow()
        data["nodes"][0]["data"] = {}  # missing instructions
        with pytest.raises(Exception):
            Workflow(**data)

    def test_missing_required_fields(self):
        """Missing top-level fields → Pydantic error."""
        with pytest.raises(Exception):
            Workflow(id="w", name="X")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Decision node data
# ---------------------------------------------------------------------------

class TestDecisionNodeData:
    def test_valid_decision_data(self):
        data = DecisionNodeData(instruction="Determine caller intent.")
        assert data.instruction == "Determine caller intent."

    def test_empty_instruction_rejected(self):
        with pytest.raises(Exception):
            DecisionNodeData(instruction="")


# ---------------------------------------------------------------------------
# Decision node in workflow
# ---------------------------------------------------------------------------

class TestDecisionNodeWorkflow:
    def test_workflow_with_decision_node_parses(self):
        wf = Workflow(**{
            "id": "wf_d",
            "name": "Decision Test",
            "version": 1,
            "entry_node_id": "n1",
            "nodes": [
                {"id": "n1", "type": "conversation", "data": {"instructions": "Greet."}},
                {"id": "d1", "type": "decision", "data": {"instruction": "Route."}},
                {"id": "n2", "type": "conversation", "data": {"instructions": "Book."}},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "d1", "label": "Done greeting"},
                {"id": "e2", "source": "d1", "target": "n2", "label": "Book"},
            ],
        })
        assert len(wf.nodes) == 3
        assert wf.nodes[1].type == NodeType.decision

    def test_decision_node_get_decision_data(self):
        node = WorkflowNode(
            id="d1",
            type=NodeType.decision,
            data={"instruction": "Evaluate intent."},
        )
        d = node.get_decision_data()
        assert d.instruction == "Evaluate intent."

    def test_decision_node_invalid_data_raises(self):
        """Decision node with missing instruction → validation error."""
        with pytest.raises(Exception):
            Workflow(**{
                "id": "wf_bad",
                "name": "Bad",
                "version": 1,
                "entry_node_id": "d1",
                "nodes": [
                    {"id": "d1", "type": "decision", "data": {}},
                ],
                "edges": [],
            })

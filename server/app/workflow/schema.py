"""Workflow schema — Pydantic models for validating workflow JSON definitions."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class NodeType(str, Enum):
    """Supported workflow node types."""

    conversation = "conversation"
    decision = "decision"
    action = "action"


class ConversationNodeData(BaseModel):
    """Data payload for a conversation node."""

    instructions: str = Field(
        ..., min_length=1, description="System prompt / personality for this node."
    )
    examples: list[dict[str, str]] = Field(
        default_factory=list,
        description="Few-shot examples injected into the message history.",
    )
    max_iterations: int = Field(
        default=10, ge=1, description="Max conversation turns before forcing transition."
    )


class DecisionNodeData(BaseModel):
    """Data payload for a decision node (pure routing, no caller interaction)."""

    instruction: str = Field(
        ...,
        min_length=1,
        description="Guidance for the Router LLM on what to evaluate.",
    )


class ActionType(str, Enum):
    """Supported action node types (extensible)."""

    end_call = "end_call"
    transfer = "transfer"


class ActionNodeData(BaseModel):
    """Data payload for an action node (performs a side effect)."""

    action_type: ActionType

    # end_call fields
    message: str = Field(
        default="",
        description="Closing message to speak before hanging up (end_call only).",
    )

    # transfer fields
    target_number: str = Field(
        default="",
        description="Phone number to transfer the call to (transfer only).",
    )
    announcement: str = Field(
        default="",
        description="Message to speak before transferring (transfer only).",
    )

    @model_validator(mode="after")
    def validate_action_fields(self) -> ActionNodeData:
        """Ensure required fields are provided for each action type."""
        if self.action_type == ActionType.end_call:
            if not self.message:
                raise ValueError("end_call action requires a non-empty 'message'.")
        elif self.action_type == ActionType.transfer:
            if not self.target_number:
                raise ValueError("transfer action requires a non-empty 'target_number'.")
            if not self.announcement:
                raise ValueError("transfer action requires a non-empty 'announcement'.")
        return self


class Position(BaseModel):
    """Visual position of a node in the workflow builder."""

    x: float = 0.0
    y: float = 0.0


class WorkflowNode(BaseModel):
    """A single node in the workflow graph."""

    id: str = Field(..., min_length=1, description="Unique node identifier.")
    type: NodeType
    data: dict[str, Any] = Field(
        ..., description="Type-specific configuration (validated per node type)."
    )
    position: Position = Field(default_factory=Position)

    def get_conversation_data(self) -> ConversationNodeData:
        """Parse and validate data as ConversationNodeData."""
        return ConversationNodeData(**self.data)

    def get_decision_data(self) -> DecisionNodeData:
        """Parse and validate data as DecisionNodeData."""
        return DecisionNodeData(**self.data)

    def get_action_data(self) -> ActionNodeData:
        """Parse and validate data as ActionNodeData."""
        return ActionNodeData(**self.data)


class WorkflowEdge(BaseModel):
    """A directed edge connecting two nodes."""

    id: str = Field(..., min_length=1, description="Unique edge identifier.")
    source: str = Field(..., min_length=1, description="Source node ID.")
    target: str = Field(..., min_length=1, description="Target node ID.")
    label: str = Field(
        ...,
        min_length=1,
        description="Plain English description of when to follow this edge.",
    )


class Workflow(BaseModel):
    """Complete workflow definition — a directed graph of nodes and edges."""

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    version: int = Field(default=1, ge=1)
    entry_node_id: str = Field(..., min_length=1)
    nodes: list[WorkflowNode] = Field(..., min_length=1)
    edges: list[WorkflowEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> Workflow:
        """Validate graph integrity: entry node exists, edge references are valid."""
        node_ids = {n.id for n in self.nodes}

        # Entry node must exist
        if self.entry_node_id not in node_ids:
            raise ValueError(
                f"entry_node_id '{self.entry_node_id}' does not match any node. "
                f"Available nodes: {sorted(node_ids)}"
            )

        # All edge sources and targets must reference existing nodes
        for edge in self.edges:
            if edge.source not in node_ids:
                raise ValueError(
                    f"Edge '{edge.id}' references source '{edge.source}' "
                    f"which does not exist. Available nodes: {sorted(node_ids)}"
                )
            if edge.target not in node_ids:
                raise ValueError(
                    f"Edge '{edge.id}' references target '{edge.target}' "
                    f"which does not exist. Available nodes: {sorted(node_ids)}"
                )

        # Validate node-type-specific data
        for node in self.nodes:
            if node.type == NodeType.conversation:
                node.get_conversation_data()  # raises on invalid data
            elif node.type == NodeType.decision:
                node.get_decision_data()  # raises on invalid data
            elif node.type == NodeType.action:
                node.get_action_data()  # raises on invalid data

        return self

    def get_node(self, node_id: str) -> WorkflowNode:
        """Lookup a node by ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise ValueError(f"Node '{node_id}' not found in workflow '{self.id}'")

    def get_outgoing_edges(self, node_id: str) -> list[WorkflowEdge]:
        """Return all edges originating from the given node."""
        return [e for e in self.edges if e.source == node_id]

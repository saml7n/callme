"""Workflow engine — state machine that drives a call through a workflow graph.

Uses two LLM roles:
- **Router LLM** (GPT-4o-mini): decides STAY or which edge to follow.
- **Responder LLM** (GPT-4o): generates the natural language reply.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.llm.openai import LLMClient
from app.workflow.schema import (
    ConversationNodeData,
    NodeType,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)

logger = logging.getLogger(__name__)


class WorkflowError(Exception):
    """Raised on workflow engine errors."""


@dataclass
class NodeSummary:
    """Summary of a conversation node's interaction, carried forward on transition."""

    node_id: str
    node_name: str
    summary: str
    key_info: dict[str, Any] = field(default_factory=dict)


ROUTER_SYSTEM_PROMPT = """\
You are a routing assistant for a phone call workflow. Your ONLY job is to decide whether the conversation should STAY on the current node or TRANSITION to another node via one of the available edges.

Current node: "{node_id}"
Node instructions: "{instructions}"

Available edges (transitions):
{edges_text}

Rules:
- If the conversation should continue on the current node, respond with exactly: STAY
- If the conversation should transition, respond with exactly the edge ID (e.g. "e1")
- Respond with ONLY "STAY" or an edge ID — nothing else.
- If no edges are available, always respond with STAY.
"""

SUMMARY_PROMPT = """\
Summarise the following conversation from a phone call node concisely. Extract key information points (names, dates, intents, preferences, numbers, etc.).

Node purpose: {instructions}

Conversation:
{conversation}

Respond in JSON format:
{{"summary": "Brief summary of what happened", "key_info": {{"key": "value", ...}}}}
"""

RESPONDER_CONTEXT_PREFIX = """\
Context from the call so far:
{summaries_text}

---
"""


class WorkflowEngine:
    """State machine that drives a call through a workflow graph.

    Usage::

        engine = WorkflowEngine(workflow_dict, responder_llm, router_llm)
        greeting = await engine.start()
        response, ended = await engine.handle_input("I'd like to book...")
    """

    def __init__(
        self,
        workflow: dict[str, Any],
        responder: LLMClient | None = None,
        router: LLMClient | None = None,
    ) -> None:
        self._workflow = Workflow(**workflow)
        self._responder = responder or LLMClient()
        self._router = router or LLMClient(model="gpt-4o-mini")

        self._current_node: WorkflowNode = self._workflow.get_node(
            self._workflow.entry_node_id
        )
        self._node_histories: dict[str, list[dict[str, str]]] = {}
        self._summaries: list[NodeSummary] = []
        self._iteration_count: int = 0

    @property
    def current_node(self) -> WorkflowNode:
        """The node the engine is currently on."""
        return self._current_node

    @property
    def summaries(self) -> list[NodeSummary]:
        """Accumulated node summaries (read-only snapshot)."""
        return list(self._summaries)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> str:
        """Enter the entry node and return an initial response."""
        self._enter_node(self._current_node)
        response = await self._call_responder()
        self._append_history("assistant", response)
        logger.info("Engine started at node '%s': %s", self._current_node.id, response)
        return response

    async def handle_input(self, transcript: str) -> tuple[str, bool]:
        """Process caller input and return (response_text, call_ended).

        Steps:
        1. Append transcript to current node's chat history.
        2. Router LLM: STAY or transition?
        3. If STAY → Responder generates reply.
        4. If transition → summarise, move to new node, Responder generates reply.
        """
        self._append_history("user", transcript)
        self._iteration_count += 1

        # Check max_iterations
        outgoing = self._workflow.get_outgoing_edges(self._current_node.id)
        conv_data = self._current_node.get_conversation_data()
        if self._iteration_count >= conv_data.max_iterations and outgoing:
            logger.info(
                "Max iterations (%d) reached at node '%s' — forcing transition",
                conv_data.max_iterations,
                self._current_node.id,
            )
            return await self._transition(outgoing[0])

        # Ask Router
        decision = await self._call_router(outgoing)

        if decision == "STAY" or not outgoing:
            response = await self._call_responder()
            self._append_history("assistant", response)
            logger.info("Router: STAY at '%s'", self._current_node.id)
            return response, False

        # Find the matching edge
        edge = self._find_edge(decision, outgoing)
        if edge is None:
            # Router returned something unexpected — stay
            logger.warning(
                "Router returned unknown decision '%s' — staying at '%s'",
                decision,
                self._current_node.id,
            )
            response = await self._call_responder()
            self._append_history("assistant", response)
            return response, False

        return await self._transition(edge)

    # ------------------------------------------------------------------
    # Router LLM
    # ------------------------------------------------------------------

    async def _call_router(self, outgoing_edges: list[WorkflowEdge]) -> str:
        """Ask the Router LLM whether to STAY or follow an edge."""
        if not outgoing_edges:
            return "STAY"

        conv_data = self._current_node.get_conversation_data()
        edges_text = "\n".join(
            f'- Edge "{e.id}": {e.label}' for e in outgoing_edges
        )
        system = ROUTER_SYSTEM_PROMPT.format(
            node_id=self._current_node.id,
            instructions=conv_data.instructions,
            edges_text=edges_text,
        )

        history = self._get_history()
        messages = [{"role": "system", "content": system}] + history

        result = await self._router.chat(messages)
        decision = result.strip().strip('"').strip("'")
        logger.info("Router decision: %s", decision)
        return decision

    # ------------------------------------------------------------------
    # Responder LLM
    # ------------------------------------------------------------------

    async def _call_responder(self) -> str:
        """Generate a response from the Responder LLM."""
        conv_data = self._current_node.get_conversation_data()
        messages = self._build_responder_messages(conv_data)
        response = await self._responder.chat(messages)
        return response.strip()

    def _build_responder_messages(
        self, conv_data: ConversationNodeData
    ) -> list[dict[str, str]]:
        """Build the full message list for the Responder LLM."""
        messages: list[dict[str, str]] = []

        # System prompt: accumulated summaries + node instructions
        system_parts: list[str] = []
        if self._summaries:
            summaries_text = "\n\n".join(
                f"[{s.node_name}] {s.summary}"
                + (f" | Key info: {json.dumps(s.key_info)}" if s.key_info else "")
                for s in self._summaries
            )
            system_parts.append(
                RESPONDER_CONTEXT_PREFIX.format(summaries_text=summaries_text)
            )
        system_parts.append(conv_data.instructions)
        system_parts.append(
            "\nKeep responses concise — 1-2 sentences at a time."
        )
        messages.append({"role": "system", "content": "\n".join(system_parts)})

        # Few-shot examples
        for ex in conv_data.examples:
            messages.append({"role": ex["role"], "content": ex["content"]})

        # Current node's chat history
        messages.extend(self._get_history())

        return messages

    # ------------------------------------------------------------------
    # Transitions & Summaries
    # ------------------------------------------------------------------

    async def _transition(self, edge: WorkflowEdge) -> tuple[str, bool]:
        """Transition to a new node via the given edge."""
        old_node = self._current_node
        new_node = self._workflow.get_node(edge.target)

        # Generate summary of outgoing node
        summary = await self._generate_summary()
        self._summaries.append(summary)
        logger.info(
            "Transition: '%s' → '%s' via edge '%s'. Summary: %s",
            old_node.id,
            new_node.id,
            edge.id,
            summary.summary,
        )

        # Enter new node
        self._current_node = new_node
        self._iteration_count = 0
        self._enter_node(new_node)

        # Generate first response in new node
        response = await self._call_responder()
        self._append_history("assistant", response)

        return response, False

    async def _generate_summary(self) -> NodeSummary:
        """Generate a summary of the current node's conversation via LLM."""
        conv_data = self._current_node.get_conversation_data()
        history = self._get_history()

        if not history:
            return NodeSummary(
                node_id=self._current_node.id,
                node_name=self._current_node.id,
                summary="No conversation occurred.",
                key_info={},
            )

        conversation_text = "\n".join(
            f"{m['role'].title()}: {m['content']}" for m in history
        )
        prompt = SUMMARY_PROMPT.format(
            instructions=conv_data.instructions,
            conversation=conversation_text,
        )

        result = await self._router.chat([{"role": "user", "content": prompt}])

        try:
            parsed = json.loads(result)
            return NodeSummary(
                node_id=self._current_node.id,
                node_name=self._current_node.id,
                summary=parsed.get("summary", result),
                key_info=parsed.get("key_info", {}),
            )
        except (json.JSONDecodeError, TypeError):
            return NodeSummary(
                node_id=self._current_node.id,
                node_name=self._current_node.id,
                summary=result.strip(),
                key_info={},
            )

    # ------------------------------------------------------------------
    # Node history management
    # ------------------------------------------------------------------

    def _enter_node(self, node: WorkflowNode) -> None:
        """Initialise a fresh chat history for the given node."""
        if node.id not in self._node_histories:
            self._node_histories[node.id] = []

    def _append_history(self, role: str, content: str) -> None:
        """Append a message to the current node's chat history."""
        self._node_histories.setdefault(self._current_node.id, []).append(
            {"role": role, "content": content}
        )

    def _get_history(self) -> list[dict[str, str]]:
        """Return the current node's chat history."""
        return self._node_histories.get(self._current_node.id, [])

    def _find_edge(
        self, edge_id: str, edges: list[WorkflowEdge]
    ) -> WorkflowEdge | None:
        """Find an edge by ID from a list."""
        for e in edges:
            if e.id == edge_id:
                return e
        return None

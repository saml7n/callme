"""Workflow engine — state machine that drives a call through a workflow graph.

Uses two LLM roles:
- **Router LLM** (GPT-4o-mini): decides STAY or which edge to follow.
- **Responder LLM** (GPT-4o): generates the natural language reply.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.llm.openai import LLMClient
from app.workflow.schema import (
    ActionNodeData,
    ActionType,
    ConversationNodeData,
    DecisionNodeData,
    NodeType,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)

logger = logging.getLogger(__name__)


class WorkflowError(Exception):
    """Raised on workflow engine errors."""


@dataclass
class ActionResult:
    """Result returned when the engine enters an action node."""

    action_type: str
    message: str  # text to speak before performing the action
    call_ended: bool = False  # True for end_call
    transfer_number: str = ""  # phone number for transfer


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

DECISION_ROUTER_PROMPT = """\
You are a routing assistant for a phone call workflow. You are at a decision node that must route the call to the correct next step.

Decision instruction: "{instruction}"

Context from the call so far:
{context}

The caller's most recent message (this is what triggered the routing decision):
"{last_utterance}"

Available edges (transitions):
{edges_text}

Rules:
- Focus primarily on the caller's MOST RECENT message to determine their current intent.
- Prior context is background information — the latest utterance reflects what the caller wants NOW.
- Respond with ONLY the edge ID (e.g. "e1") — nothing else.
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
        self._lock = asyncio.Lock()

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

    async def start(self) -> str | ActionResult:
        """Enter the entry node and return an initial response.

        If the entry node is a decision node, silently route through it
        until we reach a conversation node.
        Returns a str for conversation nodes, or ActionResult for action nodes.
        """
        self._enter_node(self._current_node)

        # If entry is a decision node, route through it first
        if self._current_node.type == NodeType.decision:
            return await self._route_through_decisions()

        # If entry is an action node, execute it immediately
        if self._current_node.type == NodeType.action:
            return self._execute_action()

        response = await self._call_responder()
        self._append_history("assistant", response)
        logger.info("Engine started at node '%s': %s", self._current_node.id, response)
        return response

    async def handle_input(self, transcript: str) -> tuple[str | ActionResult, bool]:
        """Process caller input and return (response_text, call_ended).

        Steps:
        1. Append transcript to current node's chat history.
        2. Router LLM: STAY or transition?
        3. If STAY → Responder generates reply.
        4. If transition → summarise, move to new node, Responder generates reply.

        Uses a lock to prevent concurrent calls from interleaving with
        in-flight transitions (e.g. decision node routing).

        The response may be a str (conversation) or ActionResult (action node).
        """
        async with self._lock:
            # If we're on a decision node (transition was interrupted or
            # a previous call left us here), route through it first.
            if self._current_node.type == NodeType.decision:
                logger.info(
                    "handle_input called on decision node '%s' — routing through first",
                    self._current_node.id,
                )
                result = await self._route_through_decisions()
                if isinstance(result, ActionResult):
                    return result, result.call_ended
                # Now we're on a conversation node — add the transcript and continue
                self._append_history("user", transcript)
                self._iteration_count += 1
            else:
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

        # System prompt: accumulated summaries + node instructions + examples
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

        # Embed few-shot examples in the system prompt so the LLM treats them
        # as style guidance rather than actual conversation history.
        if conv_data.examples:
            example_lines = ["\nExample exchanges (for tone and style):"]
            for ex in conv_data.examples:
                role_label = "Caller" if ex["role"] == "user" else "You"
                example_lines.append(f"  {role_label}: {ex['content']}")
            system_parts.append("\n".join(example_lines))

        # Scope enforcement: if the node has outgoing edges, tell the LLM
        # to stay within its defined boundaries.
        outgoing = self._workflow.get_outgoing_edges(self._current_node.id)
        if outgoing:
            scope_lines = [
                "\nIMPORTANT — Scope boundaries:",
                "You are ONLY responsible for the topic described above.",
                "If the caller asks about something outside your scope, do NOT attempt to answer it.",
                "Instead, briefly acknowledge their request and say you'll get them to the right place.",
                "Topics outside your scope include:",
            ]
            for edge in outgoing:
                scope_lines.append(f"  - {edge.label}")
            system_parts.append("\n".join(scope_lines))

        system_parts.append(
            "\nKeep responses concise — 1-2 sentences at a time."
        )
        messages.append({"role": "system", "content": "\n".join(system_parts)})

        # Current node's chat history (fresh per node — no examples mixed in)
        messages.extend(self._get_history())

        return messages

    # ------------------------------------------------------------------
    # Transitions & Summaries
    # ------------------------------------------------------------------

    async def _transition(self, edge: WorkflowEdge) -> tuple[str | ActionResult, bool]:
        """Transition to a new node via the given edge.

        If the current node is a conversation node, generates a summary first.
        If the target node is a decision node, chains through decisions until
        a conversation node is reached.
        If the target node is an action node, executes the action immediately.
        """
        old_node = self._current_node
        new_node = self._workflow.get_node(edge.target)

        # Generate summary of outgoing node (only for conversation nodes)
        if old_node.type == NodeType.conversation:
            summary = await self._generate_summary()
            self._summaries.append(summary)
            logger.info(
                "Transition: '%s' → '%s' via edge '%s'. Summary: %s",
                old_node.id,
                new_node.id,
                edge.id,
                summary.summary,
            )
        else:
            logger.info(
                "Transition: '%s' → '%s' via edge '%s' (decision node, no summary)",
                old_node.id,
                new_node.id,
                edge.id,
            )

        # Enter new node
        self._current_node = new_node
        self._iteration_count = 0
        self._enter_node(new_node)

        # If new node is a decision node, route through it silently
        if new_node.type == NodeType.decision:
            result = await self._route_through_decisions()
            if isinstance(result, ActionResult):
                return result, result.call_ended
            return result, False

        # If new node is an action node, execute it immediately
        if new_node.type == NodeType.action:
            result = self._execute_action()
            return result, result.call_ended

        # Generate first response in new conversation node
        response = await self._call_responder()
        self._append_history("assistant", response)

        return response, False

    async def _route_through_decisions(self) -> str | ActionResult:
        """Route through consecutive decision nodes until reaching a conversation or action node.

        Decision nodes produce no spoken output — they silently pick an edge
        and move to the next node. This method handles chaining through multiple
        decision nodes.
        """
        max_depth = 10  # safety guard against infinite loops
        for _ in range(max_depth):
            if self._current_node.type == NodeType.conversation:
                # Reached a conversation node — generate a response
                response = await self._call_responder()
                self._append_history("assistant", response)
                return response

            if self._current_node.type == NodeType.action:
                # Reached an action node — execute it
                return self._execute_action()

            if self._current_node.type != NodeType.decision:
                raise WorkflowError(
                    f"Unexpected node type '{self._current_node.type}' in decision chain"
                )
            outgoing = self._workflow.get_outgoing_edges(self._current_node.id)
            if not outgoing:
                raise WorkflowError(
                    f"Decision node '{self._current_node.id}' has no outgoing edges"
                )

            # Single outgoing edge — follow it immediately (no LLM call)
            if len(outgoing) == 1:
                edge = outgoing[0]
                logger.info(
                    "Decision node '%s': single edge, following '%s'",
                    self._current_node.id,
                    edge.id,
                )
            else:
                # Call Router LLM to pick the edge
                edge_id = await self._call_decision_router(outgoing)
                edge = self._find_edge(edge_id, outgoing)
                if edge is None:
                    # Fallback to first edge
                    logger.warning(
                        "Decision router returned unknown '%s' — falling back to first edge",
                        edge_id,
                    )
                    edge = outgoing[0]

            # Move to next node
            new_node = self._workflow.get_node(edge.target)
            logger.info(
                "Decision '%s' → '%s' via edge '%s'",
                self._current_node.id,
                new_node.id,
                edge.id,
            )
            self._current_node = new_node
            self._iteration_count = 0
            self._enter_node(new_node)

        raise WorkflowError("Too many consecutive decision nodes (possible loop)")

    def _execute_action(self) -> ActionResult:
        """Execute the current action node and return an ActionResult.

        Action nodes perform side effects:
        - ``end_call``: returns a closing message with call_ended=True.
        - ``transfer``: returns an announcement with the target phone number.
        - Unknown action types raise WorkflowError.
        """
        action_data = self._current_node.get_action_data()
        logger.info(
            "Executing action node '%s': %s",
            self._current_node.id,
            action_data.action_type,
        )

        if action_data.action_type == ActionType.end_call:
            return ActionResult(
                action_type="end_call",
                message=action_data.message,
                call_ended=True,
            )
        elif action_data.action_type == ActionType.transfer:
            return ActionResult(
                action_type="transfer",
                message=action_data.announcement,
                call_ended=False,
                transfer_number=action_data.target_number,
            )
        else:
            raise WorkflowError(
                f"Unknown action_type '{action_data.action_type}' "
                f"in action node '{self._current_node.id}'"
            )

    async def _call_decision_router(self, outgoing_edges: list[WorkflowEdge]) -> str:
        """Ask the Router LLM which edge to follow from a decision node."""
        decision_data = self._current_node.get_decision_data()
        edges_text = "\n".join(
            f'- Edge "{e.id}": {e.label}' for e in outgoing_edges
        )

        # Build context from accumulated summaries
        if self._summaries:
            context = "\n\n".join(
                f"[{s.node_name}] {s.summary}"
                + (f" | Key info: {json.dumps(s.key_info)}" if s.key_info else "")
                for s in self._summaries
            )
        else:
            context = "(No prior context)"

        # Find the last caller utterance across all node histories
        last_utterance = "(none)"
        for node_id in reversed(list(self._node_histories.keys())):
            for msg in reversed(self._node_histories[node_id]):
                if msg["role"] == "user":
                    last_utterance = msg["content"]
                    break
            if last_utterance != "(none)":
                break

        system = DECISION_ROUTER_PROMPT.format(
            instruction=decision_data.instruction,
            context=context,
            edges_text=edges_text,
            last_utterance=last_utterance,
        )

        messages = [{"role": "system", "content": system}]
        result = await self._router.chat(messages)
        decision = result.strip().strip('"').strip("'")
        logger.info("Decision router at '%s': %s", self._current_node.id, decision)
        return decision

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

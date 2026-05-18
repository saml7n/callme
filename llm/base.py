"""Abstract base for LLM clients — allows swapping providers (OpenAI, Anthropic, etc.)."""

from __future__ import annotations

from typing import Any, AsyncGenerator, Protocol, runtime_checkable


@runtime_checkable
class BaseLLMClient(Protocol):
    """Protocol that all LLM client implementations must satisfy."""

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream text chunks from the LLM."""
        ...  # pragma: no cover

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        """Return the full response text (non-streaming)."""
        ...  # pragma: no cover

    async def chat_structured(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Return structured JSON output validated against a schema."""
        ...  # pragma: no cover

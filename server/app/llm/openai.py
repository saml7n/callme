"""OpenAI LLM client with streaming, tool calling, structured output, and retries.

Implements the BaseLLMClient protocol.

Reference: https://platform.openai.com/docs/api-reference/chat
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from openai import (
    AsyncOpenAI,
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    RateLimitError,
)

from app.credentials import get_openai_api_key

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Base exception for LLM client errors."""


class LLMAuthError(LLMError):
    """Raised when the API key is invalid."""


class LLMRateLimitError(LLMError):
    """Raised when rate-limited after all retries are exhausted."""


class LLMConnectionError(LLMError):
    """Raised when the LLM API is unreachable."""


@dataclass
class ToolCall:
    """A tool/function call returned by the LLM."""

    id: str
    function_name: str
    arguments: dict[str, Any]


class LLMClient:
    """Async OpenAI LLM client with streaming, tool calling, and structured output.

    Usage::

        client = LLMClient()
        response = await client.chat([{"role": "user", "content": "Hello"}])

        async for chunk in client.chat_stream([{"role": "user", "content": "Hello"}]):
            print(chunk, end="")
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-4o",
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._api_key = api_key or get_openai_api_key()
        self._model = model
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._client = AsyncOpenAI(api_key=self._api_key)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream text chunks from the LLM.

        Yields text delta strings as they arrive. For tool calls,
        yields nothing — use chat() or chat_with_tools() instead.
        """
        kwargs = self._build_kwargs(messages, tools, stream=True)

        response = await self._call_with_retries(
            lambda: self._client.chat.completions.create(**kwargs)
        )

        async for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        """Return the full response text (non-streaming)."""
        kwargs = self._build_kwargs(messages, tools, stream=False)

        response = await self._call_with_retries(
            lambda: self._client.chat.completions.create(**kwargs)
        )

        choice = response.choices[0]
        return choice.message.content or ""

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> str | list[ToolCall]:
        """Return either a text response or a list of tool calls.

        If the LLM decides to call tools, returns a list of ToolCall objects.
        Otherwise returns the text response as a string.
        """
        kwargs = self._build_kwargs(messages, tools, stream=False)

        response = await self._call_with_retries(
            lambda: self._client.chat.completions.create(**kwargs)
        )

        choice = response.choices[0]
        message = choice.message

        if message.tool_calls:
            return [
                ToolCall(
                    id=tc.id,
                    function_name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                )
                for tc in message.tool_calls
            ]

        return message.content or ""

    async def chat_structured(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Return structured JSON output matching the provided schema.

        Uses OpenAI's response_format with json_schema to guarantee
        valid JSON output conforming to the schema.
        """
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.get("name", "extraction"),
                    "strict": True,
                    "schema": schema,
                },
            },
        }

        response = await self._call_with_retries(
            lambda: self._client.chat.completions.create(**kwargs)
        )

        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    def _build_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        stream: bool,
    ) -> dict[str, Any]:
        """Build the kwargs dict for the OpenAI API call."""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            kwargs["tools"] = tools
        return kwargs

    async def _call_with_retries(self, call_fn, _attempt: int = 0):
        """Execute an API call with exponential backoff retries on 429 / 5xx."""
        try:
            return await call_fn()
        except AuthenticationError as exc:
            raise LLMAuthError(
                f"Invalid OpenAI API key (401 Unauthorized): {exc}"
            ) from exc
        except RateLimitError as exc:
            if _attempt >= self._max_retries:
                raise LLMRateLimitError(
                    f"Rate limited after {self._max_retries} retries: {exc}"
                ) from exc
            delay = self._retry_base_delay * (2 ** _attempt)
            logger.warning(
                "Rate limited (429), retrying in %.1fs (attempt %d/%d)",
                delay,
                _attempt + 1,
                self._max_retries,
            )
            await asyncio.sleep(delay)
            return await self._call_with_retries(call_fn, _attempt + 1)
        except APIStatusError as exc:
            if exc.status_code >= 500 and _attempt < self._max_retries:
                delay = self._retry_base_delay * (2 ** _attempt)
                logger.warning(
                    "Server error (%d), retrying in %.1fs (attempt %d/%d)",
                    exc.status_code,
                    delay,
                    _attempt + 1,
                    self._max_retries,
                )
                await asyncio.sleep(delay)
                return await self._call_with_retries(call_fn, _attempt + 1)
            raise LLMError(f"OpenAI API error ({exc.status_code}): {exc}") from exc
        except APIConnectionError as exc:
            if _attempt < self._max_retries:
                delay = self._retry_base_delay * (2 ** _attempt)
                logger.warning(
                    "Connection error, retrying in %.1fs (attempt %d/%d)",
                    delay,
                    _attempt + 1,
                    self._max_retries,
                )
                await asyncio.sleep(delay)
                return await self._call_with_retries(call_fn, _attempt + 1)
            raise LLMConnectionError(
                f"Failed to connect to OpenAI after {self._max_retries} retries: {exc}"
            ) from exc

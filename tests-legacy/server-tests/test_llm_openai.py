"""Unit tests for the OpenAI LLM client (Story 4).

All tests use mocked HTTP responses — no real API calls.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openai import APIConnectionError, APIStatusError, AuthenticationError, RateLimitError

from app.llm.openai import (
    LLMClient,
    LLMAuthError,
    LLMRateLimitError,
    LLMConnectionError,
    LLMError,
    ToolCall,
)
from app.llm.base import BaseLLMClient


# ---------------------------------------------------------------------------
# Helpers to build mock OpenAI response objects
# ---------------------------------------------------------------------------

def _make_message(content: str = "", tool_calls=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    return msg


def _make_choice(message):
    choice = MagicMock()
    choice.message = message
    return choice


def _make_response(content: str = "", tool_calls=None):
    resp = MagicMock()
    resp.choices = [_make_choice(_make_message(content, tool_calls))]
    return resp


def _make_stream_chunks(texts: list[str]):
    """Create a list of mock streaming chunks with text deltas."""
    chunks = []
    for text in texts:
        chunk = MagicMock()
        delta = MagicMock()
        delta.content = text
        choice = MagicMock()
        choice.delta = delta
        chunk.choices = [choice]
        chunks.append(chunk)
    return chunks


def _make_tool_call(tc_id: str, name: str, arguments: dict):
    tc = MagicMock()
    tc.id = tc_id
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestProtocolConformance:
    def test_llm_client_satisfies_protocol(self):
        """LLMClient should satisfy the BaseLLMClient protocol."""
        assert isinstance(LLMClient(api_key="test"), BaseLLMClient)


# ---------------------------------------------------------------------------
# chat() — non-streaming
# ---------------------------------------------------------------------------

class TestChat:
    @pytest.fixture
    def client(self):
        return LLMClient(api_key="test-key", max_retries=0)

    async def test_returns_response_text(self, client):
        mock_resp = _make_response("Hello! How can I help?")
        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await client.chat([{"role": "user", "content": "Hi"}])
        assert result == "Hello! How can I help?"

    async def test_passes_tools_when_provided(self, client):
        mock_resp = _make_response("Sure, let me check.")
        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {}}}]
        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_create:
            await client.chat(
                [{"role": "user", "content": "Check my booking"}],
                tools=tools,
            )
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["tools"] == tools

    async def test_empty_content_returns_empty_string(self, client):
        mock_resp = _make_response(content="")
        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await client.chat([{"role": "user", "content": "Hi"}])
        assert result == ""


# ---------------------------------------------------------------------------
# chat_stream() — streaming
# ---------------------------------------------------------------------------

class TestChatStream:
    @pytest.fixture
    def client(self):
        return LLMClient(api_key="test-key", max_retries=0)

    async def test_yields_chunks_in_order(self, client):
        chunks = _make_stream_chunks(["Hello", ", how", " can I", " help?"])

        async def mock_stream():
            for c in chunks:
                yield c

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_stream()
        ):
            collected = []
            async for text in client.chat_stream([{"role": "user", "content": "Hi"}]):
                collected.append(text)

        assert collected == ["Hello", ", how", " can I", " help?"]
        assert "".join(collected) == "Hello, how can I help?"

    async def test_skips_empty_deltas(self, client):
        chunk_with_content = MagicMock()
        delta1 = MagicMock()
        delta1.content = "Hello"
        choice1 = MagicMock()
        choice1.delta = delta1
        chunk_with_content.choices = [choice1]

        chunk_empty = MagicMock()
        delta2 = MagicMock()
        delta2.content = None
        choice2 = MagicMock()
        choice2.delta = delta2
        chunk_empty.choices = [choice2]

        async def mock_stream():
            yield chunk_with_content
            yield chunk_empty

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_stream()
        ):
            collected = []
            async for text in client.chat_stream([{"role": "user", "content": "Hi"}]):
                collected.append(text)

        assert collected == ["Hello"]


# ---------------------------------------------------------------------------
# chat_with_tools() — tool calling
# ---------------------------------------------------------------------------

class TestChatWithTools:
    @pytest.fixture
    def client(self):
        return LLMClient(api_key="test-key", max_retries=0)

    async def test_returns_tool_calls(self, client):
        tc = _make_tool_call("call_123", "book_appointment", {"date": "Friday", "name": "Alex"})
        mock_resp = _make_response(content="", tool_calls=[tc])

        tools = [{"type": "function", "function": {"name": "book_appointment", "parameters": {}}}]

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await client.chat_with_tools(
                [{"role": "user", "content": "Book Friday for Alex"}],
                tools=tools,
            )

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ToolCall)
        assert result[0].function_name == "book_appointment"
        assert result[0].arguments == {"date": "Friday", "name": "Alex"}

    async def test_returns_text_when_no_tool_calls(self, client):
        mock_resp = _make_response(content="I can help with that!", tool_calls=None)
        tools = [{"type": "function", "function": {"name": "book_appointment", "parameters": {}}}]

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await client.chat_with_tools(
                [{"role": "user", "content": "Hello"}],
                tools=tools,
            )

        assert result == "I can help with that!"


# ---------------------------------------------------------------------------
# chat_structured() — structured JSON output
# ---------------------------------------------------------------------------

class TestChatStructured:
    @pytest.fixture
    def client(self):
        return LLMClient(api_key="test-key", max_retries=0)

    async def test_returns_parsed_json(self, client):
        json_content = json.dumps({"caller_name": "Alex", "reason": "appointment"})
        mock_resp = _make_response(content=json_content)

        schema = {
            "type": "object",
            "properties": {
                "caller_name": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["caller_name", "reason"],
            "additionalProperties": False,
        }

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_create:
            result = await client.chat_structured(
                [{"role": "user", "content": "My name is Alex, I want an appointment"}],
                schema=schema,
            )

        assert result == {"caller_name": "Alex", "reason": "appointment"}
        # Verify response_format was passed
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["response_format"]["type"] == "json_schema"


# ---------------------------------------------------------------------------
# Error handling & retries
# ---------------------------------------------------------------------------

class TestErrorHandling:
    async def test_auth_failure_raises_immediately(self):
        client = LLMClient(api_key="bad-key", max_retries=3)

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.headers = {}
        exc = AuthenticationError(
            message="Invalid API key",
            response=mock_resp,
            body=None,
        )

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock, side_effect=exc
        ):
            with pytest.raises(LLMAuthError, match="Invalid OpenAI API key"):
                await client.chat([{"role": "user", "content": "Hi"}])

    async def test_rate_limit_retries_then_succeeds(self):
        client = LLMClient(api_key="test-key", max_retries=3, retry_base_delay=0.01)

        mock_resp_obj = MagicMock()
        mock_resp_obj.status_code = 429
        mock_resp_obj.headers = {}
        rate_exc = RateLimitError(
            message="Rate limited",
            response=mock_resp_obj,
            body=None,
        )
        success_resp = _make_response("Hello!")

        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise rate_exc
            return success_resp

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock, side_effect=side_effect
        ):
            result = await client.chat([{"role": "user", "content": "Hi"}])

        assert result == "Hello!"
        assert call_count == 3

    async def test_rate_limit_exhausts_retries(self):
        client = LLMClient(api_key="test-key", max_retries=2, retry_base_delay=0.01)

        mock_resp_obj = MagicMock()
        mock_resp_obj.status_code = 429
        mock_resp_obj.headers = {}
        rate_exc = RateLimitError(
            message="Rate limited",
            response=mock_resp_obj,
            body=None,
        )

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock, side_effect=rate_exc
        ):
            with pytest.raises(LLMRateLimitError, match="Rate limited after 2 retries"):
                await client.chat([{"role": "user", "content": "Hi"}])

    async def test_server_error_retries(self):
        client = LLMClient(api_key="test-key", max_retries=3, retry_base_delay=0.01)

        mock_resp_obj = MagicMock()
        mock_resp_obj.status_code = 500
        mock_resp_obj.headers = {}
        server_exc = APIStatusError(
            message="Internal server error",
            response=mock_resp_obj,
            body=None,
        )
        success_resp = _make_response("Recovered!")

        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise server_exc
            return success_resp

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock, side_effect=side_effect
        ):
            result = await client.chat([{"role": "user", "content": "Hi"}])

        assert result == "Recovered!"
        assert call_count == 2

    async def test_connection_error_retries(self):
        client = LLMClient(api_key="test-key", max_retries=2, retry_base_delay=0.01)

        conn_exc = APIConnectionError(request=MagicMock())
        success_resp = _make_response("Back online!")

        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise conn_exc
            return success_resp

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock, side_effect=side_effect
        ):
            result = await client.chat([{"role": "user", "content": "Hi"}])

        assert result == "Back online!"

    async def test_connection_error_exhausts_retries(self):
        client = LLMClient(api_key="test-key", max_retries=1, retry_base_delay=0.01)

        conn_exc = APIConnectionError(request=MagicMock())

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock, side_effect=conn_exc
        ):
            with pytest.raises(LLMConnectionError, match="Failed to connect"):
                await client.chat([{"role": "user", "content": "Hi"}])

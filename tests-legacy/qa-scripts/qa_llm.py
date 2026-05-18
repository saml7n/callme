"""QA script for Story 4 — Live OpenAI API calls.

Tests:
1. Streaming chat with a receptionist prompt.
2. Structured data extraction from a transcript.

Run:  cd server && uv run python scripts/qa_llm.py
"""

import asyncio
import sys
import time

# Add server root to path so app.* imports work
sys.path.insert(0, ".")

from app.llm.openai import LLMClient


async def test_streaming():
    """QA Test 1: Streaming chat with receptionist prompt."""
    print("=" * 60)
    print("TEST 1: Streaming chat (receptionist)")
    print("=" * 60)

    client = LLMClient()
    messages = [
        {
            "role": "system",
            "content": "You are a receptionist. Be helpful and concise.",
        },
        {
            "role": "user",
            "content": "Hi, I'd like to book an appointment.",
        },
    ]

    print("\nPrompt: 'Hi, I'd like to book an appointment.'")
    print("Response (streamed): ", end="", flush=True)

    chunks = []
    t0 = time.perf_counter()
    first_chunk_time = None

    async for chunk in client.chat_stream(messages):
        if first_chunk_time is None:
            first_chunk_time = time.perf_counter() - t0
        chunks.append(chunk)
        print(chunk, end="", flush=True)

    total_time = time.perf_counter() - t0
    full_response = "".join(chunks)

    print(f"\n\nTime to first chunk: {first_chunk_time:.3f}s")
    print(f"Total time:          {total_time:.3f}s")
    print(f"Chunks received:     {len(chunks)}")
    print(f"Response length:     {len(full_response)} chars")

    assert len(full_response) > 10, "Response too short!"
    assert first_chunk_time < 5.0, "First chunk took too long!"
    print("✓ PASSED")


async def test_structured_output():
    """QA Test 2: Structured data extraction from a transcript."""
    print("\n" + "=" * 60)
    print("TEST 2: Structured data extraction")
    print("=" * 60)

    client = LLMClient()
    messages = [
        {
            "role": "system",
            "content": "Extract the caller's name and reason for calling from the transcript.",
        },
        {
            "role": "user",
            "content": "Transcript: 'Hi, my name is Alex and I'd like to book a dental cleaning for next Friday please.'",
        },
    ]

    schema = {
        "type": "object",
        "properties": {
            "caller_name": {"type": "string", "description": "The caller's name"},
            "reason": {"type": "string", "description": "The reason for calling"},
        },
        "required": ["caller_name", "reason"],
        "additionalProperties": False,
    }

    print("\nTranscript: 'Hi, my name is Alex and I'd like to book a dental cleaning for next Friday please.'")

    t0 = time.perf_counter()
    result = await client.chat_structured(messages, schema)
    elapsed = time.perf_counter() - t0

    print(f"Extracted: {result}")
    print(f"Time:      {elapsed:.3f}s")

    assert "caller_name" in result, "Missing caller_name!"
    assert "reason" in result, "Missing reason!"
    assert "alex" in result["caller_name"].lower(), f"Expected 'Alex', got '{result['caller_name']}'"
    print("✓ PASSED")


async def main():
    print("Story 4 QA — Live OpenAI API calls\n")
    await test_streaming()
    await test_structured_output()
    print("\n" + "=" * 60)
    print("ALL QA TESTS PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

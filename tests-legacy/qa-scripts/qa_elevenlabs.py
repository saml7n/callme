"""QA script for Story 5 — Live ElevenLabs TTS API calls.

Tests:
1. Non-streaming synthesis → save μ-law audio file → play it.
2. Streaming synthesis → log chunk timestamps.

Run:  cd server && uv run python scripts/qa_elevenlabs.py
"""

import asyncio
import sys
import time

sys.path.insert(0, ".")

from app.tts.elevenlabs import ElevenLabsTTSClient


async def test_synthesize():
    """QA Test 1: Non-streaming synthesis → save .raw file."""
    print("=" * 60)
    print("TEST 1: Non-streaming synthesis")
    print("=" * 60)

    client = ElevenLabsTTSClient()
    text = "Hello, thanks for calling. How can I help you today?"

    print(f"\nText: '{text}'")
    t0 = time.perf_counter()
    audio = await client.synthesize(text)
    elapsed = time.perf_counter() - t0

    output_path = "tests/fixtures/tts_output.raw"
    with open(output_path, "wb") as f:
        f.write(audio)

    print(f"Audio size:   {len(audio):,} bytes")
    print(f"Duration est: ~{len(audio) / 8000:.2f}s (at 8kHz μ-law)")
    print(f"Latency:      {elapsed:.3f}s")
    print(f"Saved to:     {output_path}")
    print(f"\nPlay with:  ffplay -f mulaw -ar 8000 -ac 1 {output_path}")

    assert len(audio) > 1000, f"Audio too small ({len(audio)} bytes)!"
    assert elapsed < 10.0, f"Synthesis too slow ({elapsed:.1f}s)!"
    print("✓ PASSED")

    await client.close()
    return output_path


async def test_streaming():
    """QA Test 2: Streaming synthesis → log chunk timestamps."""
    print("\n" + "=" * 60)
    print("TEST 2: Streaming synthesis")
    print("=" * 60)

    client = ElevenLabsTTSClient()
    text = "I'd be happy to help you book an appointment. What day works best for you?"

    print(f"\nText: '{text}'")

    chunks = []
    t0 = time.perf_counter()
    first_chunk_time = None

    async for chunk in client.synthesize_stream(text):
        now = time.perf_counter() - t0
        if first_chunk_time is None:
            first_chunk_time = now
        chunks.append((now, len(chunk)))
        print(f"  chunk {len(chunks):3d}: {len(chunk):5d} bytes @ {now:.3f}s")

    total_bytes = sum(size for _, size in chunks)
    total_time = time.perf_counter() - t0

    print(f"\nFirst chunk at: {first_chunk_time:.3f}s")
    print(f"Total chunks:   {len(chunks)}")
    print(f"Total bytes:    {total_bytes:,}")
    print(f"Total time:     {total_time:.3f}s")
    print(f"Duration est:   ~{total_bytes / 8000:.2f}s (at 8kHz μ-law)")

    assert len(chunks) >= 1, "No chunks received!"
    assert total_bytes > 1000, f"Audio too small ({total_bytes} bytes)!"
    assert first_chunk_time < 5.0, f"First chunk too slow ({first_chunk_time:.1f}s)!"
    print("✓ PASSED")

    await client.close()


async def main():
    print("Story 5 QA — Live ElevenLabs TTS API calls\n")
    await test_synthesize()
    await test_streaming()
    print("\n" + "=" * 60)
    print("ALL QA TESTS PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

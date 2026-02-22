"""Story 3 QA: Send a pre-recorded μ-law audio file to Deepgram and print transcripts.

Usage:
    cd server/
    uv run python scripts/qa_deepgram.py
"""

import asyncio
import sys
import os

# Add the server directory to the path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.stt.deepgram import DeepgramSTTClient


AUDIO_FILE = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "test_audio.mulaw")
CHUNK_SIZE = 3200  # 200ms of 8kHz μ-law audio (8000 * 0.2 * 1 byte)


async def main() -> None:
    client = DeepgramSTTClient()

    print("Connecting to Deepgram...")
    await client.connect()
    print("Connected!\n")

    # Read the audio file
    with open(AUDIO_FILE, "rb") as f:
        audio_data = f.read()
    print(f"Loaded {len(audio_data)} bytes of μ-law audio from {AUDIO_FILE}\n")

    # Start receiving transcripts in a background task
    async def receive():
        async for event in client.receive_transcripts():
            if event.transcript:  # skip empty interim results
                marker = ""
                if event.speech_final:
                    marker = " [SPEECH_FINAL]"
                elif event.is_final:
                    marker = " [FINAL]"
                else:
                    marker = " [interim]"
                print(
                    f"  {marker} (confidence={event.confidence:.2f}) "
                    f'"{event.transcript}"'
                )

    recv_task = asyncio.create_task(receive())

    # Send audio in chunks, simulating real-time streaming
    print("Sending audio...")
    offset = 0
    while offset < len(audio_data):
        chunk = audio_data[offset : offset + CHUNK_SIZE]
        await client.send_audio(chunk)
        offset += CHUNK_SIZE
        # Pace it roughly like real-time (200ms chunks)
        await asyncio.sleep(0.2)

    print("All audio sent. Sending silence to trigger endpointing...\n")

    # Send 1 second of silence (μ-law silence = 0xFF bytes) to trigger endpointing
    silence = b"\xff" * 8000
    await client.send_audio(silence)
    await asyncio.sleep(1)
    await client.send_audio(silence)

    # Give Deepgram a moment to finish processing
    await asyncio.sleep(2)

    # Close
    await client.close()
    recv_task.cancel()
    try:
        await recv_task
    except asyncio.CancelledError:
        pass

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())

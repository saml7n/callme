"""End-to-end synthetic caller — exercises the full voice pipeline over WebSocket.

Connects to the server's /twilio/media-stream WebSocket, simulates the Twilio
media-stream protocol, and runs multi-turn conversation scenarios through the
real STT → LLM → TTS pipeline.

This is the closest automated test to calling the actual phone number.
It tests everything except the Twilio telephone network itself.

What it exercises:
- Twilio WebSocket protocol (connected, start, media, stop, clear, mark)
- Deepgram STT (real audio → real transcription)
- OpenAI LLM (real conversation with the workflow engine)
- ElevenLabs TTS (real speech synthesis)
- Sentence splitting, interruption handling, filler phrases
- Workflow routing (greeting → intent_router → destination node)

Prerequisites:
- Server running on localhost:3000 with a workflow active
- Environment variables set: DEEPGRAM_API_KEY, ELEVENLABS_API_KEY, OPENAI_API_KEY

Run:  cd server && source ../.env.local && uv run python scripts/qa_e2e_call.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from dataclasses import dataclass, field

import httpx
import websockets
import websockets.asyncio.client

# Add server root to path so app.* imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.stt.deepgram import DeepgramSTTClient
from app.tts.elevenlabs import ElevenLabsTTSClient

# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SERVER_BASE = os.environ.get("QA_SERVER_URL", "http://localhost:3000")
WS_BASE = SERVER_BASE.replace("https://", "wss://").replace("http://", "ws://")
WS_URL = f"{WS_BASE}/twilio/media-stream?to=&from=%2B15551234567"

# Silence: μ-law 0xFF = digital silence at 8kHz
SILENCE_BYTE = b"\xff"
CHUNK_DURATION_MS = 200  # Send audio in 200ms chunks
CHUNK_SIZE = int(8000 * CHUNK_DURATION_MS / 1000)  # 1600 bytes per chunk

# How long to wait for AI response after sending caller audio (seconds)
AI_RESPONSE_TIMEOUT = 30
# How long of silence to detect end of AI speech (seconds)
AI_SILENCE_THRESHOLD = 2.0

passed = 0
failed = 0
warnings = 0


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class ConversationTurn:
    """A single turn: caller says something, AI responds."""

    caller_text: str
    ai_transcript: str = ""
    ai_audio_bytes: int = 0
    latency_ms: float = 0.0


@dataclass
class ScenarioResult:
    """Results from running one scenario."""

    name: str
    turns: list[ConversationTurn] = field(default_factory=list)
    greeting_transcript: str = ""
    greeting_audio_bytes: int = 0
    total_time: float = 0.0
    error: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _assert(condition: bool, description: str) -> None:
    """Check a condition and print pass/fail."""
    global passed, failed
    if condition:
        passed += 1
        print(f"    {GREEN}✓ {description}{RESET}")
    else:
        failed += 1
        print(f"    {RED}✗ {description}{RESET}")


def _warn(description: str) -> None:
    """Print a warning (not a failure)."""
    global warnings
    warnings += 1
    print(f"    {YELLOW}⚠ {description}{RESET}")


def _print_exchange(role: str, text: str, extra: str = "") -> None:
    """Pretty-print a conversation exchange."""
    if role == "caller":
        print(f"  {YELLOW}Caller:{RESET} {text}{DIM}{extra}{RESET}")
    else:
        print(f"  {CYAN}Agent:{RESET}  {text}{DIM}{extra}{RESET}")


async def _synthesize_caller_audio(tts: ElevenLabsTTSClient, text: str) -> bytes:
    """Synthesize caller text to μ-law audio using ElevenLabs."""
    chunks: list[bytes] = []
    async for chunk in tts.synthesize_stream(text):
        chunks.append(chunk)
    return b"".join(chunks)


def _build_twilio_connected() -> str:
    """Build a Twilio 'connected' event."""
    return json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"})


def _build_twilio_start(stream_sid: str, call_sid: str) -> str:
    """Build a Twilio 'start' event."""
    return json.dumps({
        "event": "start",
        "sequenceNumber": "1",
        "streamSid": stream_sid,
        "start": {
            "streamSid": stream_sid,
            "accountSid": "ACtest_synthetic_caller",
            "callSid": call_sid,
            "tracks": ["inbound"],
            "mediaFormat": {
                "encoding": "audio/x-mulaw",
                "sampleRate": 8000,
                "channels": 1,
            },
            "customParameters": {},
        },
    })


def _build_twilio_media(stream_sid: str, audio: bytes, seq: int) -> str:
    """Build a Twilio 'media' event with base64-encoded audio."""
    return json.dumps({
        "event": "media",
        "sequenceNumber": str(seq),
        "streamSid": stream_sid,
        "media": {
            "track": "inbound",
            "chunk": str(seq),
            "timestamp": str(seq * CHUNK_DURATION_MS),
            "payload": base64.b64encode(audio).decode("ascii"),
        },
    })


def _build_twilio_stop(stream_sid: str) -> str:
    """Build a Twilio 'stop' event."""
    return json.dumps({
        "event": "stop",
        "sequenceNumber": "9999",
        "streamSid": stream_sid,
    })


# ---------------------------------------------------------------------------
# Synthetic caller core
# ---------------------------------------------------------------------------
class SyntheticCaller:
    """Simulates a Twilio media stream and acts as a phone caller.

    Connects to the server's WebSocket, sends audio as a caller would,
    and captures + transcribes the AI's responses.
    """

    def __init__(self) -> None:
        self._tts = ElevenLabsTTSClient()
        self._ws: websockets.asyncio.client.ClientConnection | None = None
        self._stream_sid = "MZqa_synthetic_test"
        self._call_sid = "CAqa_synthetic_test"
        self._seq = 0
        self._received_audio: bytearray = bytearray()
        self._receive_task: asyncio.Task | None = None
        self._audio_event = asyncio.Event()
        self._last_audio_time: float = 0.0
        self._greeting_audio: bytearray = bytearray()
        self._collecting_greeting = True

    async def connect(self) -> None:
        """Connect to the server and send Twilio handshake events."""
        self._ws = await websockets.asyncio.client.connect(
            WS_URL,
            max_size=10 * 1024 * 1024,  # 10MB max message
        )
        # Send connected + start events
        await self._ws.send(_build_twilio_connected())
        await asyncio.sleep(0.1)
        await self._ws.send(_build_twilio_start(self._stream_sid, self._call_sid))

        # Start background receiver
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        """Background loop: receive messages from the server."""
        try:
            assert self._ws is not None
            async for raw in self._ws:
                msg = json.loads(raw)
                event = msg.get("event", "")

                if event == "media":
                    payload = msg.get("media", {}).get("payload", "")
                    audio = base64.b64decode(payload)
                    self._received_audio.extend(audio)
                    if self._collecting_greeting:
                        self._greeting_audio.extend(audio)
                    self._last_audio_time = time.monotonic()
                    self._audio_event.set()

                elif event == "clear":
                    # Server interrupted — clear buffered audio
                    pass

                elif event == "mark":
                    pass

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as exc:
            print(f"  {RED}Receive error: {exc}{RESET}")

    async def wait_for_greeting(self, timeout: float = AI_RESPONSE_TIMEOUT) -> int:
        """Wait for the AI greeting to finish. Returns bytes of audio received."""
        # Wait for first audio
        try:
            await asyncio.wait_for(self._audio_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return 0

        # Wait for silence (AI stopped speaking)
        await self._wait_for_silence()
        self._collecting_greeting = False
        return len(self._greeting_audio)

    async def send_caller_audio(self, text: str) -> None:
        """Synthesize caller text and send as Twilio media events."""
        assert self._ws is not None

        # Synthesize caller speech
        audio = await _synthesize_caller_audio(self._tts, text)

        # Reset for new response tracking
        self._received_audio.clear()
        self._audio_event.clear()
        self._last_audio_time = 0.0

        # Send audio in chunks (simulating real-time streaming)
        offset = 0
        while offset < len(audio):
            chunk = audio[offset:offset + CHUNK_SIZE]
            self._seq += 1
            await self._ws.send(
                _build_twilio_media(self._stream_sid, chunk, self._seq)
            )
            offset += CHUNK_SIZE
            # Pace roughly like real-time
            await asyncio.sleep(CHUNK_DURATION_MS / 1000)

        # Send a brief silence after speaking to trigger endpointing
        for _ in range(5):  # 1 second of silence
            self._seq += 1
            silence = SILENCE_BYTE * CHUNK_SIZE
            await self._ws.send(
                _build_twilio_media(self._stream_sid, silence, self._seq)
            )
            await asyncio.sleep(CHUNK_DURATION_MS / 1000)

    async def wait_for_response(self, timeout: float = AI_RESPONSE_TIMEOUT) -> int:
        """Wait for the AI to respond and stop speaking. Returns audio bytes."""
        # Wait for first audio from AI
        try:
            await asyncio.wait_for(self._audio_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return 0

        # Wait for silence
        await self._wait_for_silence()
        return len(self._received_audio)

    async def _wait_for_silence(self) -> None:
        """Wait until the AI stops sending audio (silence threshold reached)."""
        while True:
            await asyncio.sleep(0.5)
            if self._last_audio_time == 0.0:
                continue
            elapsed = time.monotonic() - self._last_audio_time
            if elapsed >= AI_SILENCE_THRESHOLD:
                break

    async def transcribe_received_audio(self, audio: bytes | None = None) -> str:
        """Transcribe the received AI audio using Deepgram."""
        raw = bytes(audio) if audio is not None else bytes(self._received_audio)
        if len(raw) < 100:
            return ""

        stt = DeepgramSTTClient()
        await stt.connect()

        transcripts: list[str] = []

        async def receive() -> None:
            async for event in stt.receive_transcripts():
                if event.transcript and event.is_final:
                    transcripts.append(event.transcript)

        recv_task = asyncio.create_task(receive())

        # Send audio in chunks
        offset = 0
        while offset < len(raw):
            chunk = raw[offset:offset + CHUNK_SIZE]
            await stt.send_audio(chunk)
            offset += CHUNK_SIZE
            await asyncio.sleep(CHUNK_DURATION_MS / 1000)

        # Send silence to trigger endpointing
        await stt.send_audio(SILENCE_BYTE * 8000)
        await asyncio.sleep(1.5)
        await stt.send_audio(SILENCE_BYTE * 8000)
        await asyncio.sleep(2)

        await stt.close()
        recv_task.cancel()
        try:
            await recv_task
        except asyncio.CancelledError:
            pass

        return " ".join(transcripts)

    async def disconnect(self) -> None:
        """Send stop event and close the WebSocket."""
        if self._ws is not None:
            try:
                await self._ws.send(_build_twilio_stop(self._stream_sid))
                await asyncio.sleep(0.5)
                await self._ws.close()
            except Exception:
                pass
        if self._receive_task is not None:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        await self._tts.close()


# ---------------------------------------------------------------------------
# Test scenarios
# ---------------------------------------------------------------------------

async def scenario_booking(caller: SyntheticCaller) -> ScenarioResult:
    """Scenario 1: Caller wants to book an appointment."""
    result = ScenarioResult(name="Booking path (e2e)")
    t0 = time.perf_counter()

    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}SCENARIO 1: Booking path (end-to-end){RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    try:
        # 1. Wait for greeting
        print(f"\n  {DIM}Waiting for AI greeting...{RESET}")
        greeting_bytes = await caller.wait_for_greeting()
        _assert(greeting_bytes > 0, f"Received greeting audio ({greeting_bytes:,} bytes)")

        greeting_text = await caller.transcribe_received_audio(
            bytes(caller._greeting_audio)
        )
        result.greeting_transcript = greeting_text
        result.greeting_audio_bytes = greeting_bytes
        _print_exchange("agent", greeting_text or "(no transcript)", f"  [{greeting_bytes:,} bytes]")
        _assert(len(greeting_text) > 5, f"Greeting transcribed: '{greeting_text[:80]}...'")

        # 2. Caller requests a booking
        caller_text = "I'd like to book an appointment for a dental cleaning please"
        _print_exchange("caller", caller_text)

        t_send = time.perf_counter()
        await caller.send_caller_audio(caller_text)
        response_bytes = await caller.wait_for_response()
        latency = (time.perf_counter() - t_send) * 1000

        _assert(response_bytes > 0, f"AI responded with audio ({response_bytes:,} bytes, {latency:.0f}ms)")

        response_text = await caller.transcribe_received_audio()
        turn = ConversationTurn(
            caller_text=caller_text,
            ai_transcript=response_text,
            ai_audio_bytes=response_bytes,
            latency_ms=latency,
        )
        result.turns.append(turn)
        _print_exchange("agent", response_text or "(no transcript)", f"  [{response_bytes:,} bytes, {latency:.0f}ms]")
        _assert(len(response_text) > 5, "AI response transcribed successfully")

        # Check for booking-related content
        booking_keywords = ["book", "appointment", "schedule", "name", "when", "time", "date", "prefer"]
        has_booking = any(w in response_text.lower() for w in booking_keywords)
        _assert(has_booking, "Response is booking-related")

        # 3. Caller gives their name
        caller_text_2 = "My name is Sarah Johnson"
        _print_exchange("caller", caller_text_2)

        t_send2 = time.perf_counter()
        await caller.send_caller_audio(caller_text_2)
        response_bytes_2 = await caller.wait_for_response()
        latency_2 = (time.perf_counter() - t_send2) * 1000

        _assert(response_bytes_2 > 0, f"AI responded to name ({response_bytes_2:,} bytes, {latency_2:.0f}ms)")

        response_text_2 = await caller.transcribe_received_audio()
        turn2 = ConversationTurn(
            caller_text=caller_text_2,
            ai_transcript=response_text_2,
            ai_audio_bytes=response_bytes_2,
            latency_ms=latency_2,
        )
        result.turns.append(turn2)
        _print_exchange("agent", response_text_2 or "(no transcript)", f"  [{response_bytes_2:,} bytes, {latency_2:.0f}ms]")

    except Exception as exc:
        result.error = str(exc)
        print(f"    {RED}✗ Scenario error: {exc}{RESET}")

    result.total_time = time.perf_counter() - t0
    print(f"\n  ⏱ Total time: {result.total_time:.1f}s")
    return result


async def scenario_inquiry(caller: SyntheticCaller) -> ScenarioResult:
    """Scenario 2: Caller asks about pricing."""
    result = ScenarioResult(name="General inquiry (e2e)")
    t0 = time.perf_counter()

    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}SCENARIO 2: General inquiry (end-to-end){RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    try:
        # 1. Wait for greeting
        print(f"\n  {DIM}Waiting for AI greeting...{RESET}")
        greeting_bytes = await caller.wait_for_greeting()
        _assert(greeting_bytes > 0, f"Received greeting audio ({greeting_bytes:,} bytes)")

        greeting_text = await caller.transcribe_received_audio(
            bytes(caller._greeting_audio)
        )
        result.greeting_transcript = greeting_text
        result.greeting_audio_bytes = greeting_bytes
        _print_exchange("agent", greeting_text or "(no transcript)", f"  [{greeting_bytes:,} bytes]")

        # 2. Caller asks about prices
        caller_text = "How much does a teeth whitening cost?"
        _print_exchange("caller", caller_text)

        t_send = time.perf_counter()
        await caller.send_caller_audio(caller_text)
        response_bytes = await caller.wait_for_response()
        latency = (time.perf_counter() - t_send) * 1000

        _assert(response_bytes > 0, f"AI responded with audio ({response_bytes:,} bytes, {latency:.0f}ms)")

        response_text = await caller.transcribe_received_audio()
        turn = ConversationTurn(
            caller_text=caller_text,
            ai_transcript=response_text,
            ai_audio_bytes=response_bytes,
            latency_ms=latency,
        )
        result.turns.append(turn)
        _print_exchange("agent", response_text or "(no transcript)", f"  [{response_bytes:,} bytes, {latency:.0f}ms]")
        _assert(len(response_text) > 5, "AI response transcribed successfully")

        # Check for pricing-related content
        price_keywords = ["$", "cost", "price", "fee", "250", "dollar", "whitening"]
        has_price = any(w in response_text.lower() for w in price_keywords)
        if has_price:
            _assert(True, "Response includes pricing information")
        else:
            _warn("Response may not include pricing — check transcript above")

    except Exception as exc:
        result.error = str(exc)
        print(f"    {RED}✗ Scenario error: {exc}{RESET}")

    result.total_time = time.perf_counter() - t0
    print(f"\n  ⏱ Total time: {result.total_time:.1f}s")
    return result


async def scenario_speak_to_human(caller: SyntheticCaller) -> ScenarioResult:
    """Scenario 3: Caller asks for a real person."""
    result = ScenarioResult(name="Speak to human (e2e)")
    t0 = time.perf_counter()

    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}SCENARIO 3: Speak to human (end-to-end){RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    try:
        # 1. Wait for greeting
        print(f"\n  {DIM}Waiting for AI greeting...{RESET}")
        greeting_bytes = await caller.wait_for_greeting()
        _assert(greeting_bytes > 0, f"Received greeting audio ({greeting_bytes:,} bytes)")

        greeting_text = await caller.transcribe_received_audio(
            bytes(caller._greeting_audio)
        )
        result.greeting_transcript = greeting_text
        result.greeting_audio_bytes = greeting_bytes
        _print_exchange("agent", greeting_text or "(no transcript)", f"  [{greeting_bytes:,} bytes]")

        # 2. Caller asks for a human
        caller_text = "Can I speak with a real person please?"
        _print_exchange("caller", caller_text)

        t_send = time.perf_counter()
        await caller.send_caller_audio(caller_text)
        response_bytes = await caller.wait_for_response()
        latency = (time.perf_counter() - t_send) * 1000

        _assert(response_bytes > 0, f"AI responded with audio ({response_bytes:,} bytes, {latency:.0f}ms)")

        response_text = await caller.transcribe_received_audio()
        turn = ConversationTurn(
            caller_text=caller_text,
            ai_transcript=response_text,
            ai_audio_bytes=response_bytes,
            latency_ms=latency,
        )
        result.turns.append(turn)
        _print_exchange("agent", response_text or "(no transcript)", f"  [{response_bytes:,} bytes, {latency:.0f}ms]")
        _assert(len(response_text) > 5, "AI response transcribed successfully")

        # Check for transfer-related content
        transfer_keywords = ["connect", "transfer", "team", "staff", "member", "person", "hold", "moment"]
        has_transfer = any(w in response_text.lower() for w in transfer_keywords)
        _assert(has_transfer, "Response mentions connecting to a person")

    except Exception as exc:
        result.error = str(exc)
        print(f"    {RED}✗ Scenario error: {exc}{RESET}")

    result.total_time = time.perf_counter() - t0
    print(f"\n  ⏱ Total time: {result.total_time:.1f}s")
    return result


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_scenario(
    scenario_fn,
    name: str,
) -> ScenarioResult:
    """Run a single scenario with its own SyntheticCaller connection."""
    caller = SyntheticCaller()
    try:
        await caller.connect()
        result = await scenario_fn(caller)
    except Exception as exc:
        result = ScenarioResult(name=name, error=str(exc))
        print(f"    {RED}✗ Failed to run scenario: {exc}{RESET}")
    finally:
        await caller.disconnect()
    return result


async def main() -> None:
    """Run all e2e call scenarios."""
    global passed, failed

    print(f"{BOLD}End-to-End Synthetic Caller — Full Pipeline QA{RESET}")
    print(f"Server: {SERVER_BASE}")
    print(f"WebSocket: {WS_URL}")
    print()

    # Verify server is running
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{SERVER_BASE}/health")
        if resp.status_code != 200:
            print(f"{RED}ERROR: Server health check failed ({resp.status_code}){RESET}")
            sys.exit(1)
        print(f"{GREEN}Server is healthy{RESET}")
    except httpx.ConnectError:
        print(f"{RED}ERROR: Server not running at {SERVER_BASE}{RESET}")
        sys.exit(1)

    # Verify API keys are available
    from app.credentials import get_deepgram_api_key, get_elevenlabs_api_key, get_openai_api_key
    missing = []
    if not get_deepgram_api_key():
        missing.append("DEEPGRAM_API_KEY")
    if not get_elevenlabs_api_key():
        missing.append("ELEVENLABS_API_KEY")
    if not get_openai_api_key():
        missing.append("OPENAI_API_KEY")
    if missing:
        print(f"{RED}ERROR: Missing API keys: {', '.join(missing)}{RESET}")
        print("Set them in .env.local or as environment variables.")
        sys.exit(1)
    print(f"{GREEN}All API keys present{RESET}")
    print()

    # Run scenarios (each gets its own connection = its own call)
    scenarios = [
        (scenario_booking, "Booking path (e2e)"),
        (scenario_inquiry, "General inquiry (e2e)"),
        (scenario_speak_to_human, "Speak to human (e2e)"),
    ]

    results: list[ScenarioResult] = []
    for scenario_fn, name in scenarios:
        result = await run_scenario(scenario_fn, name)
        results.append(result)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"{BOLD}RESULTS SUMMARY{RESET}")
    print(f"{'=' * 60}")
    for r in results:
        icon = GREEN + "✓" if not r.error else RED + "✗"
        time_str = f" ({r.total_time:.1f}s)" if r.total_time > 0 else ""
        print(f"  {icon} {r.name}{time_str}{RESET}")
        if r.greeting_transcript:
            print(f"    {DIM}Greeting: {r.greeting_transcript[:60]}...{RESET}")
        for turn in r.turns:
            print(f"    {DIM}Caller: {turn.caller_text[:50]}{RESET}")
            print(f"    {DIM}Agent:  {turn.ai_transcript[:50]}... [{turn.latency_ms:.0f}ms]{RESET}")
        if r.error:
            print(f"    {RED}Error: {r.error}{RESET}")

    print(f"\n  {BOLD}Assertions: {GREEN}{passed} passed{RESET}, ", end="")
    if failed:
        print(f"{RED}{failed} failed{RESET}", end="")
    else:
        print(f"{GREEN}0 failed{RESET}", end="")
    if warnings:
        print(f", {YELLOW}{warnings} warnings{RESET}")
    else:
        print()

    total = passed + failed
    if failed == 0:
        print(f"\n{GREEN}{BOLD}ALL {total} ASSERTIONS PASSED ✓{RESET}")
    else:
        print(f"\n{YELLOW}{BOLD}{passed}/{total} ASSERTIONS PASSED{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

"""End-to-end voice pipeline: Twilio audio → Deepgram STT → OpenAI LLM → ElevenLabs TTS → Twilio audio.

Orchestrates a single phone call with interruption handling, filler phrases,
and error recovery.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any

from fastapi import WebSocket

from app.llm.openai import LLMClient
from app.stt.deepgram import DeepgramConnectionError, DeepgramSTTClient
from app.tts.elevenlabs import ElevenLabsTTSClient
from app.db.call_logger import CallLogger
from app.events import event_bus
from app.workflow.engine import ActionResult, WorkflowEngine

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a friendly AI receptionist for a business. "
    "Greet the caller, ask how you can help, and have a natural conversation. "
    "Keep responses concise — 1-2 sentences at a time."
)

GREETING = "Hello! Thank you for calling. How can I help you today?"

SENTENCE_ENDINGS = frozenset(".!?")

# Filler phrases played when LLM takes > FILLER_THRESHOLD_MS to respond
FILLER_PHRASES = [
    "One moment, please.",
    "Let me check on that.",
    "Just a moment.",
    "Bear with me one second.",
    "Let me look into that for you.",
]

FILLER_THRESHOLD_MS = 1500

# Error fallback messages
ERROR_MSG_HEARING = "I'm sorry, I'm having trouble hearing you. Please hold."
ERROR_MSG_TECHNICAL = "I apologise, I'm having a technical issue. Let me transfer you."
ERROR_MSG_GOODBYE = "I'm sorry, please call back later. Goodbye."


def _build_outbound_media(stream_sid: str, audio: bytes) -> str:
    """Build a JSON message to send audio back to Twilio."""
    return json.dumps(
        {
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": base64.b64encode(audio).decode("ascii")},
        }
    )


def _build_clear_message(stream_sid: str) -> str:
    """Build a JSON 'clear' message to stop Twilio playback immediately."""
    return json.dumps({"event": "clear", "streamSid": stream_sid})


def split_first_sentence(text: str) -> tuple[str, str]:
    """Split text at the first sentence boundary (.!?).

    Returns (sentence, remainder). If no boundary is found,
    returns ("", text) — i.e. nothing to send yet.
    """
    for i, ch in enumerate(text):
        if ch in SENTENCE_ENDINGS:
            return text[: i + 1].strip(), text[i + 1 :]
    return "", text


class FillerCache:
    """Pre-synthesised filler phrases cached as μ-law audio."""

    def __init__(self) -> None:
        self._clips: list[bytes] = []
        self._index = 0

    @property
    def ready(self) -> bool:
        return len(self._clips) > 0

    async def warm(self, tts: ElevenLabsTTSClient) -> None:
        """Pre-generate filler audio clips. Best-effort — failures are logged."""
        for phrase in FILLER_PHRASES:
            try:
                chunks: list[bytes] = []
                async for chunk in tts.synthesize_stream(phrase):
                    chunks.append(chunk)
                if chunks:
                    self._clips.append(b"".join(chunks))
            except Exception:
                logger.warning("Failed to pre-generate filler: %s", phrase)
        logger.info("Filler cache warmed: %d/%d clips", len(self._clips), len(FILLER_PHRASES))

    def next_clip(self) -> bytes | None:
        if not self._clips:
            return None
        clip = self._clips[self._index % len(self._clips)]
        self._index += 1
        return clip


# Module-level filler cache — shared across calls, warmed once
_filler_cache = FillerCache()


async def warm_filler_cache(tts: ElevenLabsTTSClient | None = None) -> None:
    """Warm the filler cache at server startup."""
    if _filler_cache.ready:
        return
    client = tts or ElevenLabsTTSClient()
    try:
        await _filler_cache.warm(client)
    finally:
        if tts is None:
            await client.close()


class CallPipeline:
    """Orchestrates a single call through the STT → LLM → TTS pipeline.

    Features:
    - **Interruption handling:** Sends Twilio `clear` when caller speaks during
      TTS playback, discards queued audio.
    - **Filler phrases:** Plays a pre-cached filler if the LLM takes > 800ms.
    - **Error recovery:** STT reconnect (1 retry), LLM/TTS fallback messages,
      transfer to fallback number on unrecoverable errors.
    """

    def __init__(
        self,
        ws: WebSocket,
        stream_sid: str,
        *,
        call_sid: str = "",
        stt: DeepgramSTTClient | None = None,
        llm: LLMClient | None = None,
        tts: ElevenLabsTTSClient | None = None,
        system_prompt: str = SYSTEM_PROMPT,
        greeting: str = GREETING,
        workflow: dict[str, Any] | None = None,
        engine: WorkflowEngine | None = None,
        call_logger: CallLogger | None = None,
        call_id: str = "",
        user_id: Any | None = None,
    ) -> None:
        self._ws = ws
        self._stream_sid = stream_sid
        self._call_sid = call_sid
        self._call_id = call_id
        self._user_id = user_id

        # Resolve per-user credentials when a user_id is available
        if user_id is not None and (stt is None or llm is None or tts is None):
            from app.credentials import (
                get_deepgram_api_key,
                get_elevenlabs_api_key,
                get_openai_api_key,
            )
            dg_key = get_deepgram_api_key(user_id=user_id)
            el_key = get_elevenlabs_api_key(user_id=user_id)
            oai_key = get_openai_api_key(user_id=user_id)
            self._stt = stt or DeepgramSTTClient(api_key=dg_key or None)
            self._llm = llm or LLMClient(api_key=oai_key or None)
            self._tts = tts or ElevenLabsTTSClient(api_key=el_key or None)
        else:
            self._stt = stt or DeepgramSTTClient()
            self._llm = llm or LLMClient()
            self._tts = tts or ElevenLabsTTSClient()

        self._system_prompt = system_prompt
        self._greeting = greeting
        self._call_logger = call_logger
        self._messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt},
        ]
        self._transcript_task: asyncio.Task[None] | None = None
        self._final_debounce_task: asyncio.Task[None] | None = None
        self._closed = False

        # Interruption tracking
        self._speaking = False
        self._interrupted = False
        self._response_task: asyncio.Task[None] | None = None

        # Playback duration tracking — Twilio buffers audio, so _speaking must
        # stay True until the estimated playback finishes, not just until we
        # finish sending chunks over the WebSocket.
        self._playback_end: float = 0.0  # monotonic time when playback should end
        self._speaking_off_task: asyncio.Task[None] | None = None
        self._filler_playing_until: float = 0.0  # monotonic time filler finishes

        # Workflow mode
        if engine is not None:
            self._engine: WorkflowEngine | None = engine
        elif workflow is not None:
            self._engine = WorkflowEngine(workflow, responder=self._llm)
        else:
            self._engine = None

    @property
    def messages(self) -> list[dict[str, str]]:
        """Current conversation history (read-only snapshot)."""
        return list(self._messages)

    # ------------------------------------------------------------------
    # Live event emission
    # ------------------------------------------------------------------

    def _emit(self, event_type: str, **kwargs: Any) -> None:
        """Emit a live event to the dashboard via the event bus."""
        if not self._call_id:
            return
        import time
        event_bus.emit({
            "type": event_type,
            "call_id": self._call_id,
            "timestamp": time.time(),
            **kwargs,
        })

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to Deepgram, send greeting, start processing transcripts."""
        await self._stt.connect()
        logger.info("Pipeline started — STT connected, sending greeting")

        # Proactive greeting — from engine or hardcoded
        if self._engine is not None:
            result = await self._engine.start()
            if isinstance(result, ActionResult):
                await self._speak(result.message)
                self._messages.append({"role": "assistant", "content": result.message})
                if result.call_ended:
                    await self._handle_end_call()
                    return
                if result.transfer_number:
                    await self._handle_transfer(result.transfer_number)
                    return
                return
            greeting = result
        else:
            greeting = self._greeting

        await self._speak(greeting)
        self._messages.append({"role": "assistant", "content": greeting})
        logger.info("Greeting sent: %s", greeting)

        # Background task to process STT transcripts
        self._transcript_task = asyncio.create_task(self._process_transcripts())

    async def send_audio(self, audio: bytes) -> None:
        """Forward a raw audio chunk to the STT engine."""
        if not self._closed:
            await self._stt.send_audio(audio)

    async def close(self) -> None:
        """Shut down all resources gracefully."""
        if self._closed:
            return
        self._closed = True

        # Determine whether we're being called from one of our own tasks
        # (e.g. _handle_end_call inside _response_task). In that case we
        # must NOT await the tasks — they reference each other and create
        # a circular await chain that overflows the stack.
        current = asyncio.current_task()
        own_tasks = {self._transcript_task, self._response_task}
        called_internally = current in own_tasks

        # Always request cancellation
        for task in [self._transcript_task, self._response_task]:
            if task is not None and task is not current:
                task.cancel()

        # Only await when called from the outside (media_stream.py, tests, …)
        if not called_internally:
            for task in [self._transcript_task, self._response_task]:
                if task is not None:
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

        self._cancel_debounce()

        # Cancel playback timer
        if self._speaking_off_task is not None:
            self._speaking_off_task.cancel()
            self._speaking_off_task = None

        # Close STT and TTS clients
        await self._stt.close()
        await self._tts.close()

        # Finalise call log
        if self._call_logger:
            self._call_logger.flush()
            self._call_logger.finalise()

        logger.info("Pipeline closed — %d messages in history", len(self._messages))

    # ------------------------------------------------------------------
    # Interruption
    # ------------------------------------------------------------------

    async def _interrupt(self) -> None:
        """Interrupt current TTS playback.

        Sends a Twilio `clear` message to stop audio immediately and
        sets the interrupted flag so the response generator stops.
        """
        if not self._speaking:
            return
        self._interrupted = True
        self._speaking = False
        self._playback_end = 0.0
        if self._speaking_off_task is not None:
            self._speaking_off_task.cancel()
            self._speaking_off_task = None
        try:
            await self._ws.send_text(_build_clear_message(self._stream_sid))
            logger.info("Interruption: sent clear, discarding queued audio")
        except Exception:
            logger.warning("Failed to send clear message")

        # Cancel the response generation task if running
        if self._response_task is not None:
            self._response_task.cancel()
            try:
                await self._response_task
            except asyncio.CancelledError:
                pass
            self._response_task = None

    # ------------------------------------------------------------------
    # Transcript processing
    # ------------------------------------------------------------------

    async def _process_transcripts(self) -> None:
        """Background loop: listen for transcript events and generate responses.

        Triggers on speech_final immediately. If only is_final events arrive
        (speech_final missing), a 0.3s debounce timer fires as a fallback.
        Handles Deepgram disconnects with 1 retry.
        """
        try:
            await self._receive_transcripts_with_reconnect()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in transcript processing loop")

    async def _receive_transcripts_with_reconnect(self) -> None:
        """Receive transcripts with one reconnection attempt on disconnect."""
        retries = 0
        while not self._closed:
            try:
                async for event in self._stt.receive_transcripts():
                    if event.transcript:
                        if event.speech_final:
                            self._cancel_debounce()
                            # Interrupt if AI is currently speaking
                            if self._speaking:
                                await self._interrupt()
                            logger.info(
                                "Caller [SPEECH_FINAL] (conf=%.2f): %s",
                                event.confidence,
                                event.transcript,
                            )
                            await self._handle_caller_utterance(event.transcript)
                        elif event.is_final:
                            logger.info(
                                "Caller [FINAL] (conf=%.2f): %s",
                                event.confidence,
                                event.transcript,
                            )
                            self._cancel_debounce()
                            transcript = event.transcript
                            self._final_debounce_task = asyncio.create_task(
                                self._debounced_handle(transcript, delay=0.3)
                            )
                        else:
                            # Interim result — interrupt if the caller starts talking
                            if self._speaking and event.transcript.strip():
                                await self._interrupt()
                            logger.debug("Caller [interim]: %s", event.transcript)
                # Normal end of generator — STT connection closed cleanly
                break
            except DeepgramConnectionError:
                if retries >= 1 or self._closed:
                    logger.error("Deepgram disconnected — retry exhausted, speaking fallback")
                    await self._speak_fallback(ERROR_MSG_HEARING)
                    break
                retries += 1
                logger.warning("Deepgram disconnected — attempting reconnect (%d/1)", retries)
                try:
                    self._stt = DeepgramSTTClient()
                    await self._stt.connect()
                    logger.info("Deepgram reconnected successfully")
                except Exception:
                    logger.error("Deepgram reconnect failed — speaking fallback")
                    await self._speak_fallback(ERROR_MSG_HEARING)
                    break

    def _cancel_debounce(self) -> None:
        """Cancel any pending is_final debounce timer."""
        if self._final_debounce_task is not None:
            self._final_debounce_task.cancel()
            self._final_debounce_task = None

    async def _debounced_handle(self, transcript: str, delay: float) -> None:
        """Wait `delay` seconds, then handle the transcript as a complete utterance."""
        try:
            await asyncio.sleep(delay)
            logger.info("Debounce fired (no speech_final) — treating as utterance: %s", transcript)
            if self._speaking:
                await self._interrupt()
            await self._handle_caller_utterance(transcript)
        except asyncio.CancelledError:
            pass

    async def _handle_caller_utterance(self, transcript: str) -> None:
        """Process a complete caller utterance through LLM/engine."""
        self._messages.append({"role": "user", "content": transcript})
        self._emit("transcript", role="caller", text=transcript)
        if self._call_logger:
            self._call_logger.log_transcript(transcript)
            self._call_logger.flush()

        # Generate response in a cancellable task (for interruption)
        if self._engine is not None:
            self._response_task = asyncio.create_task(
                self._generate_engine_response(transcript)
            )
        else:
            self._response_task = asyncio.create_task(self._generate_response())

        try:
            await self._response_task
        except asyncio.CancelledError:
            logger.info("Response generation interrupted by caller")
        finally:
            self._response_task = None

    # ------------------------------------------------------------------
    # Response generation
    # ------------------------------------------------------------------

    async def _generate_response(self) -> None:
        """Stream an LLM response, split into sentences, and TTS each.

        Includes filler phrase support and error recovery.
        """
        buffer = ""
        full_response = ""
        self._interrupted = False
        first_token_received = False
        filler_task: asyncio.Task[None] | None = None

        try:
            # Start filler timer
            if _filler_cache.ready:
                filler_task = asyncio.create_task(self._play_filler_after_delay())

            async for chunk in self._llm.chat_stream(self._messages):
                if self._interrupted:
                    break

                # On first token: cancel the filler timer (or wait for filler to finish)
                if not first_token_received:
                    first_token_received = True
                    if filler_task is not None:
                        filler_task.cancel()
                        try:
                            await filler_task
                        except asyncio.CancelledError:
                            pass
                        filler_task = None
                    # Wait for any playing filler to finish naturally
                    if self._filler_playing_until > 0:
                        await self._wait_for_filler()
                        self._speaking = False

                buffer += chunk
                full_response += chunk

                # Eagerly send complete sentences
                while not self._interrupted:
                    sentence, remainder = split_first_sentence(buffer)
                    if not sentence:
                        break
                    buffer = remainder
                    logger.info("LLM sentence → TTS: %s", sentence)
                    await self._speak(sentence)

            # Cancel filler if LLM returned empty
            if filler_task is not None:
                filler_task.cancel()

            # Flush any remaining text
            if not self._interrupted:
                leftover = buffer.strip()
                if leftover:
                    logger.info("LLM remainder → TTS: %s", leftover)
                    await self._speak(leftover)

            # Add the complete response to conversation history
            if full_response.strip():
                self._messages.append({"role": "assistant", "content": full_response.strip()})
                self._emit("transcript", role="ai", text=full_response.strip())
                logger.info("Assistant: %s", full_response.strip())
                if self._call_logger:
                    self._call_logger.log_llm_response(full_response.strip())
                    self._call_logger.flush()

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error generating LLM response")
            if self._call_logger:
                self._call_logger.log_error("LLM response generation failed")
                self._call_logger.flush()
            await self._handle_llm_failure()

    async def _generate_engine_response(self, transcript: str) -> None:
        """Stream a response from the WorkflowEngine with filler and sentence splitting.

        Uses the engine's streaming API so TTS can begin as soon as the
        first sentence is generated, rather than waiting for the full response.
        """
        buffer = ""
        full_response = ""
        self._interrupted = False
        first_chunk_received = False
        filler_task: asyncio.Task[None] | None = None

        try:
            assert self._engine is not None

            # Start filler timer while we wait for routing + first LLM tokens
            if _filler_cache.ready:
                filler_task = asyncio.create_task(self._play_filler_after_delay())

            async for item in self._engine.handle_input_stream(transcript):
                if self._interrupted:
                    break

                # Handle action results (not streamed — yielded as a single object)
                if isinstance(item, ActionResult):
                    if filler_task is not None:
                        filler_task.cancel()
                        try:
                            await filler_task
                        except asyncio.CancelledError:
                            pass
                        filler_task = None
                    # Clear any playing filler
                    if self._speaking:
                        await self._interrupt()
                        self._interrupted = False

                    if item.message:
                        logger.info("Engine action response: %s", item.message)
                        await self._speak(item.message)
                        self._messages.append({"role": "assistant", "content": item.message})
                    if self._call_logger:
                        self._call_logger.log_action(
                            item.action_type,
                            {"message": item.message, "transfer_number": item.transfer_number or ""},
                        )
                        self._call_logger.flush()
                    if item.call_ended:
                        await self._handle_end_call()
                    elif item.transfer_number:
                        await self._handle_transfer(item.transfer_number)
                    return

                # Text chunk from streaming responder
                chunk = item

                # On first real content: cancel the filler timer (or wait for filler to finish)
                if not first_chunk_received:
                    first_chunk_received = True
                    if filler_task is not None:
                        filler_task.cancel()
                        try:
                            await filler_task
                        except asyncio.CancelledError:
                            pass
                        filler_task = None
                    # Wait for any playing filler to finish naturally
                    if self._filler_playing_until > 0:
                        await self._wait_for_filler()
                        self._speaking = False

                buffer += chunk
                full_response += chunk

                # Eagerly send complete sentences
                while not self._interrupted:
                    sentence, remainder = split_first_sentence(buffer)
                    if not sentence:
                        break
                    buffer = remainder
                    logger.info("Engine sentence → TTS: %s", sentence)
                    await self._speak(sentence)

            # Cancel filler if engine returned empty
            if filler_task is not None:
                filler_task.cancel()

            # Flush any remaining text
            if not self._interrupted:
                leftover = buffer.strip()
                if leftover:
                    logger.info("Engine remainder → TTS: %s", leftover)
                    await self._speak(leftover)

            # Add the complete response to conversation history
            if full_response.strip():
                self._messages.append({"role": "assistant", "content": full_response.strip()})
                self._emit("transcript", role="ai", text=full_response.strip())
                logger.info("Engine assistant: %s", full_response.strip())
                if self._call_logger:
                    self._call_logger.log_llm_response(full_response.strip())
                    self._call_logger.flush()

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error generating engine response")
            if self._call_logger:
                self._call_logger.log_error("Engine response generation failed")
                self._call_logger.flush()
            await self._handle_llm_failure()

    # ------------------------------------------------------------------
    # Filler phrases
    # ------------------------------------------------------------------

    async def _play_filler_after_delay(self) -> None:
        """Wait FILLER_THRESHOLD_MS, then play a cached filler clip."""
        try:
            await asyncio.sleep(FILLER_THRESHOLD_MS / 1000)
            clip = _filler_cache.next_clip()
            if clip and not self._interrupted and not self._closed:
                logger.info("Playing filler phrase (LLM latency > %dms)", FILLER_THRESHOLD_MS)
                self._speaking = True
                msg = _build_outbound_media(self._stream_sid, clip)
                await self._ws.send_text(msg)
                # Track when filler playback ends so we can wait for it
                now = asyncio.get_event_loop().time()
                filler_duration = len(clip) / 8000  # μ-law 8kHz
                self._filler_playing_until = now + filler_duration + 0.3
        except asyncio.CancelledError:
            pass  # LLM responded in time

    async def _wait_for_filler(self) -> None:
        """Wait for any in-progress filler to finish playing on the phone.

        Instead of sending a Twilio ``clear`` (which cuts the filler off
        mid-word), we pause briefly so the caller hears the full phrase.
        """
        now = asyncio.get_event_loop().time()
        remaining = self._filler_playing_until - now
        if remaining > 0:
            logger.debug("Waiting %.2fs for filler to finish playing", remaining)
            await asyncio.sleep(remaining)
        self._filler_playing_until = 0.0

    # ------------------------------------------------------------------
    # Audio output
    # ------------------------------------------------------------------

    async def _speak(self, text: str) -> None:
        """Synthesize text via TTS and send audio to Twilio.

        After sending, keeps ``_speaking`` True for the estimated playback
        duration so that interruptions are detected while Twilio is still
        playing buffered audio.
        """
        if self._interrupted or self._closed:
            return
        self._speaking = True
        total_bytes = 0
        try:
            async for audio_chunk in self._tts.synthesize_stream(text):
                if self._interrupted or self._closed:
                    break
                total_bytes += len(audio_chunk)
                msg = _build_outbound_media(self._stream_sid, audio_chunk)
                await self._ws.send_text(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in TTS/send for text: %s", text)
            # TTS failure — try Twilio <Say> fallback
            await self._speak_via_twilio_say(text)
            self._speaking = False
            return

        if self._interrupted or self._closed:
            return

        if total_bytes > 0:
            # Twilio buffers audio and plays it back over the phone line.
            # Estimate when playback will actually finish so _speaking stays
            # True until then (enabling caller interruption detection).
            now = asyncio.get_event_loop().time()
            audio_duration = total_bytes / 8000  # μ-law 8kHz = 8000 bytes/sec
            playback_start = max(self._playback_end, now)
            self._playback_end = playback_start + audio_duration
            remaining = self._playback_end - now + 0.3  # 300ms network buffer
            self._schedule_speaking_off(remaining)
        else:
            self._speaking = False

    def _schedule_speaking_off(self, delay: float) -> None:
        """Schedule ``_speaking = False`` after *delay* seconds.

        Cancels any previously scheduled timer so that sequential
        ``_speak()`` calls extend the window correctly.
        """
        if self._speaking_off_task is not None:
            self._speaking_off_task.cancel()
        self._speaking_off_task = asyncio.create_task(self._set_speaking_off(delay))

    async def _set_speaking_off(self, delay: float) -> None:
        """Background helper: wait *delay* seconds then clear ``_speaking``."""
        try:
            await asyncio.sleep(delay)
            if not self._interrupted and not self._closed:
                self._speaking = False
                logger.debug("Playback estimation: _speaking cleared after %.1fs", delay)
        except asyncio.CancelledError:
            pass

    async def _speak_fallback(self, text: str) -> None:
        """Speak a fallback message, trying TTS first, then Twilio <Say>."""
        try:
            self._speaking = True
            async for audio_chunk in self._tts.synthesize_stream(text):
                msg = _build_outbound_media(self._stream_sid, audio_chunk)
                await self._ws.send_text(msg)
            self._speaking = False
        except Exception:
            logger.warning("TTS fallback failed, trying Twilio <Say>")
            await self._speak_via_twilio_say(text)
            self._speaking = False

    async def _speak_via_twilio_say(self, text: str) -> None:
        """Fall back to Twilio REST API <Say> when TTS is unavailable."""
        from app.credentials import (
            get_twilio_account_sid,
            get_twilio_api_key_secret,
            get_twilio_api_key_sid,
            get_twilio_auth_token,
        )

        if not self._call_sid:
            logger.error("Cannot use Twilio <Say>: no call_sid")
            return

        account_sid = get_twilio_account_sid(user_id=self._user_id)
        api_key_sid = get_twilio_api_key_sid(user_id=self._user_id)
        api_key_secret = get_twilio_api_key_secret(user_id=self._user_id)
        auth_token = get_twilio_auth_token(user_id=self._user_id)

        if api_key_sid and api_key_secret:
            auth_pair = (api_key_sid, api_key_secret)
        elif auth_token:
            auth_pair = (account_sid, auth_token)
        else:
            auth_pair = None

        if not account_sid or not auth_pair:
            logger.error("Cannot use Twilio <Say>: missing credentials")
            return

        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f"<Say>{text}</Say>"
            "</Response>"
        )

        import httpx

        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls/{self._call_sid}.json"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    data={"Twiml": twiml},
                    auth=auth_pair,
                )
                if resp.status_code < 300:
                    logger.info("Twilio <Say> fallback succeeded for: %s", text)
                else:
                    logger.error("Twilio <Say> fallback failed (status=%d): %s", resp.status_code, resp.text)
        except Exception:
            logger.exception("Failed to use Twilio <Say> fallback")

    # ------------------------------------------------------------------
    # Error recovery
    # ------------------------------------------------------------------

    async def _handle_llm_failure(self) -> None:
        """Handle an unrecoverable LLM error: speak message + transfer or end call."""
        from app.config import settings

        fallback = settings.callme_fallback_number
        if fallback:
            await self._speak_fallback(ERROR_MSG_TECHNICAL)
            await self._handle_transfer(fallback)
        else:
            await self._speak_fallback(ERROR_MSG_GOODBYE)
            await self._handle_end_call()

    # ------------------------------------------------------------------
    # Call control
    # ------------------------------------------------------------------

    async def _handle_end_call(self) -> None:
        """End the call gracefully after speaking the closing message."""
        logger.info("End-call action — closing pipeline")
        await self.close()

    async def _handle_transfer(self, target_number: str) -> None:
        """Transfer the call to another number via Twilio REST API."""
        from app.credentials import (
            get_twilio_account_sid,
            get_twilio_api_key_secret,
            get_twilio_api_key_sid,
            get_twilio_auth_token,
        )

        logger.info("Transfer action — dialling %s via Twilio REST API", target_number)

        if not self._call_sid:
            logger.error("Cannot transfer: no call_sid available")
            return

        account_sid = get_twilio_account_sid(user_id=self._user_id)
        api_key_sid = get_twilio_api_key_sid(user_id=self._user_id)
        api_key_secret = get_twilio_api_key_secret(user_id=self._user_id)
        auth_token = get_twilio_auth_token(user_id=self._user_id)

        if api_key_sid and api_key_secret:
            auth_pair = (api_key_sid, api_key_secret)
        elif auth_token:
            auth_pair = (account_sid, auth_token)
        else:
            auth_pair = None

        if not account_sid or not auth_pair:
            logger.error("Cannot transfer: missing Twilio credentials")
            return

        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f"<Dial>{target_number}</Dial>"
            "</Response>"
        )

        import httpx

        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls/{self._call_sid}.json"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    data={"Twiml": twiml},
                    auth=auth_pair,
                )
                if resp.status_code < 300:
                    logger.info("Transfer initiated to %s (status=%d)", target_number, resp.status_code)
                else:
                    logger.error(
                        "Twilio transfer failed (status=%d): %s",
                        resp.status_code,
                        resp.text,
                    )
        except Exception:
            logger.exception("Error initiating Twilio transfer to %s", target_number)

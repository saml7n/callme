"""End-to-end voice pipeline: Twilio audio → Deepgram STT → OpenAI LLM → ElevenLabs TTS → Twilio audio.

Orchestrates a single phone call with a hardcoded receptionist system prompt.
Conversation history is maintained for the duration of the call.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

from fastapi import WebSocket

from app.llm.openai import LLMClient
from app.stt.deepgram import DeepgramSTTClient
from app.tts.elevenlabs import ElevenLabsTTSClient
from app.workflow.engine import WorkflowEngine

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a friendly AI receptionist for a business. "
    "Greet the caller, ask how you can help, and have a natural conversation. "
    "Keep responses concise — 1-2 sentences at a time."
)

GREETING = "Hello! Thank you for calling. How can I help you today?"

SENTENCE_ENDINGS = frozenset(".!?")


def _build_outbound_media(stream_sid: str, audio: bytes) -> str:
    """Build a JSON message to send audio back to Twilio."""
    return json.dumps(
        {
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": base64.b64encode(audio).decode("ascii")},
        }
    )


def split_first_sentence(text: str) -> tuple[str, str]:
    """Split text at the first sentence boundary (.!?).

    Returns (sentence, remainder). If no boundary is found,
    returns ("", text) — i.e. nothing to send yet.
    """
    for i, ch in enumerate(text):
        if ch in SENTENCE_ENDINGS:
            return text[: i + 1].strip(), text[i + 1 :]
    return "", text


class CallPipeline:
    """Orchestrates a single call through the STT → LLM → TTS pipeline.

    Usage::

        pipeline = CallPipeline(ws=websocket, stream_sid="MZ...")
        await pipeline.start()          # connects STT, sends greeting
        await pipeline.send_audio(chunk) # called per Twilio media event
        ...
        await pipeline.close()           # cleanup on hang-up / stop
    """

    def __init__(
        self,
        ws: WebSocket,
        stream_sid: str,
        *,
        stt: DeepgramSTTClient | None = None,
        llm: LLMClient | None = None,
        tts: ElevenLabsTTSClient | None = None,
        system_prompt: str = SYSTEM_PROMPT,
        greeting: str = GREETING,
        workflow: dict[str, Any] | None = None,
        engine: WorkflowEngine | None = None,
    ) -> None:
        self._ws = ws
        self._stream_sid = stream_sid
        self._stt = stt or DeepgramSTTClient()
        self._llm = llm or LLMClient()
        self._tts = tts or ElevenLabsTTSClient()
        self._system_prompt = system_prompt
        self._greeting = greeting
        self._messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt},
        ]
        self._transcript_task: asyncio.Task[None] | None = None
        self._final_debounce_task: asyncio.Task[None] | None = None
        self._closed = False

        # Workflow mode: if a workflow dict or engine is provided, delegate to it
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
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to Deepgram, send greeting, start processing transcripts."""
        await self._stt.connect()
        logger.info("Pipeline started — STT connected, sending greeting")

        # Proactive greeting — from engine or hardcoded
        if self._engine is not None:
            greeting = await self._engine.start()
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

        # Cancel the transcript processing task
        if self._transcript_task is not None:
            self._transcript_task.cancel()
            try:
                await self._transcript_task
            except asyncio.CancelledError:
                pass
        self._cancel_debounce()

        # Close STT and TTS clients
        await self._stt.close()
        await self._tts.close()
        logger.info("Pipeline closed — %d messages in history", len(self._messages))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _process_transcripts(self) -> None:
        """Background loop: listen for transcript events and generate responses.

        Triggers on speech_final immediately. If only is_final events arrive
        (speech_final missing), a 1.5s debounce timer fires as a fallback.
        """
        try:
            async for event in self._stt.receive_transcripts():
                if event.transcript:
                    if event.speech_final:
                        # Cancel any pending is_final debounce
                        self._cancel_debounce()
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
                        # Start/reset debounce timer — if speech_final doesn't
                        # arrive within 1.5s, treat this is_final as the utterance.
                        self._cancel_debounce()
                        transcript = event.transcript
                        self._final_debounce_task = asyncio.create_task(
                            self._debounced_handle(transcript, delay=1.5)
                        )
                    else:
                        logger.debug(
                            "Caller [interim]: %s",
                            event.transcript,
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in transcript processing loop")

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
            await self._handle_caller_utterance(transcript)
        except asyncio.CancelledError:
            pass  # speech_final arrived in time, or pipeline closed

    async def _handle_caller_utterance(self, transcript: str) -> None:
        """Process a complete caller utterance through LLM/engine."""
        self._messages.append({"role": "user", "content": transcript})
        if self._engine is not None:
            await self._generate_engine_response(transcript)
        else:
            await self._generate_response()

    async def _generate_response(self) -> None:
        """Stream an LLM response, split into sentences, and TTS each."""
        buffer = ""
        full_response = ""

        try:
            async for chunk in self._llm.chat_stream(self._messages):
                buffer += chunk
                full_response += chunk

                # Eagerly send complete sentences
                while True:
                    sentence, remainder = split_first_sentence(buffer)
                    if not sentence:
                        break
                    buffer = remainder
                    logger.info("LLM sentence → TTS: %s", sentence)
                    await self._speak(sentence)

            # Flush any remaining text
            leftover = buffer.strip()
            if leftover:
                logger.info("LLM remainder → TTS: %s", leftover)
                await self._speak(leftover)

            # Add the complete response to conversation history
            if full_response.strip():
                self._messages.append({"role": "assistant", "content": full_response.strip()})
                logger.info("Assistant: %s", full_response.strip())

        except Exception:
            logger.exception("Error generating LLM response")

    async def _generate_engine_response(self, transcript: str) -> None:
        """Get a response from the WorkflowEngine and speak it."""
        try:
            assert self._engine is not None
            response_text, call_ended = await self._engine.handle_input(transcript)
            if response_text:
                logger.info("Engine response: %s", response_text)
                # Split into sentences for low-latency TTS
                remaining = response_text
                while True:
                    sentence, remaining = split_first_sentence(remaining)
                    if not sentence:
                        break
                    logger.info("Engine sentence → TTS: %s", sentence)
                    await self._speak(sentence)
                leftover = remaining.strip()
                if leftover:
                    logger.info("Engine remainder → TTS: %s", leftover)
                    await self._speak(leftover)
                self._messages.append({"role": "assistant", "content": response_text})
        except Exception:
            logger.exception("Error generating engine response")

    async def _speak(self, text: str) -> None:
        """Synthesize text via TTS and send audio to Twilio."""
        try:
            async for audio_chunk in self._tts.synthesize_stream(text):
                msg = _build_outbound_media(self._stream_sid, audio_chunk)
                await self._ws.send_text(msg)
        except Exception:
            logger.exception("Error in TTS/send for text: %s", text)

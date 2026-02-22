"""Tests for the CallPipeline — end-to-end voice pipeline orchestration."""

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.pipeline import (
    CallPipeline,
    FillerCache,
    FILLER_PHRASES,
    FILLER_THRESHOLD_MS,
    GREETING,
    SYSTEM_PROMPT,
    _build_clear_message,
    split_first_sentence,
)
from app.stt.deepgram import DeepgramConnectionError
from app.workflow.engine import ActionResult


# ---------------------------------------------------------------------------
# Helpers / Fakes
# ---------------------------------------------------------------------------

@dataclass
class FakeTranscriptEvent:
    transcript: str = ""
    is_final: bool = False
    speech_final: bool = False
    confidence: float = 0.0
    start: float = 0.0
    duration: float = 0.0


class FakeSTT:
    """Minimal fake DeepgramSTTClient."""

    def __init__(self, events: list[FakeTranscriptEvent] | None = None):
        self._events = events or []
        self.connected = False
        self.closed = False
        self.audio_chunks: list[bytes] = []

    async def connect(self) -> None:
        self.connected = True

    async def send_audio(self, chunk: bytes) -> None:
        self.audio_chunks.append(chunk)

    async def receive_transcripts(self) -> AsyncGenerator[FakeTranscriptEvent, None]:
        for event in self._events:
            yield event

    async def close(self) -> None:
        self.closed = True


class FakeLLM:
    """Minimal fake LLMClient that yields predetermined chunks."""

    def __init__(self, chunks: list[str] | None = None):
        self._chunks = chunks or []

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[str, None]:
        for chunk in self._chunks:
            yield chunk


class FakeTTS:
    """Minimal fake ElevenLabsTTSClient that yields predetermined audio."""

    def __init__(self, audio_per_call: list[list[bytes]] | None = None):
        self._audio_per_call = audio_per_call or []
        self._call_index = 0
        self.texts_synthesized: list[str] = []
        self.closed = False

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        self.texts_synthesized.append(text)
        if self._call_index < len(self._audio_per_call):
            for chunk in self._audio_per_call[self._call_index]:
                yield chunk
        self._call_index += 1

    async def close(self) -> None:
        self.closed = True


def make_ws_mock() -> AsyncMock:
    """Create a mock WebSocket."""
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# split_first_sentence tests
# ---------------------------------------------------------------------------

class TestSplitFirstSentence:
    def test_splits_on_period(self):
        sentence, remainder = split_first_sentence("Hello world. How are you?")
        assert sentence == "Hello world."
        assert remainder == " How are you?"

    def test_splits_on_exclamation(self):
        sentence, remainder = split_first_sentence("Great! Let me help.")
        assert sentence == "Great!"
        assert remainder == " Let me help."

    def test_splits_on_question_mark(self):
        sentence, remainder = split_first_sentence("Can I help? Sure.")
        assert sentence == "Can I help?"
        assert remainder == " Sure."

    def test_no_boundary_returns_empty_sentence(self):
        sentence, remainder = split_first_sentence("No boundary here")
        assert sentence == ""
        assert remainder == "No boundary here"

    def test_empty_string(self):
        sentence, remainder = split_first_sentence("")
        assert sentence == ""
        assert remainder == ""

    def test_boundary_at_end(self):
        sentence, remainder = split_first_sentence("Done.")
        assert sentence == "Done."
        assert remainder == ""

    def test_multiple_sentences_returns_first_only(self):
        sentence, remainder = split_first_sentence("One. Two. Three.")
        assert sentence == "One."
        assert remainder == " Two. Three."


# ---------------------------------------------------------------------------
# CallPipeline lifecycle tests
# ---------------------------------------------------------------------------

class TestPipelineLifecycle:
    async def test_start_connects_stt_and_sends_greeting(self):
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\x00\x01"]])
        llm = FakeLLM()

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        assert stt.connected
        # Greeting should have been sent via TTS
        assert tts.texts_synthesized == [GREETING]
        # Greeting in conversation history
        assert pipeline.messages[-1] == {"role": "assistant", "content": GREETING}
        # Audio sent to WebSocket
        assert ws.send_text.call_count >= 1
        sent = json.loads(ws.send_text.call_args_list[0][0][0])
        assert sent["event"] == "media"
        assert sent["streamSid"] == "MZ1"

        await pipeline.close()

    async def test_close_cleans_up_resources(self):
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\x00"]])
        llm = FakeLLM()

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()
        await pipeline.close()

        assert stt.closed
        assert tts.closed

    async def test_close_is_idempotent(self):
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\x00"]])
        llm = FakeLLM()

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()
        await pipeline.close()
        await pipeline.close()  # Should not raise

        assert stt.closed
        assert tts.closed

    async def test_send_audio_forwards_to_stt(self):
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\x00"]])
        llm = FakeLLM()

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        await pipeline.send_audio(b"\x80\x80\x80")
        assert stt.audio_chunks == [b"\x80\x80\x80"]

        await pipeline.close()

    async def test_send_audio_noop_after_close(self):
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\x00"]])
        llm = FakeLLM()

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()
        await pipeline.close()

        await pipeline.send_audio(b"\x80\x80\x80")
        assert stt.audio_chunks == []


# ---------------------------------------------------------------------------
# Transcript → LLM → TTS flow
# ---------------------------------------------------------------------------

class TestPipelineTranscriptFlow:
    async def test_speech_final_triggers_llm_and_tts(self):
        """speech_final transcript → LLM response → TTS → Twilio."""
        ws = make_ws_mock()
        stt = FakeSTT(events=[
            FakeTranscriptEvent(
                transcript="I'd like to book an appointment",
                is_final=True,
                speech_final=True,
                confidence=0.99,
            ),
        ])
        llm = FakeLLM(chunks=["Sure!", " I can help with that."])
        # Two TTS calls: "Sure!" and "I can help with that."
        tts = FakeTTS(audio_per_call=[[b"\x01\x02"], [b"\x03\x04"]])

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        # Wait for the background transcript task to finish
        assert pipeline._transcript_task is not None
        await pipeline._transcript_task

        # LLM was called with system prompt + greeting + user message
        messages = pipeline.messages
        assert messages[0]["role"] == "system"
        assert messages[1] == {"role": "assistant", "content": GREETING}
        assert messages[2] == {"role": "user", "content": "I'd like to book an appointment"}
        assert messages[3] == {"role": "assistant", "content": "Sure! I can help with that."}

        # TTS received two sentences
        assert tts.texts_synthesized[0] == GREETING  # greeting
        assert "Sure!" in tts.texts_synthesized[1]
        assert "I can help with that." in tts.texts_synthesized[2]

        await pipeline.close()

    async def test_is_final_debounce_triggers_after_timeout(self):
        """is_final without speech_final triggers LLM after debounce."""
        ws = make_ws_mock()
        stt = FakeSTT(events=[
            FakeTranscriptEvent(
                transcript="Yes please",
                is_final=True,
                speech_final=False,  # no speech_final!
                confidence=0.99,
            ),
        ])
        llm = FakeLLM(chunks=["Sure thing!"])
        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # debounced response
        ])

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        assert pipeline._transcript_task is not None
        await pipeline._transcript_task

        # Debounce task was created — wait for it
        assert pipeline._final_debounce_task is not None
        await pipeline._final_debounce_task

        assert pipeline.messages[2] == {"role": "user", "content": "Yes please"}
        assert pipeline.messages[3]["role"] == "assistant"

        await pipeline.close()

    async def test_interim_transcripts_do_not_trigger_llm(self):
        ws = make_ws_mock()
        stt = FakeSTT(events=[
            FakeTranscriptEvent(
                transcript="I'd like to",
                is_final=False,
                speech_final=False,
                confidence=0.80,
            ),
        ])
        llm = FakeLLM(chunks=["Should not be called."])
        tts = FakeTTS(audio_per_call=[[b"\x00"]])

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        assert pipeline._transcript_task is not None
        await pipeline._transcript_task

        # Only system prompt + greeting in history (no user message, no LLM response)
        assert len(pipeline.messages) == 2

        await pipeline.close()

    async def test_multiple_turns_accumulate_history(self):
        ws = make_ws_mock()
        stt = FakeSTT(events=[
            FakeTranscriptEvent(
                transcript="Hello",
                is_final=True,
                speech_final=True,
                confidence=0.99,
            ),
            FakeTranscriptEvent(
                transcript="What time do you open?",
                is_final=True,
                speech_final=True,
                confidence=0.98,
            ),
        ])
        llm = FakeLLM(chunks=["Hi there!"])
        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # response 1
            [b"\x02"],  # response 2
        ])

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        assert pipeline._transcript_task is not None
        await pipeline._transcript_task

        # system + greeting + user1 + assistant1 + user2 + assistant2
        assert len(pipeline.messages) == 6
        assert pipeline.messages[2]["role"] == "user"
        assert pipeline.messages[2]["content"] == "Hello"
        assert pipeline.messages[3]["role"] == "assistant"
        assert pipeline.messages[4]["role"] == "user"
        assert pipeline.messages[4]["content"] == "What time do you open?"
        assert pipeline.messages[5]["role"] == "assistant"

        await pipeline.close()


# ---------------------------------------------------------------------------
# Sentence splitting in LLM response
# ---------------------------------------------------------------------------

class TestSentenceSplitting:
    async def test_llm_response_split_into_sentences(self):
        """LLM response with multiple sentences triggers multiple TTS calls."""
        ws = make_ws_mock()
        stt = FakeSTT(events=[
            FakeTranscriptEvent(
                transcript="Tell me about your hours",
                is_final=True,
                speech_final=True,
                confidence=0.99,
            ),
        ])
        # LLM streams "We open at 9. We close at 5."
        llm = FakeLLM(chunks=["We open ", "at 9. We ", "close at 5."])
        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # "We open at 9."
            [b"\x02"],  # "We close at 5."
        ])

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        assert pipeline._transcript_task is not None
        await pipeline._transcript_task

        # TTS called: greeting + 2 sentences
        assert tts.texts_synthesized[0] == GREETING
        assert tts.texts_synthesized[1] == "We open at 9."
        assert tts.texts_synthesized[2] == "We close at 5."

        await pipeline.close()

    async def test_llm_response_no_punctuation_sent_as_remainder(self):
        """LLM response without sentence endings is flushed as remainder."""
        ws = make_ws_mock()
        stt = FakeSTT(events=[
            FakeTranscriptEvent(
                transcript="Hi",
                is_final=True,
                speech_final=True,
                confidence=0.99,
            ),
        ])
        llm = FakeLLM(chunks=["Hello there"])
        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # remainder "Hello there"
        ])

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        assert pipeline._transcript_task is not None
        await pipeline._transcript_task

        assert tts.texts_synthesized[1] == "Hello there"

        await pipeline.close()


# ---------------------------------------------------------------------------
# TTS audio → Twilio formatting
# ---------------------------------------------------------------------------

class TestTTSToTwilio:
    async def test_tts_audio_sent_as_base64_media_messages(self):
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\xAA\xBB", b"\xCC\xDD"]])
        llm = FakeLLM()

        pipeline = CallPipeline(ws=ws, stream_sid="MZ42", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        # The greeting should have sent 2 audio chunks via WebSocket
        assert ws.send_text.call_count == 2

        for call in ws.send_text.call_args_list:
            msg = json.loads(call[0][0])
            assert msg["event"] == "media"
            assert msg["streamSid"] == "MZ42"
            # Payload should be valid base64
            payload = msg["media"]["payload"]
            decoded = base64.b64decode(payload)
            assert len(decoded) > 0

        await pipeline.close()


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------

class TestConversationHistory:
    async def test_system_prompt_is_first_message(self):
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\x00"]])
        llm = FakeLLM()

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        assert pipeline.messages[0] == {"role": "system", "content": SYSTEM_PROMPT}

        await pipeline.close()

    async def test_custom_system_prompt(self):
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\x00"]])
        llm = FakeLLM()

        pipeline = CallPipeline(
            ws=ws,
            stream_sid="MZ1",
            stt=stt,
            llm=llm,
            tts=tts,
            system_prompt="Custom prompt",
            greeting="Custom greeting",
        )
        await pipeline.start()

        assert pipeline.messages[0] == {"role": "system", "content": "Custom prompt"}
        assert pipeline.messages[1] == {"role": "assistant", "content": "Custom greeting"}
        assert tts.texts_synthesized[0] == "Custom greeting"

        await pipeline.close()


# ---------------------------------------------------------------------------
# Pipeline with WorkflowEngine
# ---------------------------------------------------------------------------

class FakeEngine:
    """Minimal fake WorkflowEngine for pipeline integration tests."""

    def __init__(
        self,
        greeting: str | ActionResult = "Engine greeting.",
        responses: list[tuple[str | ActionResult, bool]] | None = None,
    ):
        self._greeting = greeting
        self._responses = responses or [("Engine response.", False)]
        self._call_index = 0
        self.inputs: list[str] = []

    async def start(self) -> str | ActionResult:
        return self._greeting

    async def handle_input(self, transcript: str) -> tuple[str | ActionResult, bool]:
        self.inputs.append(transcript)
        if self._call_index < len(self._responses):
            resp = self._responses[self._call_index]
            self._call_index += 1
            return resp
        return ("Fallback.", False)


class TestPipelineWithWorkflow:
    async def test_engine_greeting_used(self):
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\x00"]])
        llm = FakeLLM()
        engine = FakeEngine(greeting="Welcome to Smile Dental!")

        pipeline = CallPipeline(
            ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts, engine=engine,
        )
        await pipeline.start()

        assert tts.texts_synthesized[0] == "Welcome to Smile Dental!"
        assert pipeline.messages[1] == {"role": "assistant", "content": "Welcome to Smile Dental!"}

        await pipeline.close()

    async def test_engine_handles_speech_final(self):
        ws = make_ws_mock()
        stt = FakeSTT(events=[
            FakeTranscriptEvent(
                transcript="I need a cleaning",
                is_final=True,
                speech_final=True,
                confidence=0.99,
            ),
        ])
        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # engine response
        ])
        llm = FakeLLM()
        engine = FakeEngine(
            greeting="Hi!",
            responses=[("Sure, I can help with that.", False)],
        )

        pipeline = CallPipeline(
            ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts, engine=engine,
        )
        await pipeline.start()
        assert pipeline._transcript_task is not None
        await pipeline._transcript_task

        # Engine was called with the transcript
        assert engine.inputs == ["I need a cleaning"]
        # TTS got the engine's response
        assert "Sure, I can help with that." in tts.texts_synthesized

        await pipeline.close()


class TestPipelineWithoutWorkflow:
    async def test_falls_back_to_hardcoded_prompt(self):
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\x00"]])
        llm = FakeLLM()

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        # Uses default GREETING
        assert tts.texts_synthesized[0] == GREETING
        assert pipeline.messages[0] == {"role": "system", "content": SYSTEM_PROMPT}

        await pipeline.close()


# ---------------------------------------------------------------------------
# Pipeline with ActionResult — end_call and transfer
# ---------------------------------------------------------------------------

class TestPipelineEndCallAction:
    async def test_end_call_action_speaks_and_closes(self):
        """ActionResult end_call → speak message, then close pipeline."""
        ws = make_ws_mock()
        stt = FakeSTT(events=[
            FakeTranscriptEvent(
                transcript="I'm done",
                is_final=True,
                speech_final=True,
                confidence=0.99,
            ),
        ])
        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # end_call message
        ])
        llm = FakeLLM()
        action = ActionResult(
            action_type="end_call",
            message="Thank you for calling! Goodbye.",
            call_ended=True,
        )
        engine = FakeEngine(
            greeting="Hi!",
            responses=[(action, True)],
        )

        pipeline = CallPipeline(
            ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts, engine=engine,
        )
        await pipeline.start()
        assert pipeline._transcript_task is not None
        await pipeline._transcript_task

        # Message was spoken via TTS
        assert "Thank you for calling! Goodbye." in tts.texts_synthesized
        # Pipeline closed
        assert pipeline._closed is True

    async def test_end_call_action_as_greeting(self):
        """If engine.start() returns end_call ActionResult, speak and close immediately."""
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\x00"]])
        llm = FakeLLM()
        greeting_action = ActionResult(
            action_type="end_call",
            message="We're closed. Please call back tomorrow.",
            call_ended=True,
        )
        engine = FakeEngine(greeting=greeting_action)

        pipeline = CallPipeline(
            ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts, engine=engine,
        )
        await pipeline.start()

        assert "We're closed. Please call back tomorrow." in tts.texts_synthesized
        assert pipeline._closed is True
        # No transcript task started (call ended immediately)
        assert pipeline._transcript_task is None


class TestPipelineTransferAction:
    async def test_transfer_action_speaks_announcement(self):
        """ActionResult transfer → speak announcement."""
        ws = make_ws_mock()
        stt = FakeSTT(events=[
            FakeTranscriptEvent(
                transcript="Connect me to someone",
                is_final=True,
                speech_final=True,
                confidence=0.99,
            ),
        ])
        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # transfer announcement
        ])
        llm = FakeLLM()
        action = ActionResult(
            action_type="transfer",
            message="I'll connect you now.",
            call_ended=False,
            transfer_number="+447908121095",
        )
        engine = FakeEngine(
            greeting="Hi!",
            responses=[(action, False)],
        )

        pipeline = CallPipeline(
            ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts, engine=engine,
            call_sid="CA123",
        )
        await pipeline.start()
        assert pipeline._transcript_task is not None

        # Patch _handle_transfer to avoid real HTTP call
        pipeline._handle_transfer = AsyncMock()
        await pipeline._transcript_task

        assert "I'll connect you now." in tts.texts_synthesized
        pipeline._handle_transfer.assert_awaited_once_with("+447908121095")

    async def test_transfer_skipped_without_call_sid(self):
        """Transfer logs error and returns when no call_sid is available."""
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\x00"]])
        llm = FakeLLM()

        pipeline = CallPipeline(
            ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts,
            call_sid="",
        )
        await pipeline.start()

        # Directly test _handle_transfer with no call_sid set
        await pipeline._handle_transfer("+441234567890")
        # Should not raise — just logs error and returns
        await pipeline.close()


# ---------------------------------------------------------------------------
# Interruption handling
# ---------------------------------------------------------------------------


class TestInterruption:
    async def test_speech_final_during_speaking_sends_clear(self):
        """When the AI is 'speaking' and caller says something, a clear message
        is sent to Twilio to stop playback."""
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\x00"]])
        llm = FakeLLM()

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        # Simulate AI speaking
        pipeline._speaking = True
        await pipeline._interrupt()

        # Verify clear message sent
        calls = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
        clear_calls = [c for c in calls if c.get("event") == "clear"]
        assert len(clear_calls) >= 1
        assert clear_calls[0]["streamSid"] == "MZ1"
        assert pipeline._interrupted is True

        await pipeline.close()

    async def test_interrupt_noop_when_not_speaking(self):
        """Interrupt is a no-op when the AI is not speaking."""
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\x00"]])
        llm = FakeLLM()

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        initial_calls = ws.send_text.call_count
        pipeline._speaking = False
        await pipeline._interrupt()

        # No additional calls — interrupt was a no-op
        assert ws.send_text.call_count == initial_calls
        assert pipeline._interrupted is False

        await pipeline.close()

    async def test_build_clear_message_structure(self):
        """_build_clear_message returns the correct JSON structure."""
        msg = json.loads(_build_clear_message("MZ42"))
        assert msg == {"event": "clear", "streamSid": "MZ42"}


# ---------------------------------------------------------------------------
# Filler phrase cache
# ---------------------------------------------------------------------------


class TestFillerCache:
    async def test_warm_populates_clips(self):
        """FillerCache.warm() synthesizes all filler phrases."""
        tts = FakeTTS(audio_per_call=[
            [b"\x01"] for _ in FILLER_PHRASES
        ])
        cache = FillerCache()
        await cache.warm(tts)

        assert cache.ready is True
        assert len(tts.texts_synthesized) == len(FILLER_PHRASES)
        for phrase in FILLER_PHRASES:
            assert phrase in tts.texts_synthesized

    async def test_next_clip_cycles(self):
        """next_clip() cycles through available clips round-robin."""
        tts = FakeTTS(audio_per_call=[
            [b"\x01"], [b"\x02"], [b"\x03"],
        ])
        cache = FillerCache()
        # Manually add 3 clips
        cache._clips = [b"\x01", b"\x02", b"\x03"]

        assert cache.next_clip() == b"\x01"
        assert cache.next_clip() == b"\x02"
        assert cache.next_clip() == b"\x03"
        assert cache.next_clip() == b"\x01"  # wraps around

    def test_next_clip_returns_none_when_empty(self):
        """next_clip() returns None when cache is empty."""
        cache = FillerCache()
        assert cache.next_clip() is None

    def test_ready_is_false_when_empty(self):
        """ready is False before warming."""
        cache = FillerCache()
        assert cache.ready is False


# ---------------------------------------------------------------------------
# Error recovery — Deepgram reconnect
# ---------------------------------------------------------------------------


class FakeSTTWithDisconnect:
    """STT client that disconnects after yielding some events."""

    def __init__(self, events_before_disconnect: list[FakeTranscriptEvent]):
        self._events = events_before_disconnect
        self.connected = False
        self.closed = False
        self.audio_chunks: list[bytes] = []
        self.connect_count = 0

    async def connect(self) -> None:
        self.connected = True
        self.connect_count += 1

    async def send_audio(self, chunk: bytes) -> None:
        self.audio_chunks.append(chunk)

    async def receive_transcripts(self) -> AsyncGenerator[FakeTranscriptEvent, None]:
        # Yield events then raise disconnect
        for event in self._events:
            yield event
        raise DeepgramConnectionError("Connection lost")

    async def close(self) -> None:
        self.closed = True


class TestErrorRecovery:
    async def test_speak_fallback_uses_tts_first(self):
        """_speak_fallback tries TTS before Twilio <Say>."""
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # fallback message
        ])
        llm = FakeLLM()

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        await pipeline._speak_fallback("Something went wrong")
        assert "Something went wrong" in tts.texts_synthesized

        await pipeline.close()

    async def test_handle_llm_failure_without_fallback_number(self, monkeypatch):
        """When LLM fails and no fallback number, speak goodbye and end call."""
        from app.config import settings as _settings
        monkeypatch.setattr(_settings, "callme_fallback_number", "")
        from app.pipeline import ERROR_MSG_GOODBYE

        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # goodbye message
        ])
        llm = FakeLLM()

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()
        await pipeline._handle_llm_failure()

        assert ERROR_MSG_GOODBYE in tts.texts_synthesized
        assert pipeline._closed is True

        # Don't call close() again — already closed

    async def test_handle_llm_failure_with_fallback_number(self, monkeypatch):
        """When LLM fails and fallback number is set, speak tech msg + transfer."""
        from app.config import settings as _settings
        monkeypatch.setattr(_settings, "callme_fallback_number", "+441234567890")
        from app.pipeline import ERROR_MSG_TECHNICAL

        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # technical error message
        ])
        llm = FakeLLM()

        pipeline = CallPipeline(
            ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts, call_sid="CA123"
        )
        await pipeline.start()

        # Patch _handle_transfer to avoid real HTTP call
        pipeline._handle_transfer = AsyncMock()
        await pipeline._handle_llm_failure()

        assert ERROR_MSG_TECHNICAL in tts.texts_synthesized
        pipeline._handle_transfer.assert_awaited_once_with("+441234567890")

        await pipeline.close()


# ---------------------------------------------------------------------------
# Close method — internal vs external calls
# ---------------------------------------------------------------------------


class TestPipelineClose:
    async def test_close_from_external_awaits_tasks(self):
        """When close() is called from outside (e.g. media_stream), tasks are awaited."""
        ws = make_ws_mock()
        stt = FakeSTT(events=[])
        tts = FakeTTS(audio_per_call=[[b"\x00"]])
        llm = FakeLLM()

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()
        await pipeline.close()

        assert pipeline._closed is True
        assert stt.closed is True
        assert tts.closed is True

    async def test_close_from_end_call_does_not_deadlock(self):
        """When close() is called from _handle_end_call (inside _response_task),
        it must not deadlock from circular awaits."""
        ws = make_ws_mock()
        stt = FakeSTT(events=[
            FakeTranscriptEvent(
                transcript="Bye",
                is_final=True,
                speech_final=True,
                confidence=0.99,
            ),
        ])
        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # end_call message
        ])
        llm = FakeLLM()
        action = ActionResult(
            action_type="end_call",
            message="Goodbye!",
            call_ended=True,
        )
        engine = FakeEngine(
            greeting="Hi!",
            responses=[(action, True)],
        )

        pipeline = CallPipeline(
            ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts, engine=engine,
        )
        await pipeline.start()
        assert pipeline._transcript_task is not None

        # This should complete without deadlock or recursion error
        await pipeline._transcript_task

        assert pipeline._closed is True
        assert "Goodbye!" in tts.texts_synthesized


# ---------------------------------------------------------------------------
# Filler phrase timing tests
# ---------------------------------------------------------------------------


class TestFillerTiming:
    async def test_filler_cancelled_when_llm_responds_quickly(self):
        """If LLM starts producing tokens quickly (< 800ms), filler is cancelled."""
        from app.pipeline import _filler_cache

        ws = make_ws_mock()
        stt = FakeSTT(events=[
            FakeTranscriptEvent(
                transcript="Quick question",
                is_final=True,
                speech_final=True,
                confidence=0.99,
            ),
        ])
        # LLM responds immediately (no delay)
        llm = FakeLLM(chunks=["Sure thing."])
        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # LLM response
        ])

        # Ensure filler cache has clips
        _filler_cache._clips = [b"\xFF"]
        _filler_cache._index = 0

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        assert pipeline._transcript_task is not None
        await pipeline._transcript_task

        # Only greeting + the real response should be spoken — no filler
        assert tts.texts_synthesized == [GREETING, "Sure thing."]

        await pipeline.close()
        # Restore filler cache state
        _filler_cache._clips = []

    async def test_filler_played_when_llm_is_slow(self):
        """If LLM takes > 800ms, filler audio is sent to the WebSocket."""
        from app.pipeline import _filler_cache

        ws = make_ws_mock()
        stt = FakeSTT(events=[
            FakeTranscriptEvent(
                transcript="Complex question",
                is_final=True,
                speech_final=True,
                confidence=0.99,
            ),
        ])

        filler_audio = b"\xFA\xFB"
        _filler_cache._clips = [filler_audio]
        _filler_cache._index = 0

        class SlowLLM:
            async def chat_stream(self, messages, tools=None):
                await asyncio.sleep(1.0)  # Over the 800ms threshold
                yield "Here you go."

        llm = SlowLLM()
        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # LLM response
        ])

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)
        await pipeline.start()

        assert pipeline._transcript_task is not None
        await pipeline._transcript_task

        # Check that filler audio was sent to the WS (as base64 media message)
        all_sent = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
        media_payloads = [
            base64.b64decode(m["media"]["payload"])
            for m in all_sent
            if m.get("event") == "media"
        ]
        assert filler_audio in media_payloads

        await pipeline.close()
        _filler_cache._clips = []


# ---------------------------------------------------------------------------
# Deepgram reconnect tests
# ---------------------------------------------------------------------------


class FakeSTTReconnectable:
    """STT that disconnects on first receive_transcripts, works on second."""

    def __init__(self, events_on_reconnect: list[FakeTranscriptEvent]):
        self._events_on_reconnect = events_on_reconnect
        self.connected = False
        self.closed = False
        self.audio_chunks: list[bytes] = []
        self.connect_count = 0
        self._call_index = 0

    async def connect(self) -> None:
        self.connected = True
        self.connect_count += 1

    async def send_audio(self, chunk: bytes) -> None:
        self.audio_chunks.append(chunk)

    async def receive_transcripts(self) -> AsyncGenerator[FakeTranscriptEvent, None]:
        self._call_index += 1
        if self._call_index == 1:
            raise DeepgramConnectionError("Connection lost")
        for event in self._events_on_reconnect:
            yield event

    async def close(self) -> None:
        self.closed = True


class TestDeepgramReconnect:
    async def test_reconnect_success(self, monkeypatch):
        """Deepgram disconnect → reconnect → transcript processing continues."""
        ws = make_ws_mock()
        events_after_reconnect = [
            FakeTranscriptEvent(
                transcript="Hello after reconnect",
                is_final=True,
                speech_final=True,
                confidence=0.99,
            ),
        ]
        reconnectable_stt = FakeSTTReconnectable(events_on_reconnect=events_after_reconnect)

        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # response to "Hello after reconnect"
        ])
        llm = FakeLLM(chunks=["Response."])

        pipeline = CallPipeline(
            ws=ws, stream_sid="MZ1", stt=reconnectable_stt, llm=llm, tts=tts,
        )

        # Monkeypatch DeepgramSTTClient constructor to return our reconnectable fake
        monkeypatch.setattr(
            "app.pipeline.DeepgramSTTClient",
            lambda: reconnectable_stt,
        )

        await pipeline.start()
        assert pipeline._transcript_task is not None
        await pipeline._transcript_task

        # The reconnectable STT was called twice (disconnect + reconnect)
        assert reconnectable_stt.connect_count >= 2
        # LLM got the transcript from after reconnect
        assert "Response." in tts.texts_synthesized

        await pipeline.close()

    async def test_reconnect_fails_speaks_fallback(self, monkeypatch):
        """Deepgram disconnect → reconnect fails → fallback message spoken."""
        from app.pipeline import ERROR_MSG_HEARING

        ws = make_ws_mock()
        stt = FakeSTTWithDisconnect(events_before_disconnect=[])

        tts = FakeTTS(audio_per_call=[
            [b"\x00"],  # greeting
            [b"\x01"],  # fallback message
        ])
        llm = FakeLLM()

        pipeline = CallPipeline(
            ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts,
        )

        # Make reconnect attempt fail
        class FailingSTT:
            async def connect(self):
                raise Exception("Cannot reconnect")
            async def receive_transcripts(self):
                raise DeepgramConnectionError("Still dead")
                yield  # make it a generator
            async def close(self):
                pass
            async def send_audio(self, chunk):
                pass

        monkeypatch.setattr(
            "app.pipeline.DeepgramSTTClient",
            lambda: FailingSTT(),
        )

        await pipeline.start()
        assert pipeline._transcript_task is not None
        await pipeline._transcript_task

        # Fallback message was spoken
        assert ERROR_MSG_HEARING in tts.texts_synthesized

        await pipeline.close()


# ---------------------------------------------------------------------------
# TTS failure → Twilio <Say> fallback
# ---------------------------------------------------------------------------


class FakeTTSWithFailure:
    """TTS that raises on first call after greeting."""

    def __init__(self, fail_on_call: int = 1):
        self._fail_on_call = fail_on_call
        self._call_index = 0
        self.texts_synthesized: list[str] = []
        self.closed = False

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        self.texts_synthesized.append(text)
        if self._call_index == self._fail_on_call:
            self._call_index += 1
            raise Exception("ElevenLabs is down")
        self._call_index += 1
        yield b"\x00"

    async def close(self) -> None:
        self.closed = True


class TestTTSFailureFallback:
    async def test_tts_failure_falls_back_to_twilio_say(self, monkeypatch):
        """When TTS raises during _speak(), falls back to _speak_via_twilio_say."""
        ws = make_ws_mock()
        stt = FakeSTT(events=[
            FakeTranscriptEvent(
                transcript="Help",
                is_final=True,
                speech_final=True,
                confidence=0.99,
            ),
        ])
        llm = FakeLLM(chunks=["Let me help."])
        tts = FakeTTSWithFailure(fail_on_call=1)  # fails on second call (first is greeting)

        pipeline = CallPipeline(ws=ws, stream_sid="MZ1", stt=stt, llm=llm, tts=tts)

        twilio_say_called_with: list[str] = []
        original_say = pipeline._speak_via_twilio_say

        async def mock_twilio_say(text: str) -> None:
            twilio_say_called_with.append(text)

        pipeline._speak_via_twilio_say = mock_twilio_say

        await pipeline.start()
        assert pipeline._transcript_task is not None
        await pipeline._transcript_task

        # TTS was attempted for the LLM response
        assert "Let me help." in tts.texts_synthesized
        # Twilio <Say> fallback was invoked
        assert "Let me help." in twilio_say_called_with

        await pipeline.close()

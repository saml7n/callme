"""Tests for the CallPipeline — end-to-end voice pipeline orchestration."""

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.pipeline import CallPipeline, SYSTEM_PROMPT, GREETING, split_first_sentence
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

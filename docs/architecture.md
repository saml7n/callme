# CallMe — AI Receptionist: Architecture & Plan

> **Status:** Planning / Pre-implementation  
> **Last updated:** 20 February 2026  
> **Approach:** Option B — Hybrid (own orchestration + best-in-class services)

---

## 1. Vision & End State

CallMe is an AI-powered phone receptionist that:

- **Answers inbound calls** on a real phone number via Twilio.
- **Transcribes caller speech in real time** using Deepgram's streaming STT.
- **Routes conversations through configurable workflows** defined as directed graphs (nodes + edges).
- **Responds with natural, realistic voice** powered by ElevenLabs TTS.
- **Lets non-technical users design call flows** in a drag-and-drop React Flow visual builder — no code required.
- **Persists workflows, call logs, and transcripts** for review and iteration.

### What "done" looks like (PoC)

1. A user dials the Twilio number.
2. The system answers within ~1 second and plays a greeting defined in the active workflow.
3. The caller speaks; the system transcribes, reasons via LLM, and responds vocally — all within ~800ms round-trip.
4. The conversation follows a workflow graph: collecting information, looking up data via API calls, transferring to a human, or ending the call.
5. After the call, a full transcript and metadata are stored and viewable in the dashboard.
6. An admin can open the workflow builder, rearrange nodes, change prompts/voices, and publish — changes take effect on the next call.

---

## 2. System Architecture

```
┌─────────────┐       ┌──────────────────────────────────────────────┐
│   Caller     │       │              CallMe Server (Python)          │
│  (phone)     │       │                                              │
│              │  ←──→ │  ┌──────────┐   ┌─────────┐   ┌──────────┐ │
│              │       │  │ Twilio   │   │Workflow │   │ Call     │ │
│              │       │  │ WebSocket│──→│ Engine  │──→│ Logger   │ │
│              │       │  │ Handler  │   │(state   │   │          │ │
│              │       │  │          │   │ machine)│   └──────────┘ │
│              │       │  └────┬─────┘   └────┬────┘               │
│              │       │       │              │                     │
│              │       │  ┌────▼─────┐   ┌────▼────┐               │
│              │       │  │ Deepgram │   │ LLM     │               │
│              │       │  │ STT      │   │(GPT-4o/ │               │
│              │       │  │(streaming│   │ Claude) │               │
│              │       │  │ WS)      │   └────┬────┘               │
│              │       │  └──────────┘        │                     │
│              │       │                 ┌────▼─────┐               │
│              │       │                 │ElevenLabs│               │
│              │       │                 │ TTS      │               │
│              │       │                 │(μ-law)   │               │
│              │       │                 └──────────┘               │
│              │       └──────────────────────────────────────────────┘
│              │
│              │       ┌──────────────────────────────────────────────┐
│              │       │           Web Dashboard (React)              │
│   Admin      │  ←──→ │  ┌──────────────┐  ┌───────────────┐       │
│  (browser)   │       │  │ React Flow   │  │ Call Logs /   │       │
│              │       │  │ Workflow     │  │ Transcripts   │       │
│              │       │  │ Builder      │  │ Viewer        │       │
│              │       │  └──────────────┘  └───────────────┘       │
│              │       └──────────────────────────────────────────────┘
```

### Audio Pipeline (per call, real-time)

```
Caller speaks
    │
    ▼
Twilio captures μ-law 8kHz audio
    │
    ▼ (bidirectional WebSocket)
Server receives audio chunks
    │
    ▼
Deepgram STT (streaming WebSocket)
    │  → interim transcripts (for early processing)
    │  → final transcript + speech_final event
    ▼
Workflow Engine evaluates current node
    │  → selects system prompt, tools, transition conditions
    ▼
LLM generates response (GPT-4o / Claude)
    │  → may trigger tool calls (API lookups, transfers)
    ▼
ElevenLabs TTS converts text → μ-law audio
    │
    ▼ (back over bidirectional WebSocket)
Twilio plays audio to caller
```

**Target latency budget:**

| Stage | Target | Notes |
|---|---|---|
| Twilio → Server | ~50ms | WebSocket, negligible |
| STT (endpointing + final) | ~200-400ms | Deepgram Flux model; tune endpointing sensitivity |
| LLM inference | ~200-400ms | Streaming response; start TTS before full response |
| TTS generation | ~150-250ms | ElevenLabs latency-optimized mode (`optimize_streaming_latency=3`) |
| Server → Twilio | ~50ms | WebSocket, negligible |
| **Total round-trip** | **~650-1150ms** | Filler phrases ("One moment…") if > 800ms |

---

## 3. Technology Stack

| Layer | Technology | Why |
|---|---|---|
| **Telephony** | Twilio Voice + Media Streams | Industry standard; bidirectional WebSocket streaming; global phone numbers |
| **STT** | Deepgram (Nova-3 / Flux) | Native WebSocket streaming; lowest latency; endpointing built-in; μ-law support |
| **LLM** | OpenAI GPT-4o (primary), Claude (swappable) | Function/tool calling for workflow actions; streaming responses |
| **TTS** | ElevenLabs | Most realistic voices; μ-law output for Twilio; latency-optimized mode |
| **Server** | Python 3.12+ | Excellent async ecosystem (asyncio); rich AI/ML library support; fast prototyping |
| **Package manager** | uv | Fast, modern Python package manager; replaces pip/poetry; manages venvs and deps |
| **Web framework** | FastAPI | Async-native; automatic OpenAPI docs; WebSocket support built-in |
| **Workflow builder** | React + React Flow (`@xyflow/react`) | De facto standard for node-based visual editors; custom nodes are React components |
| **Persistence** | SQLite (PoC) → Postgres (prod) | Zero-config for PoC; easy migration path |
| **ORM** | SQLAlchemy 2.0 + SQLModel | Async support; Pydantic integration via SQLModel |

---

## 4. Workflow System Design

### 4.1 Node Types

Three node types, built incrementally across stories:

| Node Type | Purpose | Config | Built in |
|---|---|---|---|
| **Conversation** | Talks to the caller following plain-English instructions. Maintains its own chat history. A Router LLM decides each turn whether to STAY or transition. | `instructions` (str), `examples` (list), `max_iterations` (int) | Story 7 |
| **Decision** | Pure routing — no conversation with the caller. Evaluates accumulated context and picks an outgoing edge. | `instruction` (str) | Story 8 |
| **Action** | Performs a side effect (end call, transfer, etc.). Extensible — new action types added over time. | `action_type` (str) + type-specific fields | Story 9 |

### 4.2 Two LLM Roles Per Turn

Every conversation turn uses two LLM calls:

1. **Router LLM** (cheap/fast, e.g. GPT-4o-mini): Sees the current node, outgoing edge labels (plain English), and conversation history. Returns `STAY` or the ID of the edge to follow. **One call replaces all edge condition evaluation.**
2. **Responder LLM** (GPT-4o): Sees the current node's `instructions`, `examples`, accumulated summaries from previous nodes, and the current node's chat history. Generates the natural language reply.

Decision nodes use only the Router LLM. Action nodes use neither (they execute side effects directly).

### 4.3 Per-Node Chat History & Context Passing

Each conversation node maintains its **own `messages[]`** array — separate from other nodes. When transitioning:
1. A summary of the outgoing node's conversation is generated via LLM.
2. Key information is extracted (names, dates, intents, etc.).
3. The next node receives accumulated `NodeSummary` objects as context prefix.

This keeps per-node LLM context focused and avoids bloat across long multi-node calls.

### 4.4 Graph Format (JSON)

Workflows are stored as a JSON document with `nodes` and `edges`:

```json
{
  "id": "wf_001",
  "name": "Dental Reception",
  "version": 1,
  "entry_node_id": "node_1",
  "nodes": [
    {
      "id": "node_1",
      "type": "conversation",
      "data": {
        "instructions": "You are a friendly receptionist for Smile Dental. Greet the caller warmly and ask how you can help today.",
        "examples": [
          { "role": "user", "content": "Hi, I'd like to book a cleaning" },
          { "role": "assistant", "content": "Of course! I'd be happy to help. Could I get your name first?" }
        ],
        "max_iterations": 5
      },
      "position": { "x": 100, "y": 100 }
    },
    {
      "id": "node_2",
      "type": "decision",
      "data": {
        "instruction": "Determine the caller's primary intent."
      },
      "position": { "x": 100, "y": 250 }
    },
    {
      "id": "node_3",
      "type": "conversation",
      "data": {
        "instructions": "Help the caller book a dental appointment. Ask for preferred date, time, and service type.",
        "examples": [],
        "max_iterations": 10
      },
      "position": { "x": -100, "y": 400 }
    },
    {
      "id": "node_4",
      "type": "action",
      "data": {
        "action_type": "transfer",
        "target_number": "+441234567890",
        "announcement": "I'll connect you with our team now. One moment please."
      },
      "position": { "x": 300, "y": 400 }
    },
    {
      "id": "node_5",
      "type": "action",
      "data": {
        "action_type": "end_call",
        "message": "Thank you for calling Smile Dental! Goodbye!"
      },
      "position": { "x": -100, "y": 550 }
    }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2", "label": "Caller has stated their need" },
    { "id": "e2", "source": "node_2", "target": "node_3", "label": "Caller wants to book an appointment" },
    { "id": "e3", "source": "node_2", "target": "node_4", "label": "Caller wants to speak to a person" },
    { "id": "e4", "source": "node_3", "target": "node_5", "label": "Appointment details confirmed" }
  ]
}
```

### 4.5 Edge Labels (replacing typed conditions)

Edges have a plain-English `label` describing when to follow them. The Router LLM interprets these against conversation context — no expression evaluator or per-edge LLM calls needed.

| Old approach (removed) | New approach |
|---|---|
| `condition: null` (unconditional) | Edge with a descriptive label; Router picks it when appropriate |
| `condition: { type: "expression", expr: "..." }` | Not needed — Router LLM handles routing |
| `condition: { type: "llm", prompt: "..." }` | Edge `label` serves same purpose; Router evaluates all edges in one call |

### 4.6 Workflow Engine (State Machine)

```python
class WorkflowEngine:
    workflow: Graph
    current_node: Node
    node_histories: dict[str, list[dict]]  # per-node chat histories
    summaries: list[NodeSummary]           # accumulated across transitions

    async def start() -> str:
        # Enter entry node, generate initial response via Responder LLM

    async def handle_input(transcript: str) -> tuple[str, bool]:
        # 1. Append transcript to current node's chat history
        # 2. Router LLM: STAY or follow edge?
        # 3a. STAY → Responder LLM generates reply from node instructions + chat history
        # 3b. TRANSITION → summarise current node, carry forward, enter new node
        # 4. Check max_iterations → force transition if exceeded
        # Returns (response_text, call_ended)
```

---

## 5. Implementation Phases

### Phase 1 — Skeleton & Voice Pipeline (Stories 0-6, Week 1-2)

- [x] Project scaffolding: `server/` (Python + FastAPI) and `web/` (React)
- [x] Twilio account setup: phone number purchased, webhook configured
- [x] Incoming call webhook → `<Connect><Stream>` TwiML
- [x] WebSocket server: receive Twilio media events, decode μ-law audio
- [x] Deepgram STT client (standalone, tested with live audio)
- [x] LLM client (standalone, streaming + tool calling + structured output)
- [ ] ElevenLabs TTS client (standalone, μ-law output)
- [ ] Pipe STT → LLM → TTS end-to-end with hardcoded system prompt
- [ ] **Milestone:** Make a phone call, have a free-form AI conversation

### Phase 2 — Workflow Engine (Stories 7-9, Week 3-4)

- [ ] Conversation nodes: per-node instructions, examples, max_iterations, own chat history
- [ ] Router LLM (STAY or transition) + Responder LLM (generate reply)
- [ ] Context passing: node summaries + key info carried between nodes
- [ ] Decision nodes: pure routing, no caller conversation
- [ ] Action nodes: end_call, transfer (extensible action_type)
- [ ] Wire engine into voice pipeline (replaces hardcoded prompt)
- [ ] **Milestone:** Call follows a multi-node workflow with branching

### Phase 3 — Persistence & Visual Builder (Stories 10-12, Week 5-6)

- [ ] REST API: workflow CRUD, call logs, event logging
- [ ] SQLite persistence (workflows survive restarts)
- [ ] React Flow visual builder: conversation, decision, action nodes
- [ ] Edge labels editable in the builder
- [ ] Save/publish workflows from the UI
- [ ] Call log viewer: transcript timeline, workflow path, node summaries
- [ ] **Milestone:** Build a workflow in the browser, publish it, call the number, review the logs

### Phase 4 — Polish (Story 13, Week 7)

- [ ] Interruption handling (clear TTS on caller speech)
- [ ] Filler phrases for LLM latency
- [ ] Error handling & graceful degradation
- [ ] Basic auth on dashboard + Twilio signature validation
- [ ] **Milestone:** PoC demo-ready

---

## 6. Project Structure (Planned)

```
callme/
├── docs/
│   └── architecture.md          ← you are here
├── server/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── config.py            # Settings via pydantic-settings
│   │   ├── twilio/
│   │   │   ├── webhook.py       # TwiML response for incoming calls
│   │   │   └── media_stream.py  # Bidirectional WebSocket handler
│   │   ├── stt/
│   │   │   └── deepgram.py      # Deepgram streaming client
│   │   ├── llm/
│   │   │   └── openai.py        # LLM client (swappable)
│   │   ├── tts/
│   │   │   └── elevenlabs.py    # ElevenLabs TTS client (μ-law output)
│   │   ├── workflow/
│   │   │   ├── engine.py        # State machine — Router + Responder LLM orchestration
│   │   │   ├── schema.py        # Pydantic models for workflow JSON validation
│   │   │   └── models.py        # NodeSummary, WorkflowContext dataclasses
│   │   ├── db/
│   │   │   ├── models.py        # SQLAlchemy/SQLModel schemas
│   │   │   └── session.py       # Async DB session factory
│   │   └── api/
│   │       ├── workflows.py     # CRUD endpoints for workflows
│   │       └── calls.py         # Call log endpoints
│   ├── pyproject.toml
│   └── requirements.txt
├── web/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── flow-builder/
│   │   │   │   ├── FlowCanvas.tsx       # React Flow canvas
│   │   │   │   ├── nodes/               # Custom node components
│   │   │   │   │   ├── GreetingNode.tsx
│   │   │   │   │   ├── CollectInfoNode.tsx
│   │   │   │   │   ├── ApiCallNode.tsx
│   │   │   │   │   ├── TransferNode.tsx
│   │   │   │   │   └── EndCallNode.tsx
│   │   │   │   └── panels/
│   │   │   │       └── NodeConfigPanel.tsx
│   │   │   └── call-logs/
│   │   │       └── CallLogViewer.tsx
│   │   └── api/
│   │       └── client.ts        # REST client for server API
│   ├── package.json
│   └── tsconfig.json
└── README.md
```

---

## 7. Key Reference Documentation

### Twilio

| Resource | URL |
|---|---|
| Voice overview | https://www.twilio.com/docs/voice |
| TwiML `<Connect><Stream>` (bidirectional) | https://www.twilio.com/docs/voice/twiml/connect |
| Media Streams overview | https://www.twilio.com/docs/voice/media-streams |
| Media Streams WebSocket messages | https://www.twilio.com/docs/voice/media-streams/websocket-messages |
| Bidirectional Media Streams guide | https://www.twilio.com/docs/voice/media-streams/bidirectional-media-streams |
| TwiML `<Start><Stream>` (unidirectional) | https://www.twilio.com/docs/voice/twiml/stream |
| Buy & configure phone numbers | https://www.twilio.com/docs/phone-numbers |

### Deepgram (STT)

| Resource | URL |
|---|---|
| Streaming STT (WebSocket) | https://developers.deepgram.com/docs/getting-started-with-live-streaming-audio |
| Deepgram Python SDK | https://developers.deepgram.com/docs/python-sdk |
| Endpointing config | https://developers.deepgram.com/docs/endpointing |
| Smart formatting | https://developers.deepgram.com/docs/smart-format |
| Nova-3 / Flux models | https://developers.deepgram.com/docs/models-overview |

### ElevenLabs (TTS)

| Resource | URL |
|---|---|
| Text-to-Speech API | https://elevenlabs.io/docs/api-reference/text-to-speech |
| Streaming TTS (WebSocket) | https://elevenlabs.io/docs/api-reference/text-to-speech/stream |
| Output formats (μ-law for Twilio) | https://elevenlabs.io/docs/api-reference/text-to-speech#output-format |
| Voice library | https://elevenlabs.io/docs/voices/voice-library |
| Latency optimization | https://elevenlabs.io/docs/api-reference/text-to-speech#optimize-streaming-latency |

### OpenAI (LLM)

| Resource | URL |
|---|---|
| Chat Completions API | https://platform.openai.com/docs/api-reference/chat |
| Function / tool calling | https://platform.openai.com/docs/guides/function-calling |
| Streaming responses | https://platform.openai.com/docs/api-reference/chat/create#chat-create-stream |
| Structured outputs | https://platform.openai.com/docs/guides/structured-outputs |

### React Flow (Workflow Builder)

| Resource | URL |
|---|---|
| Getting started | https://reactflow.dev/learn |
| Custom nodes | https://reactflow.dev/learn/customization/custom-nodes |
| Custom edges | https://reactflow.dev/learn/customization/custom-edges |
| Examples gallery | https://reactflow.dev/examples |
| API reference | https://reactflow.dev/api-reference |
| npm package (`@xyflow/react`) | https://www.npmjs.com/package/@xyflow/react |

### Other

| Resource | URL |
|---|---|
| FastAPI docs | https://fastapi.tiangolo.com/ |
| FastAPI WebSockets | https://fastapi.tiangolo.com/advanced/websockets/ |
| SQLAlchemy 2.0 async | https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html |
| SQLModel (Pydantic + SQLAlchemy) | https://sqlmodel.tiangolo.com/ |
| Pydantic Settings | https://docs.pydantic.dev/latest/concepts/pydantic_settings/ |
| uvicorn (ASGI server) | https://www.uvicorn.org/ |
| websockets (Python library) | https://websockets.readthedocs.io/ |

---

## 8. Environment Variables (anticipated)

```env
# Twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=

# Deepgram
DEEPGRAM_API_KEY=

# ElevenLabs
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=

# OpenAI
OPENAI_API_KEY=

# Server
PORT=3000
PUBLIC_URL=         # ngrok or tunnel URL for Twilio webhooks during dev
DATABASE_URL=       # SQLite file path for PoC
```

---

## 9. Open Questions & Decisions

- [ ] **LLM streaming into TTS:** Should we stream LLM tokens sentence-by-sentence into ElevenLabs (lower latency, more complex) or wait for the full response (simpler, higher latency)? → Sentence-by-sentence is likely needed to hit the latency target.
- [ ] **Interruption handling:** When the caller speaks over the AI's response, do we immediately stop TTS playback and process the new input? → Yes for PoC, need to send a `clear` message on the Twilio WebSocket.
- [ ] **Filler phrases:** Pre-record "One moment please" / "Let me check on that" audio clips, or generate them dynamically? → Pre-record for lower latency.
- [ ] **Multi-tenancy:** Single business for PoC, but keep the schema tenant-aware from the start?
- [ ] **Testing without phone calls:** Build a WebSocket test harness (pytest + `httpx` async client) that simulates Twilio media events for local dev.
- [ ] **Deployment target:** Local dev with ngrok for PoC. Railway / Fly.io / Render for staging.

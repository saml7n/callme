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

### 4.1 Node Types (PoC scope — keep it minimal)

| Node Type | Purpose | Config |
|---|---|---|
| **Greeting** | Entry point; plays an opening message | `message` (text to speak), `voice_id` |
| **Collect Info** | Ask the caller a question and extract structured data (slot-filling) | `prompt`, `slots[]` (name, type, required), `retry_message` |
| **LLM Conversation** | Free-form conversation guided by a system prompt | `system_prompt`, `max_turns` |
| **API Call** | Hit an external HTTP endpoint with collected data | `url`, `method`, `headers`, `body_template`, `success_edge`, `failure_edge` |
| **Transfer** | Warm- or cold-transfer to a human phone number | `target_number`, `announcement_message` |
| **End Call** | Say a closing message and hang up | `message` |

### 4.2 Graph Format (JSON)

Workflows are stored as a JSON document with two top-level arrays — `nodes` and `edges`:

```json
{
  "id": "wf_001",
  "name": "General Reception",
  "nodes": [
    {
      "id": "node_1",
      "type": "greeting",
      "data": {
        "message": "Hello, thanks for calling Acme Corp. How can I help you today?"
      },
      "position": { "x": 100, "y": 100 }
    },
    {
      "id": "node_2",
      "type": "collect_info",
      "data": {
        "prompt": "Can I get your name and the reason for your call?",
        "slots": [
          { "name": "caller_name", "type": "string", "required": true },
          { "name": "reason", "type": "string", "required": true }
        ]
      },
      "position": { "x": 100, "y": 250 }
    }
  ],
  "edges": [
    {
      "id": "edge_1",
      "source": "node_1",
      "target": "node_2",
      "condition": null
    },
    {
      "id": "edge_2",
      "source": "node_2",
      "target": "node_3",
      "condition": { "type": "llm", "prompt": "The caller wants to schedule an appointment" }
    },
    {
      "id": "edge_3",
      "source": "node_2",
      "target": "node_4",
      "condition": { "type": "llm", "prompt": "The caller wants to speak to a person" }
    }
  ]
}
```

### 4.3 Edge Conditions

| Type | Evaluation | Use case |
|---|---|---|
| `null` / unconditional | Always follows this edge (only one allowed per source) | Greeting → next step |
| `expression` | Python expression evaluated against collected slot data | `slots["reason"] == "billing"` |
| `llm` | Natural-language condition evaluated by LLM against conversation context | "The caller wants to schedule an appointment" |

### 4.4 Workflow Engine (State Machine)

```python
class WorkflowEngine:
    workflow: Graph
    current_node: Node
    context: CallContext  # slots: dict, transcript: list, turn_count: int

    async def advance(self, event: Event) -> Action:
        # 1. Evaluate all outgoing edges from current_node
        # 2. Pick the first edge whose condition is satisfied
        # 3. Transition to the target node
        # 4. Execute the new node's entry action
        #    (speak greeting, ask question, fire API, etc.)
        ...
```

---

## 5. Implementation Phases

### Phase 1 — Skeleton & Voice Pipeline (Week 1-2)

- [ ] Project scaffolding: `server/` (Python + FastAPI) and `web/` (React) packages
- [ ] Twilio account setup: buy a number, configure webhook URL
- [ ] Incoming call webhook → respond with `<Connect><Stream>` TwiML
- [ ] WebSocket server: receive Twilio media events, decode μ-law audio
- [ ] Pipe audio to Deepgram streaming STT; log transcripts to console
- [ ] Pipe transcript to LLM (hardcoded system prompt); stream response
- [ ] Pipe LLM text to ElevenLabs TTS (μ-law); send audio back to Twilio
- [ ] **Milestone:** Make a phone call, have a free-form AI conversation

### Phase 2 — Workflow Engine (Week 3)

- [ ] Define workflow JSON schema
- [ ] Implement the state machine engine (node transitions, edge evaluation)
- [ ] Wire engine into the voice pipeline (engine controls the LLM system prompt per node)
- [ ] Implement slot extraction from LLM responses (structured output / tool calls)
- [ ] Implement `llm` edge condition evaluation
- [ ] Hardcode one test workflow in JSON; test end-to-end
- [ ] **Milestone:** Call follows a multi-step workflow (greeting → collect info → transfer/hang up)

### Phase 3 — Visual Workflow Builder (Week 4-5)

- [ ] React app scaffolding (Vite + TypeScript + Tailwind) in `web/`
- [ ] Integrate React Flow with custom node components for each node type
- [ ] Node config panels (click a node → edit its properties in a sidebar)
- [ ] Save/load workflows via REST API
- [ ] Publish workflow (mark as active for a given phone number)
- [ ] **Milestone:** Build a workflow in the browser, publish it, call the number, and have it execute

### Phase 4 — Polish & Observability (Week 6)

- [ ] Call logging: store full transcripts + metadata + workflow path taken
- [ ] Call log viewer in dashboard
- [ ] Filler-phrase strategy for high-latency responses
- [ ] Interruption handling (caller speaks while TTS is playing)
- [ ] Error handling & graceful degradation (STT/LLM/TTS failures)
- [ ] Basic auth on the dashboard
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
│   │   │   ├── engine.py        # State machine / graph walker
│   │   │   ├── nodes.py         # Node type handlers
│   │   │   └── conditions.py    # Edge condition evaluators
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

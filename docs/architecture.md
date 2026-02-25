# CallMe (Pronto) — Architecture

> **Status:** All 25 stories complete, deployed to Fly.io  
> **Last updated:** 25 February 2026  
> **Approach:** Hybrid — own orchestration + best-in-class external services

---

## 1. Vision

CallMe (branded “Pronto” in the UI) is an AI-powered phone receptionist that:

- **Answers inbound calls** on a real phone number via Twilio.
- **Transcribes caller speech in real time** using Deepgram streaming STT.
- **Routes conversations through configurable workflows** defined as directed graphs (nodes + edges).
- **Responds with natural voice** powered by ElevenLabs TTS.
- **Lets non-technical users design call flows** in a React Flow visual builder — no code required.
- **Persists workflows, call logs, and transcripts** for review and iteration.
- **Supports multi-user accounts** with per-user credentials, encrypted at rest.
- **Integrates with external services** (Google Calendar, webhooks) for real-world actions during calls.

---

## 2. System Architecture

```
┌─────────────┐       ┌──────────────────────────────────────────────────┐
│   Caller     │       │              CallMe Server (Python/FastAPI)      │
│  (phone)     │       │                                                  │
│              │  ←──→ │  ┌──────────┐   ┌──────────┐   ┌────────────┐  │
│              │       │  │ Twilio   │   │ Workflow │   │ Call       │  │
│              │       │  │ WebSocket│──→│ Engine   │──→│ Logger     │  │
│              │       │  │ Handler  │   │(Router + │   │(DB persist)│  │
│              │       │  │          │   │Responder)│   └────────────┘  │
│              │       │  └────┬─────┘   └────┬────┘                   │
│              │       │       │              │                         │
│              │       │  ┌────▼─────┐   ┌────▼────┐   ┌────────────┐  │
│              │       │  │ Deepgram │   │ LLM     │   │ EventBus   │  │
│              │       │  │ STT      │   │(GPT-4o) │   │(live call  │  │
│              │       │  │(streaming│   └────┬────┘   │ broadcast) │  │
│              │       │  │ WS)      │        │        └─────┬──────┘  │
│              │       │  └──────────┘   ┌────▼─────┐        │         │
│              │       │                 │ElevenLabs│   ┌────▼──────┐  │
│              │       │                 │ TTS      │   │ WebSocket │  │
│              │       │                 │(μ-law)   │   │ /ws/calls │  │
│              │       │                 └──────────┘   └───────────┘  │
│              │       └──────────────────────────────────────────────────┘
│              │
│              │       ┌──────────────────────────────────────────────────┐
│              │       │           Web Dashboard (React/Vite)             │
│   Admin      │  ←──→ │  ┌──────────────┐  ┌───────────────┐           │
│  (browser)   │       │  │ React Flow   │  │ Call Logs /   │           │
│              │       │  │ Workflow     │  │ Live Calls /  │           │
│              │       │  │ Builder      │  │ Transcripts   │           │
│              │       │  └──────────────┘  └───────────────┘           │
│              │       │  ┌──────────────┐  ┌───────────────┐           │
│              │       │  │ Setup Wizard │  │ Settings /    │           │
│              │       │  │              │  │ Integrations  │           │
│              │       │  └──────────────┘  └───────────────┘           │
│              │       └──────────────────────────────────────────────────┘
```

### Audio Pipeline (per call, real-time)

```
Caller speaks
    │
    ▼
Twilio captures μ-law 8kHz audio
    │
    ▼ (bidirectional WebSocket)
Server receives base64 audio chunks
    │
    ▼
Deepgram STT (streaming WebSocket, Nova-3)
    │  → interim transcripts (logged)
    │  → final transcript + speech_final event
    ▼
Workflow Engine evaluates current node
    │  → Router LLM: STAY or transition?
    │  → Responder LLM: generate reply from node instructions
    │  → May trigger action: end_call, transfer, integration
    ▼
ElevenLabs TTS converts text → μ-law audio (streaming, sentence-split)
    │
    ▼ (back over bidirectional WebSocket)
Twilio plays audio to caller

Interruption: if caller speaks during playback → Twilio “clear” message → stop TTS
Filler phrases: if LLM latency > 1500ms → play pre-cached audio (“One moment…”)
```

**Latency budget:**

| Stage | Target | Notes |
|---|---|---|
| Twilio ↔ Server | ~50ms | WebSocket, negligible |
| STT (endpointing + final) | ~200–400ms | Deepgram Nova-3, 300ms endpointing |
| LLM inference | ~200–400ms | Streaming; TTS starts before full response |
| TTS generation | ~150–250ms | ElevenLabs `optimize_streaming_latency=3` |
| **Total round-trip** | **~650–1150ms** | Filler phrases (“One moment…”) if > 800ms |

---

## 3. Technology Stack

| Layer | Technology | Why |
|---|---|---|
| **Telephony** | Twilio Voice + Media Streams | Bidirectional WebSocket streaming; global phone numbers |
| **STT** | Deepgram (Nova-3) | Native WebSocket streaming; lowest latency; μ-law support |
| **LLM** | OpenAI GPT-4o + GPT-4o-mini | Tool calling for actions; streaming; mini for routing |
| **TTS** | ElevenLabs (Flash v2.5) | Realistic voices; μ-law output; latency-optimised mode |
| **Server** | Python 3.12, FastAPI, uvicorn | Async-native; WebSocket support; OpenAPI docs |
| **Package manager** | uv | Fast Python package/venv management |
| **ORM** | SQLAlchemy 2.0 + SQLModel | Pydantic integration; async support |
| **Database** | SQLite (persistent volume on Fly) | Zero-config; sufficient for PoC; easy migration path to Postgres |
| **Web framework** | React 19, Vite, TypeScript | Fast dev iteration; HMR |
| **Workflow builder** | React Flow (`@xyflow/react`) | De facto standard for node-based visual editors |
| **UI components** | Tailwind CSS + shadcn/ui | Consistent design; accessible primitives |
| **Auth** | JWT (HS256, 7-day expiry) + bcrypt | Stateless auth; no session store needed |
| **Encryption** | Fernet (AES-128-CBC + HMAC-SHA256) | Symmetric encryption for credentials at rest |
| **Deployment** | Fly.io, Docker, nginx, supervisord | Single-command deploy; HTTPS; persistent volumes |

---

## 4. Workflow System

### 4.1 Node Types

| Node Type | Purpose | Config | Talks to caller? |
|---|---|---|---|
| **Conversation** | Talks to the caller following plain-English instructions. Maintains its own chat history. | `instructions`, `examples`, `max_iterations` | Yes |
| **Decision** | Pure routing — evaluates accumulated context and picks an outgoing edge. | `instruction` | No (silent) |
| **Action** | Performs a side effect: end call, transfer, or trigger an integration. | `action_type` + type-specific fields | Plays announcement only |

### 4.2 Dual LLM Roles

Every conversation turn uses two LLM calls:

1. **Router LLM** (GPT-4o-mini): Sees the current node, outgoing edge labels, and conversation history. Returns `STAY` or the edge ID to follow. One call evaluates all edges simultaneously.
2. **Responder LLM** (GPT-4o): Sees the node’s `instructions`, `examples`, accumulated summaries from previous nodes, and the current node’s chat history. Generates the spoken reply.

Decision nodes use only the Router. Action nodes use neither (they execute side effects directly).

### 4.3 Context Passing

Each conversation node maintains its **own `messages[]`** array. When transitioning:

1. The outgoing node’s conversation is summarised via LLM.
2. Key information is extracted (names, dates, intents).
3. The next node receives accumulated `NodeSummary` objects as context prefix.

This keeps per-node context focused and avoids bloat across long multi-node calls.

### 4.4 Edge Labels

Edges have a plain-English `label` describing when to follow them (e.g., “Caller wants to book an appointment”). The Router LLM interprets these against conversation context — no expression evaluator needed.

### 4.5 Integration Actions

Action nodes with `action_type: "integration"` invoke external services during calls:

- **Google Calendar** — check availability, book appointments (via OAuth refresh tokens)
- **Webhook** — POST/PUT to any URL with JSON payload (5s timeout)

Integration credentials and OAuth tokens are encrypted at rest in the database.

---

## 5. Server Architecture

### 5.1 Module Map

```
server/app/
├── main.py              # FastAPI app, CORS, startup lifecycle, health endpoint
├── config.py            # pydantic-settings: all env vars
├── auth.py              # JWT + API key auth, admin user, get_current_user()
├── credentials.py       # Runtime credential resolver (user DB → platform env)
├── crypto.py            # Fernet encryption for credentials at rest
├── events.py            # In-memory EventBus for live call broadcasting
├── health.py            # External service health probes (Twilio, DG, 11L, OAI)
├── pipeline.py          # CallPipeline: orchestrates one call end-to-end
├── public_url.py        # PUBLIC_URL auto-detection (env → Fly → ngrok → localhost)
├── seed.py              # Demo data seeder (admin user, sample workflow, fake calls)
│
├── api/                 # REST + WebSocket endpoints
│   ├── auth.py          #   Register, login, me, config-warnings
│   ├── workflows.py     #   Workflow CRUD, publish, phone assignment
│   ├── calls.py         #   Call logs (list, detail, live count)
│   ├── live.py          #   WebSocket live events, cold transfer
│   ├── settings.py      #   Per-user settings (encrypted), validate
│   ├── phone_numbers.py #   Phone number CRUD (E.164)
│   ├── integrations.py  #   Integration CRUD, OAuth flows, calendar picker
│   ├── templates.py     #   Starter workflow templates
│   ├── admin.py         #   Reset / seed endpoints
│   └── platform.py      #   Platform key availability status
│
├── db/
│   ├── models.py        #   SQLModel: User, Workflow, PhoneNumber, Integration,
│   │                    #     Call, CallEvent, Setting
│   ├── session.py       #   SQLite engine, init_db(), schema migrations
│   └── call_logger.py   #   Buffered call event writer
│
├── integrations/
│   ├── google_calendar.py  # Google Calendar v3: availability + booking
│   └── webhook.py          # Generic webhook caller
│
├── llm/
│   ├── base.py          #   BaseLLMClient protocol (swappable)
│   └── openai.py        #   OpenAI implementation (streaming, tools, structured)
│
├── stt/
│   └── deepgram.py      #   Deepgram streaming WebSocket STT client
│
├── tts/
│   └── elevenlabs.py    #   ElevenLabs HTTP TTS client (μ-law, streaming)
│
├── twilio/
│   ├── webhook.py       #   POST /twilio/incoming → TwiML (signature validated)
│   └── media_stream.py  #   WS /twilio/media-stream → CallPipeline
│
└── workflow/
    ├── schema.py        #   Pydantic models for workflow JSON validation
    └── engine.py        #   WorkflowEngine state machine (Router + Responder)
```

### 5.2 Call Flow (end-to-end)

```
1. Twilio receives inbound call to +44...
2. POST /twilio/incoming
   → Validate X-Twilio-Signature (auth token + reconstructed public URL)
   → Return TwiML: <Connect><Stream url="wss://.../twilio/media-stream?to=...&from=...">
3. Twilio opens bidirectional WebSocket to /twilio/media-stream
4. media_stream.py:
   a. Look up PhoneNumber by "to" → find active Workflow → resolve user_id
   b. Create Call record + CallLogger
   c. Register call with EventBus (live dashboard)
   d. Create CallPipeline with per-user credentials
   e. Pipeline runs: Deepgram STT → WorkflowEngine → ElevenLabs TTS → Twilio audio
5. On hang-up: CallLogger.finalise(), EventBus.unregister(), pipeline cleanup
```

### 5.3 Authentication & Authorisation

```
                  ┌─────────────────────────────────────────┐
                  │              Auth Flow                    │
                  │                                          │
                  │  POST /api/auth/register                 │
                  │    → Create User (email + bcrypt hash)   │
                  │    → Return JWT (7-day, HS256)           │
                  │                                          │
                  │  POST /api/auth/login                    │
                  │    → Verify password → Return JWT        │
                  │    → Or: legacy API key login             │
                  │                                          │
                  │  All /api/* endpoints:                    │
                  │    → Authorization: Bearer <jwt>          │
                  │    → get_current_user() dependency        │
                  │    → All data scoped by user_id           │
                  │                                          │
                  │  Exceptions (no auth required):           │
                  │    → GET /health                          │
                  │    → POST /twilio/incoming                │
                  │    → WS /twilio/media-stream              │
                  │    → GET /api/auth/check                  │
                  │    → GET /api/platform/status             │
                  └─────────────────────────────────────────┘
```

Admin user is auto-created on startup from `CALLME_API_KEY` (used as both the API key and initial admin password).

### 5.4 Credential Resolution

The `credentials.py` resolver provides a single source of truth for all API keys:

1. **User’s DB settings** — encrypted per-user settings stored in the `setting` table.
2. **Platform env vars** — if the user opted in via `use_platform_keys`, fall back to server-level env vars.

This allows both “bring your own keys” and “platform-managed keys” modes.

### 5.5 Database Schema

```
User
  id (UUID PK), email, password_hash, name, created_at

Workflow
  id (UUID PK), name, version, graph_json, is_active, phone_number, user_id → User

PhoneNumber
  id (UUID PK), number (E.164), label, workflow_id → Workflow, user_id → User

Integration
  id (UUID PK), type (google_calendar|webhook), name, config_encrypted, user_id → User

Call
  id (UUID PK), call_sid, from_number, to_number, workflow_id → Workflow,
  user_id → User, started_at, ended_at

CallEvent
  id (UUID PK), call_id → Call, timestamp, event_type (enum), data_json

Setting
  id (UUID PK), key, user_id → User, value_encrypted
  (unique constraint on user_id + key)
```

Event types: `transcript`, `llm_response`, `node_transition`, `summary`, `action`, `error`, `call_started`, `call_ended`, `transfer_started`.

### 5.6 EventBus (Live Calls)

An in-memory pub/sub system for real-time call monitoring:

- `register_call(call_id, metadata)` / `unregister_call(call_id)` — tracks active calls
- `emit(call_id, event)` — broadcast to all subscribers
- `subscribe(queue)` / `unsubscribe(queue)` — async queue-based consumers

The `WS /ws/calls/live` endpoint subscribes to the EventBus and streams events (transcript, node transition, call started/ended) to the live dashboard.

---

## 6. Web Architecture

### 6.1 Page Map

| Route | Page | Description |
|---|---|---|
| `/login` | Login | Email/password + legacy API key |
| `/register` | Register | Create account |
| `/setup` | Setup Wizard | 5-step onboarding: Welcome → API Keys → Phone Number → Workflow Template → Publish |
| `/workflows` | Workflow List | Dashboard with all workflows, status, phone assignment |
| `/workflows/:id` | Workflow Builder | React Flow drag-and-drop editor with config panel |
| `/workflows/:id/preview` | Workflow Preview | Read-only flow visualisation |
| `/calls` | Call List | Paginated call history with status, duration, masking |
| `/calls/:id` | Call Detail | Full transcript timeline, node breadcrumbs, key info badges |
| `/calls/live` | Live Calls | Real-time active calls via WebSocket, transfer button |
| `/settings/phone-numbers` | Phone Numbers | E.164 number management |
| `/settings/integrations` | Integrations | Google Calendar OAuth, webhook config, test |

### 6.2 Key Components

- **AppShell** — shared layout with nav bar, route outlet, `<LiveCallBanner />`
- **AuthGuard** — route protection, auto-redirect to `/setup` if not configured
- **LiveCallBanner** — persistent banner showing active call count via WebSocket
- **NodePalette** — draggable node types for the workflow builder
- **ConfigPanel** — right sidebar for editing selected node properties
- **Custom Nodes** — `ConversationNode` (blue), `DecisionNode` (yellow), `ActionNode` (red)

### 6.3 API Client

The `web/src/lib/api.ts` module provides a typed `fetch` wrapper with JWT auth. Namespaced methods for all resources (workflows, calls, settings, integrations, etc.). Auto-refreshes auth state on 401.

---

## 7. Deployment Architecture

### 7.1 Cloud (Fly.io)

```
Internet (HTTPS)
    │
    ▼
Fly.io edge proxy (TLS termination)
    │
    ▼ port 8080
nginx (in-container)
    ├── /                  → serve static React build from /usr/share/nginx/html
    ├── /api/*             → proxy_pass http://127.0.0.1:3000
    ├── /health            → proxy_pass http://127.0.0.1:3000
    ├── /twilio/*          → proxy_pass http://127.0.0.1:3000 (WebSocket upgrade)
    └── /ws/*              → proxy_pass http://127.0.0.1:3000 (WebSocket upgrade)
    │
    ▼ port 3000
uvicorn (FastAPI)
    └── SQLite DB on mounted volume (/app/data/callme.db)
```

Both nginx and uvicorn run under **supervisord** as a single Fly machine process.

Key config:
- **Region:** `lhr` (London)
- **Always-on:** `auto_stop_machines = false`, `min_machines_running = 1`
- **Volume:** 1GB at `/app/data` for SQLite persistence across deploys
- **Health check:** `GET /health` (fast liveness, no external calls)
- **Secrets:** all API keys via `fly secrets set` — never in the image
- **PUBLIC_URL:** auto-detected from `FLY_APP_NAME` env var

### 7.2 Local (Docker Compose)

```
docker-compose.yml
├── server (port 3000)    # FastAPI + SQLite volume
├── web (port 8080)       # nginx serving React build + proxy to server
└── tunnels (optional)    # ngrok sidecar (--profile tunnel)
```

### 7.3 Local Dev (no Docker)

- Server: `uv run uvicorn app.main:app --port 3000 --reload`
- Web: `npm run dev` (Vite on port 5173, proxies API to 3000)
- Tunnel: `ngrok http 3000` (for Twilio webhooks)

---

## 8. Project Structure

```
callme/
├── docs/
│   ├── architecture.md       ← this file
│   ├── stories.md            # All 25 user stories with acceptance criteria
│   ├── deployment.md         # Deployment guide (Docker, Fly.io, troubleshooting)
│   ├── development.md        # Development guide (setup, testing, extending)
│   └── security-audit.md     # Security review with remediation priorities
├── server/
│   ├── pyproject.toml        # Python deps (uv)
│   ├── app/                  # Application code (see §5.1)
│   ├── tests/                # 27 test files, 372+ tests
│   ├── schemas/
│   │   ├── examples/         # Sample workflow JSONs
│   │   └── templates/        # Starter templates for setup wizard
│   └── scripts/              # QA scripts (qa_deepgram, qa_llm, etc.)
├── web/
│   ├── package.json          # Node deps
│   ├── vite.config.ts        # Vite config with API proxy
│   ├── src/
│   │   ├── pages/            # Route pages
│   │   ├── components/       # Reusable components + shadcn primitives
│   │   ├── hooks/            # Custom hooks (useLiveCallCount)
│   │   ├── lib/              # API client, types, auth, utils
│   │   └── test/             # 12 test files, Vitest + RTL
│   └── public/               # Static assets
├── fly/
│   ├── nginx.conf            # nginx config for Fly container
│   └── supervisord.conf      # Process manager config
├── scripts/
│   └── fly-setup.sh          # First-time Fly.io provisioning
├── Dockerfile.fly            # Multi-stage build for Fly deployment
├── fly.toml                  # Fly.io app config
├── docker-compose.yml        # Local Docker quickstart
├── Makefile                  # dev, test, deploy, seed, reset targets
├── .env.example              # Environment variable template
├── copilot-instructions.md   # AI coding assistant context
└── README.md                 # Quickstart guide
```

---

## 9. Environment Variables

```env
# Auth & encryption
CALLME_API_KEY=             # Admin password + legacy API key auth
CALLME_ENCRYPTION_KEY=      # Auto-generated Fernet key for credential encryption

# Twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=          # Used for REST API auth + webhook signature validation
TWILIO_API_KEY_SID=         # Optional: API key pair (alternative to auth token)
TWILIO_API_KEY_SECRET=
TWILIO_PHONE_NUMBER=

# Deepgram
DEEPGRAM_API_KEY=

# ElevenLabs
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=        # Default: 21m00Tcm4TlvDq8ikWAM (Rachel)

# OpenAI
OPENAI_API_KEY=

# Google OAuth (for Calendar integration)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# Server
PORT=3000
PUBLIC_URL=                 # Auto-detected on Fly.io; set manually for ngrok
DATABASE_URL=               # Default: sqlite:///./callme.db
CALLME_FALLBACK_NUMBER=     # Transfer-to number when errors occur

# Demo
SEED_DEMO=true              # Auto-seed demo data on startup (Fly default)
```

---

## 10. Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Single container on Fly | supervisord (nginx + uvicorn) | Simplest; Fly bills per machine; keeps latency minimal |
| SQLite not Postgres | SQLite on persistent volume | Zero-config; sufficient for PoC; easy to migrate later |
| Dual LLM (Router + Responder) | GPT-4o-mini routes, GPT-4o responds | Fast routing (~100ms) + quality responses; keeps cost down |
| JWT not sessions | HS256, 7-day expiry | Stateless; no session store; fits single-server model |
| Fernet encryption | AES-128 with HMAC | Standard; Python built-in; sufficient for credentials at rest |
| Per-user credential isolation | DB settings with Fernet | Multi-tenant ready; users can’t see each other’s keys |
| Sentence-split TTS streaming | Split on `.!?` → parallel TTS | Starts playback before LLM finishes; halves perceived latency |
| Pre-cached filler phrases | 5 clips warmed at startup | Eliminates TTS latency for “One moment…” when LLM is slow |
| Event bus (in-process) | async queues, no Redis | Simple; single-machine deployment; no external dependency |
| Edge labels over typed conditions | Plain English, Router LLM interprets | More flexible; no expression parser; users think in natural language |

---

## 11. External Service Reference

### Twilio
- [Media Streams (bidirectional WebSocket)](https://www.twilio.com/docs/voice/media-streams/bidirectional-media-streams)
- [TwiML `<Connect><Stream>`](https://www.twilio.com/docs/voice/twiml/connect)
- [Request validation](https://www.twilio.com/docs/usage/security#validating-requests)

### Deepgram
- [Streaming STT (WebSocket)](https://developers.deepgram.com/docs/getting-started-with-live-streaming-audio)
- [Nova-3 model](https://developers.deepgram.com/docs/models-overview)
- [Endpointing](https://developers.deepgram.com/docs/endpointing)

### ElevenLabs
- [Text-to-Speech API](https://elevenlabs.io/docs/api-reference/text-to-speech)
- [Output formats (μ-law)](https://elevenlabs.io/docs/api-reference/text-to-speech#output-format)
- [Latency optimisation](https://elevenlabs.io/docs/api-reference/text-to-speech#optimize-streaming-latency)

### OpenAI
- [Chat Completions](https://platform.openai.com/docs/api-reference/chat)
- [Tool/function calling](https://platform.openai.com/docs/guides/function-calling)
- [Structured outputs](https://platform.openai.com/docs/guides/structured-outputs)

### React Flow
- [Custom nodes](https://reactflow.dev/learn/customization/custom-nodes)
- [API reference](https://reactflow.dev/api-reference)

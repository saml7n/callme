# User Stories: CallMe — AI Receptionist PoC

Stories are ordered by dependency. Each one produces a concrete, testable output that the next story builds on.

**Rules:**
- No work begins on a story until every item in "Blocked until answered" is answered and recorded in this file.
- One commit per story.
- Each story must pass **both** its unit tests and QA verification before moving to the next.
- **Unit tests** cover isolated logic with mocked dependencies.
- **QA tests** are real runs of the system (phone calls, browser interactions, live API round-trips) that prove the feature works end-to-end. Where the QA involves a web UI, use Playwright for automated verification. Where it involves a phone call, document the manual test script and expected outcome.

**Dependency chain:**
```
Story 0: Decisions (no code)
  → Story 1: Project scaffolding (server + web)
    → Story 2: Twilio inbound call handler (WebSocket plumbing)
      → Story 3: Deepgram STT client (standalone, tested in isolation)
      → Story 4: LLM client (standalone, tested in isolation)
      → Story 5: ElevenLabs TTS client (standalone, tested in isolation)
        → Story 6: End-to-end voice pipeline (first real phone conversation)
          → Story 7: Workflow schema & engine (state machine, no UI)
            → Story 8: Voice pipeline + workflow integration (calls follow workflows)
              → Story 9: REST API for workflows & call logs
                → Story 10: Visual workflow builder (React Flow)
                  → Story 11: Call log viewer
                    → Story 12: Polish — interruptions, filler phrases, error handling, auth
```

---

## Story 0 — Decide the operating model

As a **project lead**, I want **clear decisions on accounts, tools, and constraints documented up front**, so that **no story is blocked by an unanswered question once coding starts**.

### Acceptance criteria
- [x] The following decisions are recorded in this file (below):
  - Twilio account type (trial vs paid) and phone number region.
  - Deepgram plan tier and model choice (Nova-3 vs Flux).
  - ElevenLabs plan tier and default voice ID.
  - LLM provider and model (GPT-4o, Claude, etc.) and whether we need function/tool calling.
  - Dev tunnelling approach for Twilio webhooks (ngrok, Cloudflare Tunnel, etc.).
  - Python version and dependency management (pip, poetry, uv).
  - React tooling (Vite, package manager).
  - Database choice confirmed (SQLite for PoC).
- [x] All API accounts are created and keys are available (not committed to repo).
- [x] A `.env.example` file documents every required environment variable.

### Unit tests
- None (no code in this story).

### QA verification
- Read through the recorded answers below. If any are blank, the story is not done.
- Confirm each API key works by making a trivial authenticated request (e.g. `curl` to list Twilio numbers, Deepgram usage, ElevenLabs voices).

### Blocked until answered
1. Twilio account: trial or paid? Which country for the phone number?
2. Deepgram model preference: Nova-3 (general) or Flux (optimised for voice agents)?
3. ElevenLabs default voice: pick from voice library or clone a custom voice?
4. LLM: GPT-4o (OpenAI) or Claude (Anthropic)? Both? Tool calling required?
5. Python dependency manager: pip + requirements.txt, poetry, or uv?
6. Tunnelling: ngrok (free tier) or Cloudflare Tunnel?

**Recorded answers:**
- Twilio account: API Key auth (`SK...` + secret) with Account SID `AC339d...`. No phone number yet — will purchase in Story 2. Twilio credentials use API Key SID + Secret (not Account SID + Auth Token) for auth.
- Deepgram model: Nova-3 (general-purpose, well-documented, reliable for PoC).
- ElevenLabs voice: Rachel (`21m00Tcm4TlvDq8ikWAM`) — professional, clear, female. Using library voice (no custom clone).
- LLM provider: OpenAI GPT-4o with tool/function calling enabled. Key verified, model available.
- Python tooling: uv for dependency management. Python 3.12+.
- Tunnel: ngrok (free tier) for dev.
- React tooling: Vite + npm.
- Database: SQLite for PoC (confirmed).

---

## Story 1 — Project scaffolding

As a **developer**, I want **a working project skeleton with linting, testing, and dev scripts configured**, so that **every subsequent story starts from a runnable baseline, not a blank folder**.

### Acceptance criteria
- [ ] `server/` directory exists with:
  - `pyproject.toml` (or `requirements.txt`) listing core dependencies: `fastapi`, `uvicorn`, `websockets`, `httpx`, `pydantic`, `pydantic-settings`, `sqlmodel`, `pytest`, `pytest-asyncio`.
  - `app/main.py` — a FastAPI app that starts and serves a health-check endpoint (`GET /health` → `{"status": "ok"}`).
  - `app/config.py` — reads all env vars via `pydantic-settings` (`BaseSettings`).
  - `tests/` directory with a passing smoke test for the health endpoint.
- [ ] `web/` directory exists with:
  - Vite + React + TypeScript + Tailwind scaffolded (e.g. via `npm create vite@latest`).
  - A placeholder `App.tsx` that renders "CallMe — AI Receptionist".
  - Dev server starts with `npm run dev`.
- [ ] `.env.example` at repo root lists all anticipated env vars (from Story 0).
- [ ] `.gitignore` covers Python (`__pycache__`, `.venv`, etc.) and Node (`node_modules`, `dist`, etc.).
- [ ] `README.md` at repo root has setup instructions for both `server/` and `web/`.

### Unit tests
- `pytest server/tests/` passes — health endpoint returns 200 with `{"status": "ok"}`.

### QA verification
1. Clone the repo fresh, follow README instructions, start the server → `curl localhost:3000/health` returns OK.
2. Start the web dev server → browser shows the placeholder page.

### Blocked until answered
- None (depends only on Story 0 answers).

---

## Story 2 — Twilio inbound call handler

As a **developer**, I want **the server to answer an inbound Twilio call and establish a bidirectional WebSocket media stream**, so that **raw audio flows between the caller and our server in real time**.

### Acceptance criteria
- [ ] A FastAPI route exists at `POST /twilio/incoming` that returns TwiML:
  ```xml
  <Response>
    <Connect>
      <Stream url="wss://{PUBLIC_URL}/twilio/media-stream" />
    </Connect>
  </Response>
  ```
- [ ] A FastAPI WebSocket endpoint exists at `/twilio/media-stream` that:
  - Accepts the Twilio connection.
  - Parses the `connected`, `start`, `media`, and `stop` events from Twilio's JSON protocol.
  - Logs the `streamSid`, `callSid`, and audio codec from the `start` event.
  - Decodes base64 μ-law audio payloads from `media` events.
  - Can send base64-encoded μ-law audio back to Twilio via the `media` message format.
  - Handles `stop` and WebSocket close gracefully.
- [ ] The Twilio phone number's webhook is configured to point at `{PUBLIC_URL}/twilio/incoming` (via console or API).

### Unit tests
- Mock WebSocket tests:
  - Receives a `start` event → extracts `streamSid` and codec.
  - Receives a `media` event → decodes base64 payload to bytes.
  - Sends an outbound `media` message → correctly formatted JSON with base64 audio.
  - Receives a `stop` event → cleans up without error.
- TwiML endpoint test: `POST /twilio/incoming` returns valid XML with `<Connect><Stream>`.

### QA verification
1. Call the Twilio number from a real phone.
2. Observe server logs showing: connection established, `streamSid` logged, audio chunks arriving.
3. The call stays connected for at least 10 seconds without dropping.
4. Hang up → server logs show graceful `stop` / disconnect.

### Blocked until answered
1. Confirm the Twilio phone number is purchased and the webhook URL is set.
2. Confirm the tunnel (ngrok / Cloudflare) is working and the public URL is stable for dev.

**Recorded answers:**
- Twilio number configured: _unanswered_
- Tunnel confirmed: _unanswered_

---

## Story 3 — Deepgram STT client (standalone)

As a **developer**, I want **a tested, reusable Deepgram streaming client**, so that **I can feed it raw audio and receive real-time transcripts without coupling it to the Twilio handler**.

### Acceptance criteria
- [ ] A Python module exists at `app/stt/deepgram.py` with a class `DeepgramSTTClient`:
  - `async connect()` — opens a WebSocket to Deepgram's streaming endpoint with config: `model`, `encoding=mulaw`, `sample_rate=8000`, `channels=1`, `punctuate=true`, `endpointing` (configurable ms).
  - `async send_audio(chunk: bytes)` — sends raw audio bytes to Deepgram.
  - `async receive_transcript()` — async generator yielding transcript events with: `transcript` (str), `is_final` (bool), `speech_final` (bool), `confidence` (float).
  - `async close()` — sends close signal and disconnects.
- [ ] The client reads `DEEPGRAM_API_KEY` from config.
- [ ] Connection errors, auth failures, and unexpected disconnects are handled with clear exceptions.

### Unit tests (mocked WebSocket)
- Successful connection → receives a transcript event → yields correct fields.
- `speech_final=True` event correctly signals end of utterance.
- Auth failure (401) raises a descriptive exception.
- Unexpected disconnect mid-stream raises a descriptive exception.
- `send_audio` after `close()` raises an exception (not a silent failure).

### QA verification
1. Write a short test script that connects to Deepgram, sends a pre-recorded μ-law audio file (8kHz, mono), and prints transcripts to the console.
2. Run it → readable transcript appears with `is_final` and `speech_final` markers.

### Blocked until answered
1. Deepgram model choice (from Story 0).
2. Endpointing threshold — default 300ms or tune differently?

**Recorded answers:**
- Model: _unanswered_
- Endpointing: _unanswered_

---

## Story 4 — LLM client (standalone)

As a **developer**, I want **a tested, swappable LLM client with streaming support and tool calling**, so that **I can generate conversational responses and structured data extraction without coupling to the voice pipeline**.

### Acceptance criteria
- [ ] A Python module exists at `app/llm/openai.py` with a class `LLMClient`:
  - `async chat_stream(messages: list[dict], tools: list[dict] | None) -> AsyncGenerator[str, None]` — streams text chunks from the LLM.
  - `async chat(messages: list[dict], tools: list[dict] | None) -> str` — returns the full response (non-streaming, for simpler use cases).
  - `async chat_structured(messages: list[dict], schema: dict) -> dict` — returns structured JSON output validated against a schema (for slot extraction).
  - Supports system messages, tool definitions, and tool-call responses.
- [ ] The client reads `OPENAI_API_KEY` from config. Model name is configurable (default: `gpt-4o`).
- [ ] An abstract base class or protocol `BaseLLMClient` exists so Claude or another provider can be swapped in later.
- [ ] Rate limit (429) and server error (5xx) responses trigger retries with backoff (max 3 attempts).

### Unit tests (mocked HTTP)
- Streaming: yields chunks in order, concatenation matches expected full response.
- Tool calling: returns a tool-call response with correct function name and arguments.
- Structured output: returns valid JSON matching the provided schema.
- Auth failure (401) raises a descriptive exception.
- Rate limit (429) triggers retry, succeeds on second attempt.
- Timeout raises after max retries.

### QA verification
1. Run a test script that sends a prompt ("You are a receptionist. A caller says: Hi, I'd like to book an appointment.") with streaming and prints each chunk as it arrives.
2. Run a test script that extracts structured data (caller name + reason) from a transcript using `chat_structured`.
3. Both produce coherent, correct output.

### Blocked until answered
1. LLM provider confirmed (from Story 0).
2. Are there any content/safety guardrails to set in the system prompt for the PoC?

**Recorded answers:**
- LLM provider: _unanswered_
- Guardrails: _unanswered_

---

## Story 5 — ElevenLabs TTS client (standalone)

As a **developer**, I want **a tested ElevenLabs TTS client that outputs μ-law audio suitable for Twilio**, so that **I can convert text to speech independently of the voice pipeline**.

### Acceptance criteria
- [ ] A Python module exists at `app/tts/elevenlabs.py` with a class `ElevenLabsTTSClient`:
  - `async synthesize(text: str) -> bytes` — returns complete μ-law audio bytes for the given text.
  - `async synthesize_stream(text: str) -> AsyncGenerator[bytes, None]` — streams μ-law audio chunks as they become available (for lower latency).
  - Configurable: `voice_id`, `model_id`, `output_format` (default: `ulaw_8000` for Twilio compatibility), `optimize_streaming_latency` (default: `3`).
- [ ] The client reads `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` from config.
- [ ] Previous/next request stitching (`previous_request_ids`) is supported for multi-sentence continuity.
- [ ] Auth failure and rate-limit errors are handled with clear exceptions.

### Unit tests (mocked HTTP)
- `synthesize` returns audio bytes for a given text input.
- `synthesize_stream` yields multiple chunks.
- Correct output format (`ulaw_8000`) is passed in the API request.
- Latency optimisation parameter is included in the request.
- Auth failure (401) raises a descriptive exception.
- Empty text input is handled gracefully (returns empty bytes or raises).

### QA verification
1. Run a test script that synthesizes "Hello, thanks for calling. How can I help you today?" with the chosen voice.
2. Save the output to a `.raw` file and play it back (e.g. `ffplay -f mulaw -ar 8000 -ac 1 output.raw`) — the audio is clear and natural-sounding.
3. Run the streaming variant and confirm chunks arrive incrementally (log timestamps per chunk).

### Blocked until answered
1. ElevenLabs voice choice (from Story 0).
2. Latency optimisation level — `3` (high optimisation, slight quality trade-off) or `2` (balanced)?

**Recorded answers:**
- Voice ID: _unanswered_
- Latency level: _unanswered_

---

## Story 6 — End-to-end voice pipeline (first real phone conversation)

As a **demo presenter**, I want to **call the Twilio number and have a free-form AI conversation**, so that **the full audio pipeline is proven before we add workflow logic**.

This is the first story where all audio components come together. No workflow engine yet — the LLM uses a single hardcoded system prompt.

### Acceptance criteria
- [ ] A `CallPipeline` class (or equivalent) in `app/pipeline.py` orchestrates a single call:
  1. Receives audio from the Twilio WebSocket handler (Story 2).
  2. Forwards audio chunks to `DeepgramSTTClient` (Story 3).
  3. On `speech_final`, sends the transcript + conversation history to `LLMClient.chat_stream()` (Story 4).
  4. As LLM text chunks arrive, accumulates them into sentences (split on `.`, `!`, `?`).
  5. Sends each sentence to `ElevenLabsTTSClient.synthesize_stream()` (Story 5).
  6. Forwards TTS audio chunks back to the Twilio WebSocket as base64 `media` messages.
- [ ] The hardcoded system prompt is: *"You are a friendly AI receptionist for a business. Greet the caller, ask how you can help, and have a natural conversation. Keep responses concise — 1-2 sentences at a time."*
- [ ] On call start, the system speaks a greeting without waiting for the caller (proactive first message).
- [ ] Conversation history (messages array) is maintained for the duration of the call.
- [ ] The pipeline handles Twilio `stop` event and caller hang-up gracefully (closes STT and any in-flight requests).

### Unit tests
- Pipeline receives a `speech_final` transcript → calls LLM with correct message history.
- LLM response is split into sentences → each sentence triggers a TTS call.
- TTS audio chunks are formatted as Twilio `media` messages with base64 encoding.
- Caller hang-up (WebSocket close) triggers cleanup of STT connection.
- Conversation history accumulates correctly across multiple turns.

### QA verification
1. **Call the Twilio number from a real phone.**
2. Hear the AI greeting within ~2 seconds of the call connecting.
3. Say "Hi, I'd like to book an appointment" → hear a coherent, relevant response within ~1-2 seconds.
4. Have a 3-4 turn conversation → responses remain contextually aware (remembers what you said earlier).
5. Hang up → server logs show clean shutdown, no errors.
6. Repeat the call → new conversation, no state leakage from the previous call.

### Blocked until answered
1. Confirm all four services (Twilio, Deepgram, ElevenLabs, OpenAI) are working individually (Stories 2-5 QA passed).
2. Sentence splitting strategy — split on punctuation, or use a smarter chunking approach?

**Recorded answers:**
- Services confirmed: _unanswered_
- Sentence splitting: _unanswered_

---

## Story 7 — Workflow JSON schema & engine

As a **developer**, I want **a workflow engine that reads a JSON graph and controls conversation flow as a state machine**, so that **calls follow structured, configurable paths instead of a single hardcoded prompt**.

This story produces the engine and schema only — no UI, no integration with the voice pipeline yet.

### Acceptance criteria
- [ ] A JSON schema file exists at `server/schemas/workflow.schema.json` defining the workflow format with:
  - `id`, `name`, `version` (metadata).
  - `nodes[]` — each with `id`, `type` (enum: `greeting`, `collect_info`, `llm_conversation`, `api_call`, `transfer`, `end_call`), `data` (type-specific config), `position` (for the visual builder later).
  - `edges[]` — each with `id`, `source`, `target`, `condition` (null | `{ type: "expression", expr: "..." }` | `{ type: "llm", prompt: "..." }`).
  - `entry_node_id` — the starting node.
- [ ] A validation function at `app/workflow/validation.py` validates a workflow dict against the schema.
- [ ] A sample workflow JSON exists at `server/schemas/examples/reception.json` with 5+ nodes covering a realistic reception scenario (greeting → collect info → branch on reason → transfer or end).
- [ ] A `WorkflowEngine` class exists at `app/workflow/engine.py`:
  - `__init__(workflow: dict, llm_client: LLMClient)` — loads and validates the graph.
  - `current_node` property — returns the active node.
  - `context` property — returns `{ slots: dict, transcript: list, turn_count: int }`.
  - `async start() -> NodeAction` — enters the entry node and returns its action (e.g. speak the greeting).
  - `async handle_input(transcript: str) -> NodeAction` — processes caller input for the current node, evaluates outgoing edges, transitions if a condition matches, and returns the next action.
  - `NodeAction` is a dataclass: `{ type: "speak" | "collect" | "api_call" | "transfer" | "end", data: dict }`.
- [ ] Node handlers exist at `app/workflow/nodes.py`:
  - `GreetingHandler` — returns a `speak` action with the configured message.
  - `CollectInfoHandler` — uses the LLM to extract slots from the transcript; returns `collect` action (re-ask if required slots are missing).
  - `LLMConversationHandler` — passes the transcript to the LLM with the node's system prompt; returns `speak` action.
  - `ApiCallHandler` — makes an HTTP request with slot data templated into the URL/body; returns `speak` with the result or follows success/failure edges.
  - `TransferHandler` — returns a `transfer` action with the target number.
  - `EndCallHandler` — returns an `end` action with the closing message.
- [ ] Edge condition evaluators exist at `app/workflow/conditions.py`:
  - `evaluate_expression(expr: str, context: dict) -> bool` — safely evaluates a Python expression against slot data.
  - `async evaluate_llm(prompt: str, context: dict, llm_client: LLMClient) -> bool` — asks the LLM a yes/no question about the conversation context.

### Unit tests
- **Schema validation:** valid sample workflow passes; missing required fields fail; invalid node type fails.
- **Engine start:** enters entry node, returns correct greeting action.
- **Engine handle_input:** transcript triggers edge evaluation → transitions to correct next node.
- **CollectInfoHandler:** extracts slots from transcript; re-asks when required slot is missing.
- **Expression evaluator:** `slots["reason"] == "billing"` returns True when slot matches; False otherwise; malicious expressions are blocked.
- **LLM condition evaluator:** mocked LLM returns "yes" → True; "no" → False.
- **Edge with null condition:** always transitions (unconditional).
- **Multiple outgoing edges:** first matching condition wins.
- **No matching edge:** engine stays on current node (doesn't crash).
- **Dead-end node (no outgoing edges):** engine signals conversation complete.

### QA verification
1. Load the sample `reception.json` workflow into the engine.
2. Write an integration test script that simulates a caller interaction (no audio — just text in, actions out):
   - Start → engine returns greeting.
   - Input "I'd like to book an appointment" → engine transitions to collect_info node.
   - Input "My name is Alex, I need a cleaning on Friday" → engine extracts slots (`caller_name: "Alex"`, `service: "cleaning"`, `day: "Friday"`).
   - Engine transitions to the correct next node based on edge conditions.
3. Run the script → all transitions match expected behavior.

### Blocked until answered
1. Should expression conditions use a sandboxed evaluator or is `ast.literal_eval`-level safety sufficient for the PoC?
2. For the LLM edge evaluator, should we use a cheap/fast model (e.g. GPT-4o-mini) to save cost and latency?

**Recorded answers:**
- Expression safety: _unanswered_
- LLM evaluator model: _unanswered_

---

## Story 8 — Voice pipeline + workflow integration

As a **caller**, I want **the AI receptionist to follow a structured workflow** (greeting → questions → routing), so that **my call is handled consistently regardless of which AI model is having a good day**.

This story wires the `WorkflowEngine` (Story 7) into the `CallPipeline` (Story 6).

### Acceptance criteria
- [ ] `CallPipeline` accepts an optional `workflow_id` parameter. If provided, it loads the workflow from the database (or JSON file for now) and creates a `WorkflowEngine`.
- [ ] The pipeline's behaviour changes based on `NodeAction` types:
  - `speak` → send text through TTS and play to caller.
  - `collect` → send the prompt through TTS, then wait for caller input and re-invoke `engine.handle_input()`.
  - `api_call` → execute the HTTP request, feed the result back to the engine.
  - `transfer` → send a Twilio `<Dial>` or SIP transfer to the target number.
  - `end` → speak the closing message, then close the WebSocket (Twilio hangs up).
- [ ] The hardcoded system prompt from Story 6 is replaced by per-node prompts from the workflow.
- [ ] If no workflow is configured, the pipeline falls back to the hardcoded free-form prompt (Story 6 behaviour).
- [ ] Transfer action generates the correct Twilio REST API call (or TwiML update) to redirect the call.

### Unit tests
- Pipeline with a workflow: start → greeting action → TTS called with greeting text.
- Pipeline with a collect node: receives transcript → passes to engine → engine extracts slots → re-asks if incomplete.
- Pipeline with an end node: speaks closing message → closes WebSocket.
- Pipeline with a transfer node: correct Twilio API call is made with target number.
- Pipeline without a workflow: falls back to hardcoded prompt (Story 6 behaviour preserved).

### QA verification
1. Load the sample `reception.json` workflow and configure the phone number to use it.
2. **Call the Twilio number from a real phone.**
3. Hear the greeting defined in the workflow's greeting node (not the generic Story 6 greeting).
4. Say "I'd like to speak to someone in billing" → the call follows the correct branch (based on LLM edge condition).
5. If the workflow has a transfer node, confirm the call is transferred (or hear the transfer announcement).
6. If the workflow has an end node, hear the closing message and the call disconnects.
7. Repeat with a different caller intent to exercise a different branch.

### Blocked until answered
1. Transfer implementation: Twilio REST API to update the live call, or close WebSocket and fall back to TwiML? (REST API update is cleaner.)
2. Should the pipeline stream interim transcripts to the engine (for faster response) or wait for `speech_final`?

**Recorded answers:**
- Transfer method: _unanswered_
- Interim vs final transcripts: _unanswered_

---

## Story 9 — REST API for workflows & call logs

As a **dashboard developer**, I want **CRUD endpoints for workflows and read endpoints for call logs**, so that **the React frontend has a backend to talk to**.

### Acceptance criteria
- [ ] Database schema (SQLModel) with tables:
  - `workflows` — `id`, `name`, `version`, `graph_json` (the full node/edge JSON), `is_active` (bool), `phone_number` (nullable — which Twilio number uses this workflow), `created_at`, `updated_at`.
  - `calls` — `id`, `call_sid`, `from_number`, `to_number`, `workflow_id` (FK, nullable), `started_at`, `ended_at`, `duration_seconds`.
  - `call_events` — `id`, `call_id` (FK), `timestamp`, `event_type` (enum: `transcript`, `llm_response`, `node_transition`, `slot_extracted`, `transfer`, `error`), `data_json`.
- [ ] Alembic (or equivalent) migration creates the tables.
- [ ] REST API endpoints:
  - `GET /api/workflows` — list all workflows (summary: id, name, is_active, updated_at).
  - `GET /api/workflows/{id}` — full workflow including `graph_json`.
  - `POST /api/workflows` — create a new workflow.
  - `PUT /api/workflows/{id}` — update a workflow (name, graph_json).
  - `POST /api/workflows/{id}/publish` — set `is_active=True` and optionally assign a phone number (deactivates the previous active workflow for that number).
  - `DELETE /api/workflows/{id}` — soft-delete or hard-delete.
  - `GET /api/calls` — list recent calls (summary: id, from, to, workflow_name, started_at, duration).
  - `GET /api/calls/{id}` — full call detail including all events (transcript, node transitions, etc.).
- [ ] The voice pipeline (Story 8) logs events to the `call_events` table in real time during a call.
- [ ] Input validation on all endpoints (Pydantic models).

### Unit tests
- Workflow CRUD: create → read → update → read (verify changes) → delete → read (404 or gone).
- Publish: publishing workflow A deactivates the previously active workflow for the same phone number.
- Call log: create a call record with events → list calls → get call detail with events.
- Validation: creating a workflow with invalid `graph_json` (fails schema validation) returns 422.
- Validation: required fields missing returns 422.

### QA verification
1. Start the server and use `curl` or Postman to:
   - Create a workflow → 201 with ID.
   - Get the workflow → matches what was created.
   - Update the workflow → 200, changes persisted.
   - Publish the workflow → `is_active` is True.
   - List workflows → published workflow appears.
2. Make a phone call (Story 8) → after the call, `GET /api/calls` shows the call → `GET /api/calls/{id}` shows the full transcript and node transitions.

### Blocked until answered
1. Soft-delete or hard-delete for workflows?
2. Should call events be stored in a single JSONB column per call, or as individual rows in `call_events`?

**Recorded answers:**
- Delete strategy: _unanswered_
- Event storage: _unanswered_

---

## Story 10 — Visual workflow builder (React Flow)

As an **admin**, I want **a drag-and-drop visual editor for designing call workflows**, so that **I can create and modify call flows without writing JSON by hand**.

### Acceptance criteria
- [ ] A page exists at `/workflows/new` (and `/workflows/{id}/edit`) in the React app.
- [ ] The page renders a React Flow (`@xyflow/react`) canvas with:
  - A left sidebar / palette listing available node types (Greeting, Collect Info, LLM Conversation, API Call, Transfer, End Call) that can be dragged onto the canvas.
  - Custom node components for each type — visually distinct (icon + colour per type), showing a summary of the node's config.
  - Edges drawn between node handles; edges with conditions show a label on the edge.
  - Minimap, zoom controls, and background grid.
- [ ] Clicking a node opens a right sidebar config panel with editable fields:
  - Greeting: message text, voice selector.
  - Collect Info: prompt text, slot definitions (name, type, required toggle).
  - LLM Conversation: system prompt, max turns.
  - API Call: URL, method, headers, body template, success/failure edge labels.
  - Transfer: target phone number, announcement message.
  - End Call: closing message.
- [ ] "Save" button → `PUT /api/workflows/{id}` with the serialised React Flow graph (nodes + edges + positions).
- [ ] "Publish" button → `POST /api/workflows/{id}/publish`.
- [ ] Loading an existing workflow (`GET /api/workflows/{id}`) populates the canvas with saved nodes, edges, and positions.
- [ ] Deleting a node removes it and its connected edges.
- [ ] Basic validation: entry node required, no orphan nodes (warning), no duplicate node IDs.

### Unit tests
- React component tests (Vitest + React Testing Library):
  - Canvas renders without crashing.
  - Adding a node to the canvas → node appears in the React Flow state.
  - Clicking a node → config panel opens with correct fields for that node type.
  - Saving → correct payload sent to API (mock `fetch`).
  - Loading a workflow → nodes and edges rendered in correct positions.
  - Deleting a node → node and connected edges removed.

### QA verification (Playwright)
1. **Navigate to `/workflows/new`** → canvas loads with empty grid and node palette.
2. **Drag a Greeting node** onto the canvas → node appears.
3. **Click the Greeting node** → config panel opens on the right.
4. **Type a greeting message** ("Welcome to Acme Corp!") in the config panel → node summary updates on the canvas.
5. **Drag a Collect Info node** onto the canvas → second node appears.
6. **Draw an edge** from Greeting → Collect Info by dragging from the source handle to the target handle.
7. **Click Save** → network request sent to API with correct payload (intercept and assert in Playwright).
8. **Reload the page** (`/workflows/{id}/edit`) → the saved nodes, edges, and config are restored.
9. **Click Publish** → confirmation shown, workflow marked as active.
10. **Delete the Collect Info node** → node and its edge are removed.

### Blocked until answered
1. UI framework / component library preference (shadcn/ui, Headless UI, plain Tailwind)?
2. Should the voice selector in the Greeting node fetch voices from ElevenLabs API, or use a hardcoded list for PoC?

**Recorded answers:**
- UI library: _unanswered_
- Voice selector: _unanswered_

---

## Story 11 — Call log viewer

As an **admin**, I want to **view a list of past calls and drill into any call to see the full transcript and workflow path**, so that **I can review how the AI handled each caller and identify issues**.

### Acceptance criteria
- [ ] A page exists at `/calls` in the React app showing a table of recent calls:
  - Columns: date/time, caller number (masked: `+1 *** *** 1234`), duration, workflow name, status (completed / transferred / error).
  - Sorted by most recent first.
  - Pagination or infinite scroll.
- [ ] Clicking a row navigates to `/calls/{id}` showing:
  - Call metadata (date, duration, caller number, workflow used).
  - Full transcript as a chat-style timeline (caller messages on the left, AI responses on the right).
  - Workflow path visualisation: which nodes were visited, in order (could be a simple breadcrumb or a miniature flow diagram with visited nodes highlighted).
  - Extracted slot data displayed as key-value pairs.
  - Any errors or transfers noted inline in the timeline.
- [ ] Data fetched from `GET /api/calls` and `GET /api/calls/{id}` (Story 9).

### Unit tests
- Call list component: renders rows from mock data; columns display correct values; phone number is masked.
- Call detail component: renders transcript messages in correct order; caller vs AI messages styled differently.
- Empty state: no calls → "No calls yet" message displayed.
- Error state: API failure → error message displayed.

### QA verification (Playwright)
1. **Navigate to `/calls`** → table loads with at least one call (from previous QA runs).
2. **Verify columns** — date, masked phone number, duration, workflow name are all visible.
3. **Click a call row** → navigates to call detail page.
4. **Verify transcript** — caller and AI messages are displayed in chronological order.
5. **Verify slot data** — extracted slots (e.g. `caller_name: "Alex"`) are shown.
6. **Verify workflow path** — the nodes visited during the call are displayed in order.
7. **Navigate back** to the call list → previous state preserved (no re-fetch flicker).

### Blocked until answered
1. Phone number masking: always mask in the UI, or configurable?
2. Transcript: real-time (WebSocket updates during a live call) or post-call only for PoC?

**Recorded answers:**
- Phone masking: _unanswered_
- Real-time transcript: _unanswered_

---

## Story 12 — Polish: interruptions, filler phrases, error handling, auth

As a **demo presenter**, I want **the system to feel polished — handling interruptions, filling silence during long LLM responses, recovering from errors, and requiring login**, so that **the PoC is demo-ready and doesn't fall apart on the first edge case**.

### Acceptance criteria

#### Interruption handling
- [ ] When the caller speaks while TTS audio is playing, the pipeline:
  1. Immediately sends a `clear` message on the Twilio WebSocket to stop playback.
  2. Discards any queued TTS audio for the interrupted response.
  3. Processes the new caller input normally.
- [ ] The system does not "talk over" the caller for more than ~500ms after they start speaking.

#### Filler phrases
- [ ] If the LLM takes > 800ms to start producing tokens, the pipeline plays a pre-synthesized filler phrase ("One moment, please", "Let me check on that", etc.).
- [ ] Filler audio is pre-generated at server startup (3-5 variants) and cached — no TTS latency.
- [ ] Filler audio is interrupted as soon as the real LLM response audio is ready.

#### Error handling
- [ ] If Deepgram disconnects mid-call: attempt reconnection (1 retry); if it fails, speak "I'm sorry, I'm having trouble hearing you. Please hold." and keep the call alive.
- [ ] If the LLM request fails: speak "I apologize, I'm having a technical issue. Let me transfer you." and trigger a transfer to a fallback number (configurable).
- [ ] If ElevenLabs fails: fall back to a basic TTS (Twilio `<Say>` or pyttsx3) for the error message, then attempt to continue.
- [ ] No unhandled exceptions crash the server or drop the WebSocket.

#### Basic auth
- [ ] The web dashboard requires login (email + password, or a simple shared secret for PoC).
- [ ] API endpoints under `/api/` require a Bearer token or session cookie.
- [ ] The Twilio webhook endpoint (`/twilio/incoming`) does **not** require auth (Twilio calls it) but validates the `X-Twilio-Signature` header.

### Unit tests
- **Interruption:** Mock a scenario where STT emits a `speech_final` while TTS is sending audio → `clear` message sent, TTS queue flushed.
- **Filler:** Mock LLM latency > 800ms → filler audio is sent before the real response.
- **Filler cancelled:** Mock LLM response arriving at 600ms → no filler played.
- **Deepgram reconnect:** Mock disconnect → reconnection attempt → success → pipeline resumes.
- **Deepgram reconnect failure:** Mock disconnect → reconnection fails → fallback message spoken.
- **LLM failure:** Mock 500 error → fallback message spoken, transfer triggered.
- **TTS failure:** Mock ElevenLabs 500 → fallback TTS used for error message.
- **Twilio signature validation:** Valid signature → request accepted. Invalid → 403.

### QA verification
1. **Interruption test (real call):** Call the number, wait for the AI to start speaking a long response, then interrupt by speaking loudly mid-sentence → AI stops, processes your new input, and responds to it (not to the old context).
2. **Filler test (real call):** Trigger a complex question that requires a long LLM response → hear a brief filler phrase before the real answer.
3. **Error resilience (simulated):** Temporarily revoke the Deepgram API key → call the number → hear the fallback message (not silence or a crash).
4. **Auth test (Playwright):** Navigate to `/calls` without logging in → redirected to login page. Log in → dashboard accessible. Invalid credentials → error message shown.
5. **Twilio signature (curl):** Send a request to `/twilio/incoming` without a valid signature → 403. With a valid signature → 200 with TwiML.

### Blocked until answered
1. Auth approach: email/password (with a users table), or a single shared secret/API key for the PoC?
2. Fallback transfer number for error scenarios?
3. Filler phrase voice: same ElevenLabs voice as the active workflow, or a neutral pre-recorded voice?

**Recorded answers:**
- Auth approach: _unanswered_
- Fallback number: _unanswered_
- Filler voice: _unanswered_

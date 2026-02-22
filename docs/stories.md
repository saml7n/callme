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
          → Story 7: Conversation nodes + single-node workflow engine
            → Story 8: Decision nodes + multi-node workflows (routing & context passing)
              → Story 9: Action nodes (end_call, transfer)
                → Story 10: REST API + persistence (workflows & call logs)
                  → Story 11: Visual workflow builder (React Flow)
                    → Story 12: Call log viewer
                      → Story 13: Polish — interruptions, filler phrases, error handling, auth
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
- [x] `server/` directory exists with:
  - `pyproject.toml` (or `requirements.txt`) listing core dependencies: `fastapi`, `uvicorn`, `websockets`, `httpx`, `pydantic`, `pydantic-settings`, `sqlmodel`, `pytest`, `pytest-asyncio`.
  - `app/main.py` — a FastAPI app that starts and serves a health-check endpoint (`GET /health` → `{"status": "ok"}`).
  - `app/config.py` — reads all env vars via `pydantic-settings` (`BaseSettings`).
  - `tests/` directory with a passing smoke test for the health endpoint.
- [x] `web/` directory exists with:
  - Vite + React + TypeScript + Tailwind scaffolded (e.g. via `npm create vite@latest`).
  - A placeholder `App.tsx` that renders "CallMe — AI Receptionist".
  - Dev server starts with `npm run dev`.
- [x] `.env.example` at repo root lists all anticipated env vars (from Story 0).
- [x] `.gitignore` covers Python (`__pycache__`, `.venv`, etc.) and Node (`node_modules`, `dist`, etc.).
- [x] `README.md` at repo root has setup instructions for both `server/` and `web/`.

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
- [x] A FastAPI route exists at `POST /twilio/incoming` that returns TwiML:
  ```xml
  <Response>
    <Connect>
      <Stream url="wss://{PUBLIC_URL}/twilio/media-stream" />
    </Connect>
  </Response>
  ```
- [x] A FastAPI WebSocket endpoint exists at `/twilio/media-stream` that:
  - Accepts the Twilio connection.
  - Parses the `connected`, `start`, `media`, and `stop` events from Twilio's JSON protocol.
  - Logs the `streamSid`, `callSid`, and audio codec from the `start` event.
  - Decodes base64 μ-law audio payloads from `media` events.
  - Can send base64-encoded μ-law audio back to Twilio via the `media` message format.
  - Handles `stop` and WebSocket close gracefully.
- [x] The Twilio phone number's webhook is configured to point at `{PUBLIC_URL}/twilio/incoming` (via console or API).

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
- Twilio number configured: `+441279969211` (SID: `PN10ff13ded9e05309982affcdece20dc6`). Webhook set to `{PUBLIC_URL}/twilio/incoming` via Twilio REST API.
- Tunnel confirmed: ngrok free tier. URL changes per session — webhook must be re-set each time ngrok restarts.

---

## Story 3 — Deepgram STT client (standalone)

As a **developer**, I want **a tested, reusable Deepgram streaming client**, so that **I can feed it raw audio and receive real-time transcripts without coupling it to the Twilio handler**.

### Acceptance criteria
- [x] A Python module exists at `app/stt/deepgram.py` with a class `DeepgramSTTClient`:
  - `async connect()` — opens a WebSocket to Deepgram's streaming endpoint with config: `model`, `encoding=mulaw`, `sample_rate=8000`, `channels=1`, `punctuate=true`, `endpointing` (configurable ms).
  - `async send_audio(chunk: bytes)` — sends raw audio bytes to Deepgram.
  - `async receive_transcript()` — async generator yielding transcript events with: `transcript` (str), `is_final` (bool), `speech_final` (bool), `confidence` (float).
  - `async close()` — sends close signal and disconnects.
- [x] The client reads `DEEPGRAM_API_KEY` from config.
- [x] Connection errors, auth failures, and unexpected disconnects are handled with clear exceptions.

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
- Model: Nova-3 (confirmed from Story 0).
- Endpointing: 300ms (default, working well in QA — clean speech_final events).

---

## Story 4 — LLM client (standalone)

As a **developer**, I want **a tested, swappable LLM client with streaming support and tool calling**, so that **I can generate conversational responses and structured data extraction without coupling to the voice pipeline**.

### Acceptance criteria
- [x] A Python module exists at `app/llm/openai.py` with a class `LLMClient`:
  - `async chat_stream(messages: list[dict], tools: list[dict] | None) -> AsyncGenerator[str, None]` — streams text chunks from the LLM.
  - `async chat(messages: list[dict], tools: list[dict] | None) -> str` — returns the full response (non-streaming, for simpler use cases).
  - `async chat_structured(messages: list[dict], schema: dict) -> dict` — returns structured JSON output validated against a schema (for slot extraction).
  - Supports system messages, tool definitions, and tool-call responses.
- [x] The client reads `OPENAI_API_KEY` from config. Model name is configurable (default: `gpt-4o`).
- [x] An abstract base class or protocol `BaseLLMClient` exists so Claude or another provider can be swapped in later.
- [x] Rate limit (429) and server error (5xx) responses trigger retries with backoff (max 3 attempts).

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
- LLM provider: OpenAI GPT-4o (confirmed from Story 0). SDK v2.21.0.
- Guardrails: None for PoC — system prompt only.

---

## Story 5 — ElevenLabs TTS client (standalone)

As a **developer**, I want **a tested ElevenLabs TTS client that outputs μ-law audio suitable for Twilio**, so that **I can convert text to speech independently of the voice pipeline**.

### Acceptance criteria
- [x] A Python module exists at `app/tts/elevenlabs.py` with a class `ElevenLabsTTSClient`:
  - `async synthesize(text: str) -> bytes` — returns complete μ-law audio bytes for the given text.
  - `async synthesize_stream(text: str) -> AsyncGenerator[bytes, None]` — streams μ-law audio chunks as they become available (for lower latency).
  - Configurable: `voice_id`, `model_id`, `output_format` (default: `ulaw_8000` for Twilio compatibility), `optimize_streaming_latency` (default: `3`).
- [x] The client reads `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` from config.
- [x] Previous/next request stitching (`previous_request_ids`) is supported for multi-sentence continuity.
- [x] Auth failure and rate-limit errors are handled with clear exceptions.

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
- Voice ID: Rachel (`21m00Tcm4TlvDq8ikWAM`) — confirmed from Story 0.
- Latency level: `3` (high optimisation) — acceptable quality trade-off for PoC.

---

## Story 6 — End-to-end voice pipeline (first real phone conversation)

As a **demo presenter**, I want to **call the Twilio number and have a free-form AI conversation**, so that **the full audio pipeline is proven before we add workflow logic**.

This is the first story where all audio components come together. No workflow engine yet — the LLM uses a single hardcoded system prompt.

### Acceptance criteria
- [x] A `CallPipeline` class (or equivalent) in `app/pipeline.py` orchestrates a single call:
  1. Receives audio from the Twilio WebSocket handler (Story 2).
  2. Forwards audio chunks to `DeepgramSTTClient` (Story 3).
  3. On `speech_final`, sends the transcript + conversation history to `LLMClient.chat_stream()` (Story 4).
  4. As LLM text chunks arrive, accumulates them into sentences (split on `.`, `!`, `?`).
  5. Sends each sentence to `ElevenLabsTTSClient.synthesize_stream()` (Story 5).
  6. Forwards TTS audio chunks back to the Twilio WebSocket as base64 `media` messages.
- [x] The hardcoded system prompt is: *"You are a friendly AI receptionist for a business. Greet the caller, ask how you can help, and have a natural conversation. Keep responses concise — 1-2 sentences at a time."*
- [x] On call start, the system speaks a greeting without waiting for the caller (proactive first message).
- [x] Conversation history (messages array) is maintained for the duration of the call.
- [x] The pipeline handles Twilio `stop` event and caller hang-up gracefully (closes STT and any in-flight requests).

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
- Services confirmed: All four services (Twilio, Deepgram, ElevenLabs, OpenAI) individually QA'd in Stories 2-5.
- Sentence splitting: Split on punctuation (`.!?`) — eagerly sends each completed sentence to TTS for low latency. Any trailing text without punctuation is flushed as a remainder.

---

## Story 7 — Workflow engine with conversation nodes

As a **developer**, I want **a workflow engine that loads a JSON workflow and runs conversation nodes with per-node chat history**, so that **the AI receptionist's behaviour is configurable without code changes**.

This is the first workflow story. It supports only **conversation nodes** — the simplest, most important node type. Decision nodes and action nodes come in later stories. The engine is wired into the voice pipeline immediately, so QA is a real phone call.

### Design: Three Node Types (built incrementally)

| Type | Purpose | Built in |
|---|---|---|
| **Conversation** | Talks to the caller following plain-English instructions. Has its own chat history. A Router LLM decides each turn whether to STAY or transition. | **This story** |
| **Decision** | Pure routing — no conversation with the caller. Evaluates accumulated context and picks an outgoing edge. | Story 8 |
| **Action** | Performs a side effect (end call, transfer, etc.). Extensible — new action types added over time. | Story 9 |

### Design: Context Passing Between Nodes

Each conversation node maintains its **own `messages[]`** array — separate from other nodes. When transitioning between nodes:
1. A summary of the outgoing node's conversation is generated (via LLM).
2. Key information points are extracted (names, dates, intents, etc.).
3. The next node receives accumulated summaries as context prefix, keeping its own chat history focused and avoiding LLM context bloat.

### Workflow JSON Format

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
    }
  ],
  "edges": [
    { "id": "e1", "source": "node_1", "target": "node_2", "label": "Caller has stated their need" }
  ]
}
```

### Acceptance criteria
- [x] A workflow schema is defined (Pydantic models or JSON schema) supporting:
  - `id`, `name`, `version` (metadata).
  - `nodes[]` — each with `id`, `type` (enum: `conversation`), `data` (type-specific), `position`.
  - `edges[]` — each with `id`, `source`, `target`, `label` (plain English description of when to follow this edge).
  - `entry_node_id`.
- [x] Conversation node `data` includes:
  - `instructions` (str) — system prompt / personality for this node.
  - `examples` (list of `{ role, content }`, optional) — few-shot examples injected into the message history.
  - `max_iterations` (int, default 10) — max conversation turns before forcing transition to the first outgoing edge.
- [x] A `WorkflowEngine` class at `app/workflow/engine.py`:
  - `__init__(workflow: dict, llm_client: LLMClient)` — loads and validates the workflow graph.
  - `current_node` property.
  - `async start() -> str` — enters the entry node and returns an initial response (Responder LLM generates it from the node's instructions).
  - `async handle_input(transcript: str) -> tuple[str, bool]` — processes caller input, returns `(response_text, call_ended)`. Internally:
    1. Appends the caller's transcript to the current node's chat history.
    2. Calls the **Router LLM** with: current node info, outgoing edge labels, node chat history. Router returns `STAY` or an edge ID.
    3. If `STAY`: calls the **Responder LLM** with node `instructions` + `examples` + node chat history → returns the response.
    4. If transition: generates a summary of the current node's conversation, carries accumulated summaries forward, enters the new node, calls Responder LLM → returns the response.
  - Checks `max_iterations` — if reached, forces transition along the first available edge.
- [x] Each conversation node maintains its own `messages[]` (not shared with other nodes).
- [x] When transitioning, a `NodeSummary` is generated: `{ summary: str, key_info: dict }` — extracted via a single LLM call.
- [x] The `CallPipeline` from Story 6 accepts an optional workflow dict. If provided, it delegates to `WorkflowEngine` instead of the hardcoded prompt. If no workflow, falls back to Story 6 behaviour.
- [x] A sample single-node workflow exists at `server/schemas/examples/simple_receptionist.json`.
- [x] Workflow validation: missing `entry_node_id`, dangling edge references, missing required fields → clear error messages.
- [x] A **workflow preview page** exists at `http://localhost:5173/workflows/preview` (React Flow, read-only) showing:
  - All nodes with type badge, instructions preview, examples count, max iterations.
  - Edges with labels and animated arrows.
  - Entry node highlighted (indigo ring + "ENTRY" badge).
  - Header with workflow name, version, node/edge counts.
- [x] A `GET /api/workflows/active` endpoint returns the currently loaded workflow JSON.
- [x] CORS enabled on the server for the Vite dev origin (`localhost:5173`).

### Unit tests (mocked LLM)
- **Engine start:** enters entry node, calls Responder LLM with node instructions, returns response.
- **Handle input — STAY:** Router returns STAY → Responder called with node instructions + growing chat history → response returned.
- **Handle input — TRANSITION:** Router returns edge ID → summary generated → new node entered → Responder called with new node's instructions + accumulated summaries.
- **Max iterations:** after `max_iterations` turns, engine forces transition along first available edge without consulting Router.
- **Single-node workflow (no outgoing edges):** engine stays in the node indefinitely (no crash, no forced transition).
- **Router LLM context:** Router is called with correct payload (current node, edge labels, chat history).
- **Responder LLM context:** Responder is called with node instructions, examples, accumulated summaries, and current node's chat history.
- **Validation:** missing entry node → error; dangling edge target → error; empty workflow → error.
- **Pipeline with workflow:** start → engine response → TTS called with text.
- **Pipeline without workflow:** falls back to hardcoded prompt (Story 6 preserved).

### QA verification
1. **Visual verification**: Open `http://localhost:5173/workflows/preview` in a browser → see the workflow graph rendered with React Flow. Verify:
   - The "greeting" node is displayed with an indigo ring and "ENTRY" badge.
   - Node shows: instructions preview, "4 examples", "max 20 turns".
   - Header shows: "Simple Receptionist", "v1", "1 node", "0 edges".
   - Minimap and zoom controls are present.
2. **API verification**: `curl http://localhost:3000/api/workflows/active` → returns the full workflow JSON with correct `id`, `name`, `nodes`, `edges`.
3. **Phone call**: Load the workflow into the pipeline and **call the Twilio number from a real phone**.
4. Have a 3-4 turn conversation → AI follows the node's instructions, maintains context within the node.
5. Compare to Story 6's hardcoded prompt → workflow-driven conversation is equally coherent.

### Blocked until answered
1. Router LLM model: GPT-4o-mini (cheap/fast) or same as Responder (GPT-4o)?
2. Summary generation: separate LLM call, or fold into the Router's response?

**Recorded answers:**
- Router model: GPT-4o-mini (cheap/fast for routing decisions).
- Summary approach: Separate LLM call via the Router model — generates `{ summary, key_info }` JSON on node transition.

**Completion evidence:**
- Unit tests: 111 passed (24 pipeline, 15 engine, 14 schema, plus existing tests).
- QA — Visual: Workflow preview page at `/workflows/preview` renders single-node graph with ENTRY badge, instructions preview, 4 examples, max 20 turns.
- QA — API: `curl /api/workflows/active` returns full workflow JSON.
- QA — Phone call: Called +441279969211, AI greeted as Smile Dental receptionist, responded to questions about services and hours across multiple turns.

---

## Story 8 — Decision nodes + multi-node workflows

As a **caller**, I want **the AI to route my call through different conversation paths based on what I say**, so that **I get relevant, focused help instead of a generic response**.

This story adds **decision nodes** and proves multi-node workflows with context (summary + key info) passing between nodes.

### Acceptance criteria
- [x] Decision node type (`type: "decision"`) added to the workflow schema:
  - `data.instruction` (str) — guidance for the Router LLM on what to evaluate (e.g. *"Determine the caller's primary intent"*).
  - Multiple outgoing edges, each with a `label` describing the condition (e.g. *"Caller wants to book an appointment"*).
  - No conversation with the caller — a decision node is purely routing logic.
- [x] When the engine enters a decision node:
  1. The Router LLM evaluates accumulated context (summaries + key info from previous nodes) against the outgoing edge labels.
  2. Picks the best matching edge.
  3. Immediately transitions to the target node — **no response is spoken** from the decision node itself.
- [x] Context passing across multi-node workflows:
  - On leaving a conversation node, a `NodeSummary` is generated: `{ summary: str, key_info: dict }`.
  - Summaries accumulate as the call moves through the graph.
  - Each new conversation node receives the accumulated summaries as a context prefix before its own instructions.
  - Per-node chat history is fresh (not carried over — only summaries cross boundaries).
- [x] A sample multi-node workflow at `server/schemas/examples/reception_flow.json` with at least 5 nodes:
  - Greeting (conversation) → Intent router (decision) → Book appointment (conversation) / General inquiry (conversation) / Speak to human (conversation).
- [x] The workflow is loaded into the voice pipeline and testable via a real phone call.

### Unit tests (mocked LLM)
- **Decision node:** Router evaluates accumulated context → picks the correct edge based on labels.
- **Decision node — no matching edge:** falls back to first edge (graceful default).
- **Decision node is silent:** no response text generated for the caller.
- **Multi-node traversal:** greeting → decision → conversation node A (correct path taken, verified by checking which node is current).
- **Context accumulation:** summaries from nodes 1 and 2 are present in the context passed to node 3.
- **Summary generation:** LLM is called with the outgoing node's chat history; result stored as `NodeSummary`.
- **Fresh chat history:** when entering a new conversation node, its `messages[]` starts empty (only summaries are inherited).
- **Decision node with single outgoing edge:** immediately follows that edge (no LLM call needed).

### QA verification
1. **Visual verification**: Open `http://localhost:5173/workflows/preview` → see the full multi-node graph. Verify:
   - 5 nodes visible: greeting (entry), intent router (decision), book appointment, general inquiry, speak to human.
   - Decision node rendered distinctly (yellow/diamond style).
   - Edges with labels connecting all nodes correctly.
   - Entry node highlighted.
2. **API verification**: `curl http://localhost:3000/api/workflows/active` → returns the full 5-node workflow JSON.
3. **Phone call — booking path**: Call the Twilio number, say *"I'd like to book a cleaning"* → AI routes to the appointment booking node, asks relevant follow-up questions about dates and times.
4. **Phone call — inquiry path**: Hang up. Call again, say *"I have a question about your prices"* → AI routes to the general inquiry node, discusses services and pricing.
5. **Phone call — transfer path**: Call again, say *"Can I speak to someone?"* → AI routes to the "speak to human" node.
6. In each case, verify the AI's responses match the target node's instructions (not generic fallback).
7. **Automated QA** (`scripts/qa_workflow.py`): 7 tests, 27 assertions — all passed ✓
   - Test 1 — Direct booking path: greeting → intent_router → book_appointment ✓
   - Test 2 — Inquiry path: greeting → intent_router → general_inquiry (with pricing data) ✓
   - Test 3 — Speak to human path: greeting → intent_router → speak_to_human ✓
   - Test 4 — Re-route booking → inquiry: changed topic mid-booking, re-routed via intent_router ✓
   - Test 5 — Scope enforcement: booking node deflected off-topic question correctly ✓
   - Test 6 — Context carries across nodes: caller name captured in summary, passed to booking node ✓
   - Test 7 — Re-route inquiry → booking: asked about prices then booked, re-routed correctly ✓

### Blocked until answered
- None (builds on Story 7 decisions).

---

## Story 9 — Action nodes (end call, transfer)

As a **developer**, I want **action nodes that perform side effects — ending the call or transferring to a human**, so that **workflows can do more than talk — they can take real actions**.

Action nodes are extensible by `action_type`. This story ships the first two types; more (e.g. `api_call`, `send_sms`, `schedule_callback`) can be added later without schema changes.

### Acceptance criteria
- [x] Action node type (`type: "action"`) added to the workflow schema:
  - `data.action_type` (str) — extensible enum, starting with: `end_call`, `transfer`.
  - Type-specific fields in `data`:
    - `end_call`: `{ message: str }` — closing message to speak before hanging up.
    - `transfer`: `{ target_number: str, announcement: str }` — message to speak, then transfer the call.
- [x] When the engine enters an action node:
  - `end_call` → returns `(message, call_ended=True)`.
  - `transfer` → returns `(announcement, call_ended=False)` + a `transfer` signal with the target number.
- [x] The `CallPipeline` handles action results:
  - `call_ended=True` → TTS speaks the closing message, then closes the Twilio WebSocket (call ends).
  - `transfer` → TTS speaks the announcement, then sends a Twilio REST API call to update the live call with `<Dial><Number>target</Number></Dial>` TwiML (or closes WebSocket with transfer TwiML).
- [x] Update `reception_flow.json` to include:
  - An `end_call` action after the general inquiry branch.
  - A `transfer` action for the "speak to human" branch.
- [x] Unknown `action_type` raises a descriptive `WorkflowError`.

### Unit tests
- **End call action:** engine returns message + `call_ended=True`.
- **Transfer action:** engine returns announcement + transfer signal with target number.
- **Pipeline handles end_call:** TTS speaks message, WebSocket close triggered.
- **Pipeline handles transfer:** TTS speaks announcement, Twilio REST API called with correct number.
- **Unknown action_type:** raises `WorkflowError` with descriptive message.
- **Action node with outgoing edges after end_call:** edges are ignored (end_call is terminal).
- **Action node with outgoing edges after transfer:** optionally follow a "transfer failed" edge.

### QA verification
1. **Visual verification**: Open `http://localhost:5173/workflows/preview` → see action nodes rendered with red styling and action_type badges (`end_call`, `transfer`). Verify edges connect to them correctly from conversation/decision nodes.
2. **Phone call — transfer**: Call the Twilio number, navigate through the flow to the "speak to human" branch → hear the transfer announcement. (For PoC, the transfer target can be your own mobile — verify the call redirects.)
3. **Phone call — end call**: Call again, navigate to the general inquiry branch, complete the conversation → hear the closing message, call disconnects cleanly.
4. Server logs show clean shutdown (no errors, no orphaned connections).

### Blocked until answered
1. Transfer implementation: Twilio REST API to update the live call, or close WebSocket and return TwiML?
2. For PoC testing, should transfer go to a real number, or just play an announcement and hang up?

**Recorded answers:**
- Transfer method: Use Twilio REST API to update the live call with `<Dial>` TwiML. Provides full control during the call.
- Transfer target: Real transfer to a configurable number. Default test number: `07908121095`. The `target_number` is specified in the action node's `data`.

### Results
- **Unit tests:** 145 passed (19 new: 5 schema, 6 engine, 6 pipeline action tests + 2 engine fixture tests). `uv run pytest tests/ -v` — all green.
- **QA tests (live LLM):** 31/31 assertions passed across 9 tests (7 Story 8 + 2 Story 9). New tests: `test_end_call_action` (booking → end_call), `test_transfer_action` (speak_to_human → transfer).
- **Implementation:** `ActionType` enum, `ActionNodeData` Pydantic model, `ActionResult` dataclass. Engine returns `str | ActionResult` from `start()` / `handle_input()`. Pipeline handles end_call (close) and transfer (Twilio REST API). `ActionNode.tsx` web component (red theme).

---

## Story 10 — REST API + persistence

As a **dashboard developer**, I want **CRUD endpoints for workflows and read endpoints for call logs**, so that **the React frontend has a backend to talk to and workflows survive server restarts**.

### Acceptance criteria
- [x] Database schema (SQLModel) with tables:
  - `workflows` — `id` (UUID), `name`, `version`, `graph_json` (full workflow JSON), `is_active` (bool), `phone_number` (nullable), `created_at`, `updated_at`.
  - `calls` — `id` (UUID), `call_sid`, `from_number`, `to_number`, `workflow_id` (FK, nullable), `started_at`, `ended_at`, `duration_seconds`.
  - `call_events` — `id`, `call_id` (FK), `timestamp`, `event_type` (enum: `transcript`, `llm_response`, `node_transition`, `summary_generated`, `action_executed`, `error`), `data_json`.
- [x] SQLite database created on startup (no migration tool needed for PoC).
- [x] REST API endpoints:
  - `GET /api/workflows` — list all workflows (id, name, is_active, updated_at).
  - `GET /api/workflows/{id}` — full workflow including `graph_json`.
  - `POST /api/workflows` — create a new workflow.
  - `PUT /api/workflows/{id}` — update a workflow.
  - `POST /api/workflows/{id}/publish` — set `is_active=True` and assign to a phone number.
  - `DELETE /api/workflows/{id}` — delete a workflow.
  - `GET /api/calls` — list recent calls (id, from, to, workflow_name, started_at, duration).
  - `GET /api/calls/{id}` — full call detail including all events.
- [x] The voice pipeline logs events to `call_events` in real time during a call (node transitions, transcripts, LLM responses, summaries).
- [x] The pipeline loads the active workflow for the Twilio number from the database (instead of from a JSON file).
- [x] Input validation on all endpoints (Pydantic models). Invalid `graph_json` → 422.

### Unit tests
- **CRUD:** create → read → update → read (verify changes) → delete → read (404).
- **Publish:** publishing workflow A deactivates the previously active workflow for the same phone number.
- **Call log:** create a call record with events → list calls → get call detail with events.
- **Validation:** invalid `graph_json` → 422. Missing required fields → 422.
- **Pipeline loads from DB:** active workflow is fetched and used by the engine.

### QA verification
1. Use `curl` to create a workflow → 201. Get it → matches. Update it → 200. Publish it → `is_active=True`. List workflows → appears.
2. **Call the Twilio number** → the published workflow drives the conversation.
3. After the call, `GET /api/calls` shows the call → `GET /api/calls/{id}` shows transcript, node transitions, and summaries.

### Blocked until answered
1. Soft-delete or hard-delete for workflows?
2. Auth on API endpoints now or defer to Story 13?

**Recorded answers:**
- Delete strategy: Hard delete — row removed entirely. No recovery needed for PoC.
- Auth timing: Defer to Story 13 — no auth on API endpoints for now.

---

## Story 11 — Visual workflow builder (React Flow)

As an **admin**, I want **a drag-and-drop visual editor for designing call workflows**, so that **I can create and modify call flows without writing JSON by hand**.

### Acceptance criteria
- [x] A page at `/workflows/new` (and `/workflows/{id}/edit`) renders a React Flow canvas.
- [x] Left sidebar palette with three node types that can be dragged onto the canvas:
  - **Conversation** (blue) — shows a preview of the `instructions` text.
  - **Decision** (yellow/diamond) — shows the `instruction` text.
  - **Action** (red) — shows the `action_type` badge.
- [x] Edges drawn between node handles. Each edge has an editable `label` (plain English condition).
- [x] Clicking a node opens a right sidebar config panel:
  - **Conversation:** `instructions` (textarea), `examples` (add/remove pairs), `max_iterations` (number).
  - **Decision:** `instruction` (textarea). Outgoing edge labels are edited on the edges themselves.
  - **Action:** `action_type` (dropdown: `end_call`, `transfer`), then type-specific fields (`message` for end_call; `target_number` + `announcement` for transfer).
- [x] One node is marked as the entry node (visual indicator — e.g. green border or "START" badge). Clicking "Set as entry" on a node marks it.
- [x] "Save" → `PUT /api/workflows/{id}` with serialised graph. "Publish" → `POST /api/workflows/{id}/publish`.
- [x] Loading `/workflows/{id}/edit` fetches the workflow and renders saved nodes, edges, and positions.
- [x] Delete a node → node and connected edges removed.
- [x] Validation warnings: no entry node set, orphan nodes (no edges in or out), duplicate IDs.
- [x] Minimap, zoom controls, background grid.

### Unit tests (Vitest + React Testing Library)
- Canvas renders without crashing.
- Adding each node type → appears in React Flow state with correct type.
- Clicking a conversation node → config panel shows instructions textarea.
- Clicking an action node → config panel shows action_type dropdown.
- Save → correct API payload sent (mock fetch).
- Load workflow → nodes and edges in correct positions.
- Delete a node → node and connected edges removed.

### QA verification (Playwright)
1. Navigate to `/workflows/new` → empty canvas with node palette.
2. Drag a Conversation node, a Decision node, and an Action node onto the canvas.
3. Click the Conversation node → config panel opens, type instructions → node preview updates.
4. Draw edges between nodes → edge labels are editable.
5. Mark the Conversation node as entry → visual indicator appears.
6. Save → API call sent with correct payload. Reload → layout restored.
7. Publish → workflow is active. **Call the Twilio number** → conversation follows the workflow built in the UI.
8. Delete a node → node and edges removed.

### Blocked until answered
1. UI component library: shadcn/ui, Headless UI, or plain Tailwind?
2. Should the builder support undo/redo for PoC?

**Recorded answers:**
- UI library: shadcn/ui (Radix primitives + Tailwind).
- Undo/redo: Defer to a later story — skip for PoC.

---

## Story 12 — Call log viewer

As an **admin**, I want **a list of past calls with drill-down into full transcripts and workflow paths**, so that **I can review how the AI handled each caller**.

### Acceptance criteria
- [ ] A page at `/calls` shows a table of recent calls:
  - Columns: date/time, caller number (masked: `+44 *** *** 1234`), duration, workflow name, status (completed / transferred / error).
  - Sorted by most recent first. Pagination or infinite scroll.
- [ ] Clicking a row navigates to `/calls/{id}` showing:
  - Call metadata (date, duration, caller number, workflow name).
  - Full transcript as a chat-style timeline (caller on the left, AI on the right).
  - Workflow path: which nodes were visited, in order (breadcrumb or mini flow diagram with visited nodes highlighted).
  - Node summaries displayed at each transition point in the timeline.
  - Extracted key info shown as key-value badges.
  - Errors or transfers noted inline.
- [ ] Data from `GET /api/calls` and `GET /api/calls/{id}` (Story 10).

### Unit tests (Vitest + React Testing Library)
- Call list: renders rows from mock data; phone number is masked; columns correct.
- Call detail: transcript messages in chronological order; caller vs AI styled differently.
- Workflow path: nodes listed in order; current node highlighted during playback.
- Empty state: "No calls yet" message.
- Error state: API failure → error message displayed.

### QA verification (Playwright)
1. Navigate to `/calls` → table shows calls from previous QA runs.
2. Verify columns: date, masked number, duration, workflow name.
3. Click a call → detail page with transcript, node path, and key info.
4. Verify transcript order matches what was said during the call.
5. Navigate back → list state preserved.

### Blocked until answered
1. Phone number masking: always mask, or configurable?
2. Real-time transcript (WebSocket updates during live call) or post-call only for PoC?

**Recorded answers:**
- Phone masking: _unanswered_
- Real-time transcript: _unanswered_

---

## Story 13 — Polish: interruptions, filler phrases, error handling, auth

As a **demo presenter**, I want **the system to feel polished — handling interruptions, filling silence, recovering from errors, and requiring login**, so that **the PoC is demo-ready**.

### Acceptance criteria

#### Interruption handling
- [ ] When the caller speaks while TTS audio is playing:
  1. Immediately send a `clear` message on the Twilio WebSocket to stop playback.
  2. Discard any queued TTS audio for the interrupted response.
  3. Process the new caller input normally.
- [ ] The system does not "talk over" the caller for more than ~500ms.

#### Filler phrases
- [ ] If the LLM takes > 800ms to start producing tokens, the pipeline plays a pre-synthesised filler phrase (*"One moment, please"*, *"Let me check on that"*, etc.).
- [ ] Filler audio is pre-generated at server startup (3-5 variants) and cached.
- [ ] Filler is interrupted as soon as the real LLM response audio is ready.

#### Error handling
- [ ] Deepgram disconnect mid-call → attempt reconnection (1 retry); on failure, speak *"I'm sorry, I'm having trouble hearing you. Please hold."*
- [ ] LLM failure → speak *"I apologise, I'm having a technical issue. Let me transfer you."* → trigger transfer to fallback number.
- [ ] ElevenLabs failure → fall back to Twilio `<Say>` for the error message.
- [ ] No unhandled exceptions crash the server or drop the WebSocket.

#### Basic auth
- [ ] Web dashboard requires login (simple shared secret or email/password).
- [ ] API endpoints under `/api/` require a Bearer token or session cookie.
- [ ] `/twilio/incoming` does **not** require auth but validates `X-Twilio-Signature`.

### Unit tests
- **Interruption:** STT emits `speech_final` while TTS is playing → `clear` sent, queue flushed.
- **Filler:** LLM latency > 800ms → filler audio sent. LLM latency < 800ms → no filler.
- **Deepgram reconnect:** disconnect → retry → success. / disconnect → retry → fail → fallback message.
- **LLM failure:** 500 → fallback message + transfer.
- **TTS failure:** ElevenLabs 500 → Twilio `<Say>` fallback.
- **Auth:** valid token → 200. Missing token → 401. Invalid → 403.
- **Twilio signature:** valid → accepted. Invalid → 403.

### QA verification
1. **Interruption (real call):** AI speaks a long response, interrupt mid-sentence → AI stops. Responds to the new input.
2. **Filler (real call):** Ask a complex question → hear a filler phrase, then the real answer.
3. **Error resilience:** Temporarily revoke Deepgram key → call → hear fallback message (not silence/crash).
4. **Auth (Playwright):** `/calls` without login → redirected. Login → accessible. Bad credentials → error.
5. **Twilio signature (curl):** request without signature → 403. With valid signature → 200.

### Blocked until answered
1. Auth approach: shared secret or email/password with a users table?
2. Fallback transfer number for error scenarios?
3. Filler phrase voice: same ElevenLabs voice as the active workflow, or pre-recorded neutral?

**Recorded answers:**
- Auth approach: _unanswered_
- Fallback number: _unanswered_
- Filler voice: _unanswered_

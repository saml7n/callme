# Development Guide

This guide covers setting up a local development environment, understanding code patterns, running tests, and extending the application.

---

## Table of Contents

1. [Local Setup](#1-local-setup)
2. [Project Layout](#2-project-layout)
3. [Running Tests](#3-running-tests)
4. [Server Development](#4-server-development)
5. [Web Development](#5-web-development)
6. [Code Patterns](#6-code-patterns)
7. [Adding Features](#7-adding-features)
8. [Debugging](#8-debugging)

---

## 1. Local Setup

### Prerequisites

- **Python 3.12+** — check with `python3 --version`
- **[uv](https://docs.astral.sh/uv/)** — `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Node.js 18+** and npm — `brew install node` or via [nvm](https://github.com/nvm-sh/nvm)
- **ngrok** (optional) — for receiving Twilio webhooks locally

### Environment

```bash
cp .env.example .env
# Edit .env — at minimum set CALLME_API_KEY to any strong secret
```

### Server

```bash
cd server
uv sync                    # Creates .venv and installs all deps
```

### Web

```bash
cd web
npm install
```

### Start both

```bash
# From project root:
make dev                   # Starts server (:3000) + web (:5173) concurrently

# Or separately:
make dev-server            # Server only with --reload
make dev-web               # Vite dev server only
```

The Vite dev server proxies `/api/*` and `/ws/*` requests to `localhost:3000` automatically (see `web/vite.config.ts`).

### First login

On first startup the server creates an admin user:
- **Email:** `admin@callme.local` (or `demo@callme.ai` if `SEED_DEMO=true`)
- **Password:** your `CALLME_API_KEY` value

### Tunnel for Twilio

If you need to test live calls locally:

```bash
make dev-ngrok             # Starts ngrok with a stable subdomain
```

The server auto-detects the ngrok tunnel URL via the ngrok API (localhost:4040). No need to set `PUBLIC_URL` manually.

---

## 2. Project Layout

### Server (`server/`)

```
server/
├── pyproject.toml         # Dependencies (managed by uv)
├── app/
│   ├── main.py            # FastAPI app entrypoint, startup lifecycle
│   ├── config.py          # pydantic-settings — all env vars
│   ├── auth.py            # JWT auth + get_current_user() dependency
│   ├── credentials.py     # Resolve API keys (user DB → platform env)
│   ├── crypto.py          # Fernet encrypt/decrypt for credentials
│   ├── events.py          # In-memory EventBus (live call pub/sub)
│   ├── health.py          # Deep health check probes
│   ├── pipeline.py        # CallPipeline — orchestrates STT/LLM/TTS per call
│   ├── public_url.py      # Auto-detect public URL (Fly/ngrok/env)
│   ├── seed.py            # Demo data seeder
│   ├── api/               # REST + WebSocket endpoint routers
│   ├── db/                # SQLModel models, session, call logger
│   ├── integrations/      # Google Calendar, webhook callers
│   ├── llm/               # LLM abstraction + OpenAI implementation
│   ├── stt/               # Deepgram streaming STT client
│   ├── tts/               # ElevenLabs TTS client
│   ├── twilio/            # Incoming webhook + media stream WebSocket
│   └── workflow/          # Workflow engine (schema + state machine)
├── tests/                 # 27 test files, 372+ tests
├── schemas/               # Example and template workflow JSON files
└── scripts/               # QA scripts for manual service testing
```

### Web (`web/`)

```
web/
├── package.json
├── vite.config.ts         # Dev proxy config
├── src/
│   ├── main.tsx           # App entrypoint
│   ├── App.tsx            # Router + AppShell
│   ├── pages/             # Route pages
│   │   ├── LoginPage.tsx
│   │   ├── RegisterPage.tsx
│   │   ├── SetupWizard.tsx
│   │   ├── WorkflowList.tsx
│   │   ├── WorkflowBuilder.tsx
│   │   ├── WorkflowPreview.tsx
│   │   ├── CallList.tsx
│   │   ├── CallDetail.tsx
│   │   ├── LiveCalls.tsx
│   │   ├── PhoneNumbers.tsx
│   │   └── Integrations.tsx
│   ├── components/        # Reusable components
│   │   ├── nodes/         # React Flow custom nodes
│   │   ├── ui/            # shadcn/ui primitives
│   │   └── ...            # App-specific (ConfigPanel, NodePalette, etc.)
│   ├── hooks/             # Custom React hooks
│   ├── lib/               # API client, auth, types, utils
│   └── test/              # 12 Vitest + React Testing Library test files
└── public/
```

---

## 3. Running Tests

### Server tests

```bash
cd server

# Run all (372+ tests)
uv run pytest -x -q

# Verbose output
uv run pytest -v

# Specific test file
uv run pytest tests/test_pipeline.py -v

# Specific test by name
uv run pytest -k "test_router_stay" -v

# With coverage
uv run pytest --cov=app --cov-report=term-missing
```

All tests use `pytest-asyncio` with `asyncio_mode = "auto"`. No external services are called — everything is mocked.

### Web tests

```bash
cd web

# Run all (119 tests)
npm test -- --run

# Watch mode (re-run on file changes)
npm test

# Specific file
npm test -- --run src/test/CallDetail.test.tsx

# With coverage
npm test -- --run --coverage
```

Web tests use **Vitest** + **React Testing Library**. API calls are mocked via `msw` or manual `vi.mock`.

### Run everything

```bash
make test                  # Server + web tests in sequence
```

---

## 4. Server Development

### Adding an API endpoint

1. **Create or edit a router** in `server/app/api/`:

```python
# server/app/api/my_feature.py
from fastapi import APIRouter, Depends
from app.auth import get_current_user
from app.db.models import User

router = APIRouter(prefix="/api/my-feature", tags=["my-feature"])

@router.get("/")
async def list_items(user: User = Depends(get_current_user)):
    # user.id scopes all queries
    ...
```

2. **Register the router** in `server/app/main.py`:

```python
from app.api.my_feature import router as my_feature_router
app.include_router(my_feature_router)
```

3. **Write tests** in `server/tests/test_my_feature.py`.

### Adding a database model

1. **Define the model** in `server/app/db/models.py`:

```python
class MyModel(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str
    user_id: str = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

2. **Create the table** — add to `init_db()` in `server/app/db/session.py`:

```python
SQLModel.metadata.create_all(engine)  # Already handles all models
```

New models are auto-created on startup via `SQLModel.metadata.create_all()`. For existing deployments, add a migration in the `_run_migrations()` function in `session.py`.

### Adding a workflow node type

1. **Update the schema** in `server/app/workflow/schema.py` — add the new type to the `NodeType` enum and define its data model.
2. **Handle it in the engine** in `server/app/workflow/engine.py` — add a case in the node processing logic.
3. **Add a custom React Flow node** in `web/src/components/nodes/`.
4. **Register it** in the workflow builder and node palette.

### Working with credentials

Use the `credentials.py` resolver — never read env vars directly:

```python
from app.credentials import resolve_credentials

creds = resolve_credentials(user_id, db)
deepgram_key = creds.get("deepgram_api_key")
```

This checks the user's encrypted DB settings first, then falls back to platform env vars.

---

## 5. Web Development

### Component conventions

- **Pages** go in `web/src/pages/` — one per route
- **Reusable components** go in `web/src/components/`
- **shadcn/ui primitives** are in `web/src/components/ui/` — don't modify these directly
- **Custom hooks** go in `web/src/hooks/`
- **Types and API client** live in `web/src/lib/`

### API client

All API calls go through `web/src/lib/api.ts`:

```typescript
import { api } from '@/lib/api'

// GET
const workflows = await api.workflows.list()

// POST
const workflow = await api.workflows.create({ name: 'My Flow', graph: {...} })

// The client handles JWT auth headers, 401 redirects, and error parsing
```

### Adding a new page

1. **Create the page** in `web/src/pages/MyPage.tsx`
2. **Add the route** in `web/src/App.tsx`:

```tsx
<Route path="/my-page" element={<AuthGuard><MyPage /></AuthGuard>} />
```

3. **Add nav link** in the `AppShell` component
4. **Write tests** in `web/src/test/MyPage.test.tsx`

### Styling

- Use **Tailwind CSS** utility classes
- Follow the existing design system (shadcn/ui)
- Import `@/components/ui/*` for buttons, cards, inputs, etc.
- Use the `@` path alias (maps to `web/src/`)

---

## 6. Code Patterns

### Auth dependency

Every API endpoint that needs authentication uses the `get_current_user` FastAPI dependency:

```python
@router.get("/items")
async def list_items(user: User = Depends(get_current_user)):
    # user.id is always available
    items = db.exec(select(Item).where(Item.user_id == user.id)).all()
```

### Database sessions

Use the `get_session` dependency for database access:

```python
from app.db.session import get_session
from sqlmodel import Session

@router.get("/items")
async def list_items(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    ...
```

### Error handling

Use FastAPI's `HTTPException`:

```python
from fastapi import HTTPException

if not item:
    raise HTTPException(status_code=404, detail="Item not found")
```

### Test patterns

Server tests use `pytest` with FastAPI's `TestClient`:

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_list_items(auth_headers):
    response = client.get("/api/items", headers=auth_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)
```

Common fixtures:
- `auth_headers` — JWT auth headers for a test user
- `test_user` — creates a test user in the DB
- `test_workflow` — creates a workflow for the test user
- `monkeypatch` — for mocking env vars and functions

Web tests use React Testing Library:

```typescript
import { render, screen } from '@testing-library/react'
import { MyComponent } from './MyComponent'

test('renders title', () => {
  render(<MyComponent />)
  expect(screen.getByText('My Title')).toBeInTheDocument()
})
```

---

## 7. Adding Features

### Adding a new integration type

1. **Create the integration module** in `server/app/integrations/my_service.py`
2. **Add the type** to the integration enum in `server/app/db/models.py`
3. **Handle it** in `server/app/api/integrations.py` (CRUD + OAuth if needed)
4. **Wire it into the workflow engine** in `server/app/workflow/engine.py` — called from action nodes
5. **Add UI** for configuration in `web/src/pages/Integrations.tsx`
6. **Write tests** for both server and web

### Adding a new LLM provider

The LLM layer uses a base protocol (`server/app/llm/base.py`):

```python
class BaseLLMClient(Protocol):
    async def chat(self, messages, model, ...) -> str: ...
    async def chat_stream(self, messages, model, ...) -> AsyncIterator[str]: ...
    async def chat_structured(self, messages, model, response_format, ...) -> dict: ...
```

1. **Create a new client** in `server/app/llm/my_provider.py` implementing this protocol
2. **Wire it up** in `server/app/pipeline.py` based on a config setting

### Adding a new TTS/STT provider

Similar to LLM — the STT and TTS modules have implicit interfaces:

- **STT** needs to provide a streaming WebSocket connection that produces transcript events
- **TTS** needs to convert text to μ-law 8kHz audio (Twilio's required format)

---

## 8. Debugging

### Server logs

```bash
# Local dev — uvicorn logs to stdout
cd server && uv run uvicorn app.main:app --port 3000 --reload --log-level debug

# Fly.io
fly logs
```

### Interactive debugging

```bash
cd server
uv run python
>>> from app.config import settings
>>> print(settings.public_url)
```

### QA scripts

Manual testing scripts for individual services:

```bash
cd server
uv run python scripts/qa_deepgram.py     # Test STT with a sample audio file
uv run python scripts/qa_elevenlabs.py    # Test TTS and listen to output
uv run python scripts/qa_llm.py           # Test LLM with a sample prompt
```

### Common issues

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError` | Run `uv sync` in `server/` |
| Port 3000 already in use | `lsof -i :3000` and kill the process |
| Vite proxy 502 | Ensure the server is running on port 3000 |
| SQLite locked | Only one server instance should run at a time |
| `CALLME_API_KEY not set` | Create `.env` from `.env.example` and set a value |
| Tests fail with `asyncio` errors | Ensure `pytest-asyncio` is installed: `uv sync` |
| WebSocket errors in browser | Check that both server and Vite dev server are running |

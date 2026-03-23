# CallMe — AI Receptionist

An AI-powered phone receptionist that answers calls, transcribes speech in real time, and routes callers through configurable workflows.

See [docs/architecture.md](docs/architecture.md) for the full system design and [docs/stories.md](docs/stories.md) for the implementation plan.

---

## Quickstart (Docker)

The fastest way to get running — no Python or Node.js install required.

```bash
git clone https://github.com/your-org/callme.git
cd callme
cp .env.example .env.local     # Create env file (gitignored)
# Edit .env.local — set CALLME_API_KEY (any strong secret string)
docker compose up --build     # Start server + web UI
```

Open **http://localhost:8080** in your browser.

### First login

The admin account is created automatically on first startup. Log in with:

- **Email:** `admin@callme.local`
- **Password:** the value of `CALLME_API_KEY` from your `.env` file

After logging in, the setup wizard will guide you through entering API keys, configuring a phone number, and publishing your first workflow.

> **Tip:** You don't need to put service API keys in `.env` — enter them via the setup wizard instead. They are stored encrypted in the database.

### Service accounts needed

You'll need accounts with these services:

| Service | Sign up | Free tier |
|---------|---------|-----------|
| [Twilio](https://www.twilio.com/try-twilio) | twilio.com/try-twilio | Trial account with free credits |
| [Deepgram](https://console.deepgram.com/signup) | console.deepgram.com/signup | $200 free credit |
| [ElevenLabs](https://elevenlabs.io/sign-up) | elevenlabs.io/sign-up | 10k characters/month free |
| [OpenAI](https://platform.openai.com/signup) | platform.openai.com/signup | Pay-as-you-go (no free tier) |

### Platform keys vs. bring-your-own

CallMe supports two modes for API credentials:

- **Platform keys** — the server operator sets service API keys in `.env` (or the database). Users can toggle "Use platform keys" in the setup wizard so they don't need their own accounts.
- **Bring your own** — each user enters their own API keys via the setup wizard. Credentials are encrypted and isolated per user.

---

## Cloud deployment (Fly.io)

Deploy Pronto to the cloud with a single command. [Fly.io](https://fly.io) provides free HTTPS, persistent volumes for SQLite, and WebSocket support.

### Prerequisites

- [flyctl](https://fly.io/docs/flyctl/install/) installed: `brew install flyctl`
- A Fly.io account: `fly auth signup`

### First-time setup

```bash
./scripts/fly-setup.sh
```

This creates the app, a 1GB persistent volume, imports secrets from your `.env`, and deploys. Your app will be live at **https://callme-pronto.fly.dev**.

### Subsequent deploys

```bash
make deploy          # or: fly deploy --ha=false
```

### Configuration

Secrets are managed via `fly secrets`:

```bash
fly secrets set CALLME_API_KEY=your-key
fly secrets set OPENAI_API_KEY=sk-...
fly secrets list
```

The `PUBLIC_URL` is auto-detected from `FLY_APP_NAME` — no need to set it manually.

### Custom domain

```bash
fly certs add yourdomain.com
# Then add a CNAME record: yourdomain.com → callme-pronto.fly.dev
```

CORS automatically includes the resolved public URL.

### Useful commands

```bash
fly logs                    # Stream logs
fly ssh console             # SSH into the machine
fly status                  # Machine status
fly volumes list            # Check volume
```

---

## Local development

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js 18+ and npm

### 1. Environment variables

```bash
cp .env.example .env.local
# Set CALLME_API_KEY to any strong secret (also used as admin password)
# Optionally fill in service API keys or leave blank to enter via the UI
```

### 2. Server (Python + FastAPI)

```bash
cd server
uv sync                                             # Install deps (creates .venv)
uv run uvicorn app.main:app --port 3000 --reload    # Start dev server
```

The server runs at **http://localhost:3000**. Check health:

```bash
curl http://localhost:3000/health
# → {"status":"ok"}
```

### 3. Web UI (React + Vite)

```bash
cd web
npm install      # Install deps
npm run dev      # Start dev server → http://localhost:5173
```

The Vite dev server proxies `/api` and `/ws` requests to `localhost:3000` automatically (see `vite.config.ts`).

### Running tests

```bash
# Server (352 tests)
cd server
uv run pytest -v

# Web (119 tests)
cd web
npm test
```

### Project structure

```
callme/
├── server/           # Python / FastAPI backend
│   ├── app/          #   Application code
│   │   ├── api/      #     REST endpoints (auth, settings, workflows, …)
│   │   ├── db/       #     SQLModel models & session management
│   │   ├── llm/      #     LLM abstraction (OpenAI)
│   │   ├── stt/      #     Speech-to-text (Deepgram streaming)
│   │   ├── tts/      #     Text-to-speech (ElevenLabs)
│   │   ├── twilio/   #     Twilio webhook & media-stream handlers
│   │   └── workflow/  #    Workflow engine (state machine)
│   ├── schemas/      #   Example workflow JSON files
│   └── tests/        #   Pytest test suite
├── web/              # React / TypeScript / Vite frontend
│   └── src/
│       ├── components/  # Reusable UI components
│       ├── lib/         # API client, types, utilities
│       └── pages/       # Route pages (Setup, Dashboard, Builder, …)
├── docs/             # Architecture & story docs
├── fly/              # Fly.io deployment configs (nginx, supervisord)
├── scripts/          # Setup & utility scripts
├── .env.example      # Environment variable template
├── fly.toml          # Fly.io app configuration
└── docker-compose.yml
```

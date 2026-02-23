# CallMe — AI Receptionist

An AI-powered phone receptionist that answers calls, transcribes speech in real time, and routes callers through configurable workflows.

See [docs/architecture.md](docs/architecture.md) for the full system design and [docs/stories.md](docs/stories.md) for the implementation plan.

## Quickstart (Docker)

The fastest way to get running — no Python or Node.js install required.

```bash
git clone https://github.com/your-org/callme.git
cd callme
cp .env.example .env          # Create env file
# Edit .env — set CALLME_API_KEY (any secret string) and optionally CALLME_ENCRYPTION_KEY
docker compose up --build     # Start server + web UI
```

Open **http://localhost:8080** in your browser. The setup wizard will guide you through entering API keys, configuring a phone number, and publishing your first workflow.

> **Note:** API keys for Twilio, Deepgram, ElevenLabs, and OpenAI can be entered via the setup wizard — you don't need to put them in `.env`.

### Service accounts needed

You'll need free (or paid) accounts with these services:

| Service | Sign up | Free tier |
|---------|---------|-----------|
| [Twilio](https://www.twilio.com/try-twilio) | twilio.com/try-twilio | Trial account with free credits |
| [Deepgram](https://console.deepgram.com/signup) | console.deepgram.com/signup | $200 free credit |
| [ElevenLabs](https://elevenlabs.io/sign-up) | elevenlabs.io/sign-up | 10k characters/month free |
| [OpenAI](https://platform.openai.com/signup) | platform.openai.com/signup | Pay-as-you-go (no free tier) |

## Prerequisites (local dev)

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js 18+ and npm
- API keys for: Twilio, Deepgram, ElevenLabs, OpenAI (see `.env.example`)

## Setup (local dev)

### 1. Environment variables

```bash
cp .env.example .env
# Fill in your API keys in .env
```

### 2. Server (Python + FastAPI)

```bash
cd server
uv sync          # Install dependencies (creates .venv automatically)
uv run uvicorn app.main:app --port 3000 --reload   # Start dev server
```

The server runs at `http://localhost:3000`. Check health: `curl http://localhost:3000/health`

### 3. Web (React + TypeScript + Vite)

```bash
cd web
npm install      # Install dependencies
npm run dev      # Start dev server (default: http://localhost:5173)
```

### Running tests

```bash
# Server
cd server
uv run pytest -v

# Web
cd web
npm test
```

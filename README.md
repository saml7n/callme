# CallMe — AI Receptionist

An AI-powered phone receptionist that answers calls, transcribes speech in real time, and routes callers through configurable workflows.

See [docs/architecture.md](docs/architecture.md) for the full system design and [docs/stories.md](docs/stories.md) for the implementation plan.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js 18+ and npm
- API keys for: Twilio, Deepgram, ElevenLabs, OpenAI (see `.env.example`)

## Setup

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

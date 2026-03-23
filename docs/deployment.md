# Deployment Guide

This guide covers deploying CallMe/Pronto in three modes: Docker Compose (local), Fly.io (cloud), and bare-metal (no Docker).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Docker Compose (local)](#2-docker-compose-local)
3. [Fly.io (cloud)](#3-flyio-cloud)
4. [Twilio Configuration](#4-twilio-configuration)
5. [Health Checks](#5-health-checks)
6. [Secrets Management](#6-secrets-management)
7. [Monitoring & Operations](#7-monitoring--operations)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Prerequisites

### Service accounts

You need accounts with these external services:

| Service | Sign up | Required for |
|---------|---------|-------------|
| [Twilio](https://www.twilio.com/try-twilio) | twilio.com/try-twilio | Phone calls (telephony) |
| [Deepgram](https://console.deepgram.com/signup) | console.deepgram.com/signup | Speech-to-text |
| [ElevenLabs](https://elevenlabs.io/sign-up) | elevenlabs.io/sign-up | Text-to-speech |
| [OpenAI](https://platform.openai.com/signup) | platform.openai.com/signup | LLM reasoning |

Optional:
- **Google Cloud** — only needed if you want Google Calendar integration (requires OAuth client credentials)
- **ngrok** — only for local development with Twilio webhooks

### Environment file

```bash
cp .env.example .env.local
```

At minimum, set `CALLME_API_KEY` to any strong secret string. This becomes:
- The admin user's password
- The legacy API key for programmatic access

All other API keys can be entered later via the setup wizard in the UI — they are encrypted and stored in the database.

If you prefer to set them server-side (e.g., for a shared platform):

```env
CALLME_API_KEY=your-strong-secret

# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxx
TWILIO_AUTH_TOKEN=xxxxxx
TWILIO_PHONE_NUMBER=+441234567890

# AI services
DEEPGRAM_API_KEY=xxxxxx
ELEVENLABS_API_KEY=xxxxxx
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM   # Rachel (default)
OPENAI_API_KEY=sk-xxxxxx

# Optional
CALLME_FALLBACK_NUMBER=+441234567890   # Transfer-to number on errors
GOOGLE_CLIENT_ID=xxxxxx                # For Calendar integration
GOOGLE_CLIENT_SECRET=xxxxxx
```

---

## 2. Docker Compose (local)

### Start the stack

```bash
docker compose up --build
```

This starts:
- **server** — FastAPI on port 3000 (with SQLite volume)
- **web** — nginx serving React build on port 8080, proxying `/api/*` to server

Open **http://localhost:8080** and log in:
- Email: `admin@callme.local`
- Password: your `CALLME_API_KEY` value

### With ngrok tunnel

To receive Twilio webhooks locally, add an ngrok sidecar:

```bash
NGROK_AUTHTOKEN=your-token docker compose --profile tunnel up --build
```

This starts an ngrok container tunnelling to the server on port 3000. The server auto-detects the ngrok tunnel URL. Check the ngrok dashboard at http://localhost:4040.

### Data persistence

SQLite data is stored in the `callme-data` Docker volume. Data survives container restarts but is lost if you run `docker compose down -v`.

To back up:

```bash
docker compose exec server cp /app/data/callme.db /app/data/callme.db.bak
docker compose cp server:/app/data/callme.db.bak ./callme-backup.db
```

### Stopping / resetting

```bash
docker compose down             # Stop, keep data
docker compose down -v          # Stop, delete data volume
make clean                      # Remove DB, caches, volumes
make reset                      # Wipe and re-seed demo data
```

---

## 3. Fly.io (cloud)

### Prerequisites

```bash
brew install flyctl              # macOS
# or: curl -L https://fly.io/install.sh | sh
fly auth signup                  # Create account (if needed)
fly auth login
```

### First-time deployment

```bash
./scripts/fly-setup.sh
```

This script:
1. Creates the Fly app `callme-pronto` in the `lhr` (London) region
2. Creates a 1GB persistent volume (`callme_data`) for SQLite
3. Imports secrets from your `.env` file
4. Builds and deploys the multi-stage Docker image

Your app will be live at **https://callme-pronto.fly.dev**.

### What gets deployed

The `Dockerfile.fly` creates a single container running:

```
supervisord
├── nginx (port 8080)      # Serves React build + proxies API
└── uvicorn (port 3000)    # Runs FastAPI server
```

Fly's edge proxy handles TLS termination and routes to nginx on port 8080.

### Subsequent deploys

```bash
make deploy
# or: fly deploy --ha=false
```

The `--ha=false` flag prevents Fly from creating a second machine (which would require a second volume).

### Managing secrets

```bash
# Set individual secrets
fly secrets set CALLME_API_KEY=new-key
fly secrets set OPENAI_API_KEY=sk-...

# List all secrets (values are hidden)
fly secrets list

# Remove a secret
fly secrets unset SOME_KEY

# Re-import from .env
./scripts/fly-setup.sh    # re-running is idempotent
```

Secrets are injected as environment variables at runtime — never baked into the Docker image.

### Volume & data

SQLite lives on a persistent Fly volume mounted at `/app/data/callme.db`. Data survives deploys and machine restarts.

```bash
# Check volume
fly volumes list

# SSH in and inspect the database
fly ssh console
ls -la /app/data/
```

**Important:** The volume is tied to a specific region. If you scale to a new region, you'd need a new volume (and data would be empty there).

### Custom domain

```bash
fly certs add yourdomain.com
# Add a CNAME record: yourdomain.com → callme-pronto.fly.dev
```

CORS automatically includes the resolved public URL.

### Scaling

Current config (sufficient for PoC):

| Setting | Value |
|---------|-------|
| VM size | `shared-cpu-1x` |
| Memory | 512MB |
| Always on | Yes (`auto_stop_machines = false`) |
| Min machines | 1 |

To increase resources:

```bash
fly scale vm shared-cpu-2x --memory 1024
```

---

## 4. Twilio Configuration

### Webhook URL

After deployment, configure your Twilio phone number's webhook:

1. Go to [Twilio Console → Phone Numbers](https://console.twilio.com/us1/develop/phone-numbers/manage/incoming)
2. Select your number
3. Under **Voice Configuration**:
   - **A call comes in:** Webhook
   - **URL:** `https://callme-pronto.fly.dev/twilio/incoming` (or your custom domain)
   - **HTTP Method:** POST

For local development with ngrok:
- **URL:** `https://your-subdomain.ngrok-free.dev/twilio/incoming`

### Auth token vs API keys

CallMe uses the **Auth Token** for:
- Validating incoming webhook signatures (`X-Twilio-Signature`)
- Making REST API calls (checking phone number ownership, etc.)

Set it as `TWILIO_AUTH_TOKEN` in your secrets. API key pairs (`TWILIO_API_KEY_SID` / `TWILIO_API_KEY_SECRET`) are supported as an alternative but may have permission limitations depending on your Twilio account type.

### Signature validation

All incoming requests to `/twilio/incoming` are validated against the `X-Twilio-Signature` header. The server reconstructs the full public URL for validation using:

1. `PUBLIC_URL` env var (if set), OR
2. `FLY_APP_NAME` → `https://{app}.fly.dev` (auto-detected on Fly), OR
3. ngrok API auto-detection (local dev), OR
4. `http://localhost:3000` (fallback)

If you get 403 errors on incoming calls, check that the URL Twilio is calling matches the URL the server thinks it has. View the resolved URL in logs on startup.

---

## 5. Health Checks

### Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| `GET /health` | None | Fast liveness check — returns `{"status": "ok"}` instantly |
| `GET /health?detail=true` | None | Deep check — probes Twilio, Deepgram, ElevenLabs, OpenAI APIs |

### Fly health check config

The Fly machine runs a liveness probe every 15 seconds:

```toml
[[http_service.checks]]
  grace_period = "30s"
  interval = "15s"
  method = "GET"
  path = "/health"
  timeout = "10s"
```

The default `/health` (no `?detail=true`) is intentionally fast — it doesn't call external APIs. This prevents health-check flapping when external services are slow or rate-limited.

### Interpreting the detailed health response

```json
{
  "status": "degraded",
  "services": {
    "twilio": {"status": "ok"},
    "deepgram": {"status": "ok"},
    "elevenlabs": {"status": "error", "error": "401 Unauthorized"},
    "openai": {"status": "ok"}
  }
}
```

- `ok` — all services reachable
- `degraded` — one or more services failing, but server itself is running
- Individual service errors don't necessarily mean calls will fail (e.g., ElevenLabs health uses the user info endpoint which needs `user_read` permission — TTS still works)

---

## 6. Secrets Management

### Required secrets

| Secret | Required | Description |
|--------|----------|-------------|
| `CALLME_API_KEY` | **Yes** | Admin password + API key |
| `CALLME_ENCRYPTION_KEY` | Auto | Auto-generated Fernet key for DB encryption. Set explicitly to persist across clean deploys |
| `TWILIO_ACCOUNT_SID` | For calls | Twilio account SID (starts with `AC`) |
| `TWILIO_AUTH_TOKEN` | For calls | Twilio auth token (for webhook validation + REST API) |
| `TWILIO_PHONE_NUMBER` | For calls | Default phone number in E.164 format |
| `DEEPGRAM_API_KEY` | For calls | Deepgram API key |
| `ELEVENLABS_API_KEY` | For calls | ElevenLabs API key |
| `ELEVENLABS_VOICE_ID` | No | Default voice (falls back to Rachel) |
| `OPENAI_API_KEY` | For calls | OpenAI API key |
| `CALLME_FALLBACK_NUMBER` | No | Number to transfer to on errors |
| `GOOGLE_CLIENT_ID` | No | For Google Calendar OAuth |
| `GOOGLE_CLIENT_SECRET` | No | For Google Calendar OAuth |

### Platform keys vs user keys

API keys can be provided at two levels:

1. **Platform level** — set as environment variables / Fly secrets. Available to users who enable "Use platform keys" in their settings.
2. **User level** — entered via the setup wizard or settings page. Encrypted per-user in the database with Fernet.

Users with their own keys always use those first. The platform keys act as a fallback for users who don't have their own.

### Encryption key management

`CALLME_ENCRYPTION_KEY` is a Fernet key used to encrypt user credentials at rest. If not set, one is auto-generated on first startup and cached. However, on a clean deploy (new volume), a new key would be generated and old encrypted data becomes unreadable.

For production, generate and set it explicitly:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
fly secrets set CALLME_ENCRYPTION_KEY=the-generated-key
```

---

## 7. Monitoring & Operations

### Logs

```bash
# Fly.io
fly logs                        # Stream live logs
fly logs --no-tail              # Recent logs only

# Docker Compose
docker compose logs -f          # Stream all services
docker compose logs server      # Server only
```

### SSH access (Fly.io)

```bash
fly ssh console
# Inside the container:
ls /app/data/                   # Check SQLite DB
cat /var/log/supervisor/*.log   # supervisord logs
supervisorctl status            # Check nginx + uvicorn status
```

### Database access

```bash
# Fly.io
fly ssh console
sqlite3 /app/data/callme.db ".tables"
sqlite3 /app/data/callme.db "SELECT id, email FROM user;"

# Local
sqlite3 server/callme.db ".tables"
```

### Restarting services

```bash
# Full machine restart
fly machines restart

# Inside SSH — restart individual processes
fly ssh console
supervisorctl restart uvicorn
supervisorctl restart nginx
```

### Demo data

The `SEED_DEMO=true` environment variable (set by default on Fly) seeds demo data on startup:
- Admin user (`demo@callme.ai` / `CALLME_API_KEY` password)
- Sample "Simple Receptionist" workflow
- 5 fake historical calls with transcripts

To re-seed or reset:

```bash
# Via API (requires auth)
curl -X POST https://callme-pronto.fly.dev/api/admin/reset \
  -H "Authorization: Bearer YOUR_JWT"

# Via Makefile (local)
make reset
make seed
```

---

## 8. Troubleshooting

### Incoming calls return 403

**Cause:** Twilio webhook signature validation is failing.

**Fix:**
1. Ensure `TWILIO_AUTH_TOKEN` is set correctly in your secrets
2. Ensure the webhook URL in Twilio Console exactly matches what the server resolves (check startup logs for "Public URL resolved to: ...")
3. If using a custom domain, ensure `PUBLIC_URL` is set to `https://yourdomain.com`

### Health check flapping on Fly

**Cause:** The `?detail=true` health check calls external APIs which may time out.

**Fix:** Fly's health check hits `/health` (not `/health?detail=true`), which is a fast liveness check. If it still flaps:
1. Increase the timeout in `fly.toml`: `timeout = "10s"`
2. Check the machine has enough memory: `fly scale show`

### Calls connect but no audio / no response

**Cause:** Missing or invalid API keys for Deepgram, OpenAI, or ElevenLabs.

**Fix:**
1. Check `GET /health?detail=true` for service status
2. Verify secrets are set: `fly secrets list`
3. Check logs for specific errors: `fly logs`

### WebSocket connections fail

**Cause:** nginx not upgrading connections properly.

**Fix:** The `fly/nginx.conf` includes WebSocket upgrade headers for `/twilio/*` and `/ws/*` paths. If using a custom reverse proxy, ensure it passes:

```
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

### "No active workflow" error on calls

**Cause:** No workflow is published and assigned to the phone number.

**Fix:**
1. Log in and go to the workflow builder
2. Create or edit a workflow
3. Click "Publish" to make it active
4. Assign a phone number to it (Settings → Phone Numbers, or via the workflow detail page)

### Database locked errors

**Cause:** SQLite concurrent write contention.

**Fix:** This is rare with a single uvicorn process. If it occurs:
1. Ensure only one machine is running: `fly status`
2. Don't run `--ha=false` flag when deploying (this is already the default in the Makefile)
3. Consider WAL mode (already enabled by default in SQLite 3.x)

### Docker build fails

```bash
# Clear Docker cache
docker compose build --no-cache

# Ensure you're on the right Python / Node versions
docker compose run server python --version   # Should be 3.12+
docker compose run web node --version         # Should be 20+
```

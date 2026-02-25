# Security Audit — CallMe / Pronto

**Date:** 25 February 2026  
**Scope:** Full-stack review — server (FastAPI/Python), web (React), infrastructure (Docker / Fly.io)

---

## Executive Summary

The application has **solid foundational security** — JWT auth on all API routes, bcrypt password hashing, Fernet-encrypted credentials at rest, Twilio signature validation, and tenant isolation. However, several gaps exist that would allow a malicious actor to **burn API credits** or **wipe data** if the app is exposed publicly without fixes.

| Severity | Count | Summary |
|----------|-------|---------|
| **Critical** | 1 | Open registration allows unlimited account creation → credit abuse |
| **High** | 2 | Admin endpoints lack role-based access; no request rate limiting |
| **Medium** | 3 | WebSocket auth gap; demo credentials in source; JWT secret coupling |
| **Low** | 3 | Health endpoint info leak; CORS hardening; password policy |

---

## Authentication Architecture

### How It Works

1. **Registration** — `POST /api/auth/register` accepts email + password, creates a `User` row with bcrypt-hashed password, returns a signed JWT.
2. **Login** — `POST /api/auth/login` verifies email + password (or legacy API key), returns a JWT.
3. **JWT** — HMAC-SHA256 signed, 7-day expiry. Payload contains `sub` (user UUID), `email`, `name`.
4. **API Key** — `CALLME_API_KEY` env var acts as a superuser bypass. Sending it as a Bearer token authenticates as the admin user.
5. **Route protection** — Every API router uses `dependencies=[Depends(require_auth)]` at the router level, plus individual endpoints use `Depends(get_current_user)` to resolve the `User` object and enforce tenant isolation.

### Auth Flow Diagram

```
User enters email + password
    → POST /api/auth/login
    → Server verifies bcrypt hash
    → Server creates JWT (signed with CALLME_API_KEY as HMAC secret)
    → Returns { token, user }
    → Client stores token in localStorage
    → All subsequent requests: Authorization: Bearer <JWT>
    → Server decodes JWT → looks up User by UUID → scopes queries to user_id
```

---

## What's Properly Secured

### ✅ API Route Protection
All data-bearing routes require authentication:
- `workflows`, `calls`, `phone_numbers`, `integrations`, `settings`, `templates`, `admin` — all have `Depends(require_auth)` at the router level.
- Individual endpoints additionally use `Depends(get_current_user)` to resolve the user and enforce tenant isolation.

### ✅ Tenant Isolation
Every database query filters by `user_id`. User A cannot read, modify, or delete User B's workflows, calls, phone numbers, integrations, or settings.

### ✅ Password Hashing
Passwords are hashed with **bcrypt** (`bcrypt.hashpw` with auto-generated salt). Plaintext passwords are never stored.

### ✅ Credentials Encrypted at Rest
Integration configs (Twilio, Deepgram, ElevenLabs, OpenAI keys) and per-user settings are **Fernet-encrypted** (AES-128-CBC + HMAC-SHA256) in the database. The encryption key (`CALLME_ENCRYPTION_KEY`) is stored in `.env`, not in the database.

### ✅ Twilio Webhook Validation
`POST /twilio/incoming` validates the `X-Twilio-Signature` header using `twilio.request_validator.RequestValidator` when `twilio_auth_token` is configured. Invalid signatures return 403.

### ✅ CORS Restricted
CORS `allow_origins` is limited to:
- `localhost:5173` / `localhost:8080` (dev)
- The resolved `PUBLIC_URL` (production)
- Not a wildcard `*`

### ✅ Constant-Time Token Comparison
API key checks use `secrets.compare_digest()` to prevent timing attacks.

---

## Vulnerabilities

### 🔴 CRITICAL — Open Registration

**File:** `server/app/api/auth.py` — `POST /api/auth/register`

**Issue:** Anyone can create an unlimited number of accounts. Each account can trigger calls that consume **your** OpenAI, ElevenLabs, and Deepgram API credits, because service API keys are instance-wide (stored in .env or DB settings), not per-user.

**Impact:** An attacker could register throwaway accounts and make hundreds of calls, running up your third-party API bills with no spending cap at the application level.

**Remediation:**
- Disable registration entirely (single-tenant mode), or
- Gate registration behind an invite code / admin approval, or
- Require email verification before allowing API access, or
- Implement per-user usage quotas / spending caps

---

### 🔴 HIGH — Admin Endpoints Lack Role-Based Access

**File:** `server/app/api/admin.py`

**Issue:** The admin router uses `dependencies=[Depends(require_auth)]` — which means **any authenticated user** (not just the admin) can call:
- `POST /api/admin/reset` — **wipes all data** and re-seeds
- `POST /api/admin/seed` — seeds demo data

**Impact:** Any registered user can destroy all data for all users.

**Remediation:**
- Add an `is_admin` field to the `User` model
- Create a `require_admin` dependency that checks `user.is_admin`
- Apply it to the admin router

---

### 🔴 HIGH — No Request Rate Limiting

**Issue:** No rate limiting is configured on any endpoint — not on login, registration, or API calls. There is no middleware (e.g. `slowapi`, `fastapi-limiter`) and no Fly.io-level rate limiting.

**Impact:**
- **Brute force** — login endpoint can be hammered to guess passwords
- **Credential stuffing** — no lockout after failed attempts
- **Credit abuse** — authenticated users can make unlimited API calls to third-party services

**Remediation:**
- Add `slowapi` or similar middleware with per-IP limits on auth endpoints (e.g. 10 attempts/minute)
- Add per-user rate limits on call-triggering endpoints
- Set up billing alerts and hard caps on OpenAI, ElevenLabs, and Deepgram dashboards (defence in depth)

---

### 🟡 MEDIUM — Live Events WebSocket Has No Authentication

**File:** `server/app/api/live.py` — `GET /ws/calls/live`

**Issue:** The WebSocket endpoint accepts any connection without verifying JWT or API key. The client sends a `?token=` query parameter, but the server never validates it — it immediately calls `ws.accept()` and starts streaming events.

**Impact:** Anyone who knows the URL can connect and observe all live call events (call starts, transcripts, node transitions, call ends) in real time.

**Remediation:**
- Parse the `token` query parameter before accepting the WebSocket
- Validate it as a JWT or API key
- Reject the connection with `ws.close(code=4001)` if invalid

---

### 🟡 MEDIUM — Demo Credentials Are Public

**Issue:** The demo user credentials (`demo@callme.ai` / `demo1234`) are hardcoded in the source code (`server/app/seed.py`). Anyone reading the repo can log in when `SEED_DEMO=true`.

**Impact:** Low for private repos, but if the codebase is ever shared or open-sourced, anyone can log in to any deployment running in demo mode.

**Remediation:**
- Generate a random demo password at deploy time and log it once
- Or make demo credentials configurable via environment variables

---

### 🟡 MEDIUM — JWT Signing Secret = API Key

**File:** `server/app/auth.py` line `JWT_SECRET_KEY = _api_key`

**Issue:** The JWT HMAC signing secret is the same value as `CALLME_API_KEY`. If the API key is leaked (e.g. in logs, client-side code, shared `.env`), an attacker can:
1. Forge JWTs for any user UUID
2. Use the API key directly as a Bearer token (admin access)

**Impact:** Full account takeover for all users.

**Remediation:**
- Use a separate `JWT_SECRET` environment variable for token signing
- Keep `CALLME_API_KEY` only for the API key auth path

---

### 🟢 LOW — Health Endpoint Leaks Information

**File:** `server/app/main.py` — `GET /health`

**Issue:** The unauthenticated `/health` endpoint returns:
- `public_url` (the full domain)
- `demo_mode` (whether demo data is seeded)
- `services` (connectivity status of Twilio, Deepgram, ElevenLabs, OpenAI)

**Impact:** Gives attackers reconnaissance — they learn which services are configured and whether it's a demo instance.

**Remediation:**
- Return only `{"status": "ok"}` for unauthenticated health checks
- Move detailed service info behind auth (e.g. `GET /api/admin/health`)

---

### 🟢 LOW — Weak Password Policy

**File:** `server/app/api/auth.py` — `register()` endpoint

**Issue:** Only enforces minimum 6 characters. No complexity requirements (uppercase, numbers, symbols).

**Impact:** Users can set weak passwords like `123456`.

**Remediation:**
- Require minimum 8 characters with at least one number and one letter, or
- Integrate a password strength library like `zxcvbn`

---

### 🟢 LOW — CORS Could Be Tighter

**Issue:** CORS allows all methods (`allow_methods=["*"]`) and all headers (`allow_headers=["*"]`). While the origins list is restricted, the wildcard methods/headers are more permissive than necessary.

**Remediation:**
- Restrict to `["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]`
- Restrict headers to `["Authorization", "Content-Type"]`

---

## Infrastructure Security

### Fly.io Deployment

| Item | Status |
|------|--------|
| HTTPS enforced | ✅ `force_https = true` in `fly.toml` |
| Secrets management | ✅ API keys imported via `fly secrets import`, not baked into image |
| Persistent volume | ✅ SQLite DB on mounted volume, survives redeploys |
| Internal services | ✅ uvicorn bound to `127.0.0.1:3000`, not exposed directly |
| SSH access | ⚠️ Default Fly.io SSH access — restrict if not needed |

### Docker Compose (Local / QA)

| Item | Status |
|------|--------|
| `.env` in `.gitignore` | ✅ Secrets not committed |
| Internal network | ✅ Server container only exposed via nginx proxy |
| No secrets in Dockerfile | ✅ Env vars passed at runtime |

### Database

| Item | Status |
|------|--------|
| SQLite file | ⚠️ No encryption at the database level (relies on volume access controls) |
| Credentials in DB | ✅ Fernet-encrypted (`config_encrypted`, `value_encrypted` columns) |
| Backups | ❌ No automated backup strategy for the SQLite file |

---

## Secrets Inventory

The following secrets are required in production. Ensure all are set via `fly secrets` (not in code or Docker image):

| Secret | Purpose | Rotation |
|--------|---------|----------|
| `CALLME_API_KEY` | Admin auth + JWT signing | Rotate periodically; also rotates all JWTs |
| `CALLME_ENCRYPTION_KEY` | Fernet key for DB credential encryption | Cannot rotate without re-encrypting all values |
| `TWILIO_ACCOUNT_SID` | Twilio account identifier | N/A (identifier, not secret) |
| `TWILIO_API_KEY_SID` | Twilio API key ID | Rotate via Twilio console |
| `TWILIO_API_KEY_SECRET` | Twilio API key secret | Rotate via Twilio console |
| `DEEPGRAM_API_KEY` | Speech-to-text service | Rotate via Deepgram console |
| `ELEVENLABS_API_KEY` | Text-to-speech service | Rotate via ElevenLabs console |
| `OPENAI_API_KEY` | LLM service | Rotate via OpenAI console |
| `GOOGLE_CLIENT_ID` | Google OAuth (calendar) | Rotate via Google Cloud console |
| `GOOGLE_CLIENT_SECRET` | Google OAuth (calendar) | Rotate via Google Cloud console |

---

## Recommended Priority

| Priority | Action | Effort |
|----------|--------|--------|
| 1 | Disable open registration or add invite codes | Small |
| 2 | Add admin-role check to `/api/admin/*` endpoints | Small |
| 3 | Add WebSocket auth validation on `/ws/calls/live` | Small |
| 4 | Add rate limiting to auth endpoints (`slowapi`) | Medium |
| 5 | Set billing alerts on OpenAI, ElevenLabs, Deepgram | Small (external) |
| 6 | Separate JWT secret from API key | Small |
| 7 | Tighten health endpoint response | Small |
| 8 | Improve password policy | Small |
| 9 | Add SQLite backup strategy | Medium |

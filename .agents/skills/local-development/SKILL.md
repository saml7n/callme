# Local Development

## Quick Start
```bash
# Backend
cd ~/repos/callme/server
source ../.env.local
source /run/repo_secrets/saml7n/callme/.env.secrets  # Real API keys
uv run --python 3.12 uvicorn app.main:app --port 3000 --reload

# Frontend (separate terminal)
cd ~/repos/callme/web
npm run dev
```

- Web UI: http://localhost:5173 (proxies to localhost:3000)
- Health check: `curl http://localhost:3000/health`
- Admin login: `admin@callme.local` / password is the `CALLME_API_KEY` value

## Environment Variables
- `CALLME_API_KEY` — Admin password + legacy API key + JWT signing fallback
- `CALLME_INVITE_CODE` — Gates registration. If unset, registration disabled (403)
- `JWT_SECRET` — Separate JWT signing key (falls back to CALLME_API_KEY with warning)
- `DEMO_EMAIL` / `DEMO_PASSWORD` — Configurable demo user credentials
- `SEED_DEMO=true` — Creates demo user on startup

## Credentials
Always check `/run/repo_secrets/saml7n/callme/.env.secrets` for real API keys before claiming credentials are missing. The `.env.local` file only has non-secret config.

## Database
SQLite at `server/callme.db`. Delete and restart server to reset:
```bash
rm -f server/callme.db
```
Migrations run automatically on startup via `_migrate_existing_data()` in `server/app/db/session.py`.

## Common Issues
- `OperationalError: no such column` — Delete `callme.db` and restart. Migration adds missing columns on fresh start.
- `InsecureKeyLengthWarning` — CALLME_API_KEY is short. Normal for local dev.
- Port 3000 in use — Kill existing server: `lsof -ti:3000 | xargs kill`

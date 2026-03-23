# Testing

## Test Commands
```bash
# Server (405+ tests)
cd server && uv run --python 3.12 pytest -x -q          # Quick, stop on first failure
cd server && uv run --python 3.12 pytest -v              # Verbose
cd server && uv run --python 3.12 pytest -k "test_name"  # Specific test

# Web (121+ tests)
cd web && npm test

# Web build (TypeScript check)
cd web && npm run build
```

## Server Test Patterns
- Framework: pytest + pytest-asyncio (asyncio_mode = "auto")
- All external services mocked — no real API calls
- `db_session` fixture: in-memory SQLite, disables auth, creates test user
- `TEST_USER`: Fixed test user with `is_admin=True` (email: test@example.com)
- `TEST_API_KEY`: "test-api-key-for-tests"
- Security tests in `test_security_hardening.py` manually remove auth overrides in try/finally blocks

## QA Scripts (require real API keys)
```bash
cd server
source ../.env.local && source /run/repo_secrets/saml7n/callme/.env.secrets
uv run python scripts/qa_deepgram.py     # STT
uv run python scripts/qa_elevenlabs.py   # TTS
uv run python scripts/qa_llm.py          # LLM
uv run python scripts/qa_e2e_call.py     # Full synthetic caller (14+ assertions)
```

## API Testing (against running server)
```bash
# Health (unauthenticated)
curl -s http://localhost:3000/health
# Returns: {"status":"ok"}

# Health detail (authenticated)
curl -s -H "Authorization: Bearer $CALLME_API_KEY" 'http://localhost:3000/health?detail=true'

# Login and get JWT
curl -s -X POST http://localhost:3000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@callme.local","password":"'$CALLME_API_KEY'"}'

# WebSocket auth test
# Valid: ws://localhost:3000/ws/calls/live?token=<JWT_OR_API_KEY>
# Invalid: rejected with HTTP 403
```

## Key Testing Notes
- UAT is mandatory before any story is marked Done
- Run both server AND web tests before creating PRs
- Security-related tests need auth overrides removed to test real auth behavior

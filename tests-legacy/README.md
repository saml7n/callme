# tests-legacy/

These are the original callme test suites from before the parbaked-native
migration. They reference the pre-migration layout (`app.api.*`, `app.auth`,
`app.db.models.User`, `app.db.session`) and the QA scripts that talked to
the old supervisord + nginx Docker stack.

They are **not** wired into pytest. The active test suite is
`/tests/test_smoke.py` at the repo root — that's the contract for the
kernel-runtime boot.

## Port pattern

When porting a test from here into `tests/`:

1. **Imports**
   - `from app.auth import get_current_user` → `from parbaked import current_user as get_current_user`
   - `from app.auth import require_auth` → drop; rely on `Depends(get_current_user)` or `parbaked.current_user`
   - `from app.db.session import get_session` → `from parbaked import get_session`
   - `from app.db.models import User` → `from parbaked.auth.models import User`
   - `from app.db.models import <X>` → `from models import <X>`
   - `from app.api.<X>` → `from routes.api.<X>`
   - `from app.twilio.<X>` → `from routes.twilio.<X>` (note: `webhook.py` →
     `incoming.py`, `media_stream.py` → `media-stream.py`)
   - `from app.<X>` (e.g. `app.crypto`, `app.credentials`) → `from <X>`

2. **App bootstrapping**
   - Instead of constructing `FastAPI()` directly, drive `parbaked.runtime.create_app(...)`
     with `banner=False`, a tmp DB, and `ConsoleEmail(buffer=StringIO())`.
   - Add `runtime._reset_for_tests()` in setup/teardown so each test gets a
     fresh active instance.
   - `sys.path` must include the repo root so route files' bare imports
     (`from services import …`, `from models import …`) resolve.

3. **Auth**
   - The old fixture created a user with `password_hash=hash_password(...)`,
     then issued a JWT via `create_jwt(...)`. Replace with a signup +
     admin-approve + login flow against parbaked's `/auth/*` endpoints.
   - Helper sketch (see `tests/test_smoke.py` for the boot path):

     ```python
     # 1. Sign up
     client.post("/auth/signup", json={"email": ..., "password": ..., "name": ...})
     # 2. Approve as admin (parbaked.cli.admin.approve_user, or hit
     #    /auth/admin/approve with the admin password)
     # 3. Log in to get a JWT
     r = client.post("/auth/login", json={"email": ..., "password": ...})
     token = r.json()["token"]
     ```

4. **Routes**
   - `routes/api/<name>.py` mounts at `/api/<name>` automatically; the file
     must export `router: APIRouter` and route decorators are relative to
     that prefix (e.g. `@router.get("")` → `GET /api/<name>`).
   - `routes/api/live.py` mounts at `/api/live` (WS at `/api/live/ws`,
     transfer at `/api/live/{call_id}/transfer`).
   - `routes/twilio/incoming.py` mounts the webhook at `/twilio/incoming`.
   - `routes/twilio/media-stream.py` mounts the WS at `/twilio/media-stream`.

5. **Demo seed**
   - `app/seed.py` is gone. Tests that relied on `seed_demo_data()` must
     stage their fixtures directly via the models.

## What's here

- `server-tests/` — the original `server/tests/` tree (29 test files +
  `conftest.py` + `fixtures/`).
- `qa-scripts/` — the original `server/scripts/` end-to-end QA scripts
  (Deepgram, ElevenLabs, OpenAI, workflow, live call). Useful for manual
  smoke checks of the third-party integrations; they need updating to
  point at the new entrypoints before they'll run.

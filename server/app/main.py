import logging
import os

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.calls import router as calls_router
from app.api.integrations import router as integrations_router
from app.api.live import router as live_router
from app.api.phone_numbers import router as phone_numbers_router
from app.api.platform import router as platform_router
from app.api.settings import router as settings_router
from app.api.templates import router as templates_router
from app.api.workflows import router as workflows_router
from app.auth import init_api_key
from app.config import settings
from app.db.session import init_db
from app.public_url import get_public_url, resolve_public_url
from app.twilio.media_stream import router as media_stream_router
from app.twilio.webhook import router as webhook_router

# Configure root logger so our app.* loggers are visible
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    init_db()
    logging.getLogger(__name__).info("Database initialised")

    # Initialize API key (auto-generate if not set)
    api_key = init_api_key()
    logging.getLogger(__name__).info("Auth initialised (key configured: %s)", bool(api_key))

    # Ensure admin user exists and backfill orphaned rows
    try:
        from app.db.session import get_session as _get_session
        from app.auth import ensure_admin_user, backfill_user_ids
        session = next(_get_session())
        admin = ensure_admin_user(session)
        backfill_user_ids(session, admin.id)
    except Exception:
        logging.getLogger(__name__).warning("Could not run user backfill — will retry next startup.")

    # Check if settings are configured — warn but don't crash
    try:
        from app.db.session import get_session as _get_session
        from app.api.settings import get_all_settings
        session = next(_get_session())
        all_settings = get_all_settings(session)
        core_keys = ["twilio_account_sid", "deepgram_api_key", "elevenlabs_api_key", "openai_api_key"]
        missing = [k for k in core_keys if not all_settings.get(k)]
        if missing:
            logging.getLogger(__name__).warning(
                "Missing service settings: %s — run the setup wizard at /setup to configure them.",
                ", ".join(missing),
            )
    except Exception:
        logging.getLogger(__name__).warning("Could not check settings — database may not be initialised yet.")

    # Warm filler phrase cache (best-effort, non-blocking)
    try:
        from app.pipeline import warm_filler_cache
        await warm_filler_cache()
    except Exception:
        logging.getLogger(__name__).warning("Failed to warm filler cache — fillers disabled")

    # Resolve PUBLIC_URL (env → ngrok API → localhost fallback)
    try:
        public_url = await resolve_public_url()
        logging.getLogger(__name__).info("Resolved PUBLIC_URL: %s", public_url)
    except Exception:
        logging.getLogger(__name__).warning("PUBLIC_URL resolution failed — using localhost fallback")

    # Auto-seed demo data if SEED_DEMO=true
    if os.environ.get("SEED_DEMO", "").lower() in ("true", "1", "yes"):
        try:
            from app.seed import seed_demo_data
            seed_demo_data()
            logging.getLogger(__name__).info("Demo data seeded successfully")
        except Exception:
            logging.getLogger(__name__).warning("Demo seed failed", exc_info=True)

    yield


app = FastAPI(title="CallMe", description="AI Receptionist Server", lifespan=lifespan)


def _get_cors_origins() -> list[str]:
    """Build CORS allow_origins dynamically from PUBLIC_URL + dev ports."""
    origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:8080",   # Docker web (nginx)
        "http://127.0.0.1:8080",
    ]
    # Check both the cached resolve result and the env var (middleware is built
    # at import time before the async resolve runs).
    candidates = [get_public_url(), settings.public_url]
    for public in candidates:
        if public and public not in origins:
            origins.append(public)
            # Also allow the same host on port 8080 (Docker web via ngrok)
            from urllib.parse import urlparse
            parsed = urlparse(public)
            if parsed.scheme and parsed.hostname:
                alt = f"{parsed.scheme}://{parsed.hostname}:8080"
                if alt not in origins:
                    origins.append(alt)
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(webhook_router)
app.include_router(media_stream_router)
app.include_router(live_router)
app.include_router(workflows_router)
app.include_router(phone_numbers_router)
app.include_router(calls_router)
app.include_router(integrations_router)
app.include_router(settings_router)
app.include_router(templates_router)
app.include_router(platform_router)


@app.get("/health")
async def health_check() -> dict:
    """Enhanced health endpoint — reports service connectivity."""
    from app.health import check_all_services
    services = await check_all_services()
    all_ok = all(s["status"] == "ok" for s in services.values())
    demo_mode = os.environ.get("SEED_DEMO", "").lower() in ("true", "1", "yes")
    return {
        "status": "ok" if all_ok else "degraded",
        "public_url": get_public_url(),
        "demo_mode": demo_mode,
        "services": services,
    }

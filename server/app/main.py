import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.workflows import router as workflows_router
from app.twilio.media_stream import router as media_stream_router
from app.twilio.webhook import router as webhook_router

# Configure root logger so our app.* loggers are visible
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="CallMe", description="AI Receptionist Server")

# CORS — allow the Vite dev server during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)
app.include_router(media_stream_router)
app.include_router(workflows_router)


@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}

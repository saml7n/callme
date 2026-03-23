"""Admin API — demo reset and management endpoints.

Endpoints
---------
POST /api/admin/reset   — wipe all data and re-seed demo environment
POST /api/admin/seed    — seed demo data (additive, idempotent)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.post("/reset")
async def reset_demo() -> dict:
    """Wipe all user data and re-seed a fresh demo environment."""
    from app.seed import seed_demo_data, wipe_demo_data

    logger.info("Admin reset requested — wiping all data")
    wipe_demo_data()
    result = seed_demo_data()
    logger.info("Admin reset complete — demo re-seeded")
    return {"status": "ok", "message": "Demo data reset and re-seeded", **result}


@router.post("/seed")
async def seed_demo() -> dict:
    """Seed demo data (additive — skips existing records)."""
    from app.seed import seed_demo_data

    result = seed_demo_data()
    return {"status": "ok", "message": "Demo data seeded", **result}

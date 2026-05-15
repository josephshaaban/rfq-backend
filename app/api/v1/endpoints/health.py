import time
from fastapi import APIRouter, Request
from sqlalchemy import text
from app.settings import get_settings

APP_START_TIME = time.time()
router = APIRouter()
settings = get_settings()


@router.get("/health", summary="Health check")
async def health(request: Request):
    db_ok = False
    last_poll_run = None
    try:
        engine = request.app.state.engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            db_ok = True
            result = await conn.execute(text("SELECT MAX(started_at) FROM poll_runs"))
            row = result.fetchone()
            last_poll_run = row[0] if row and row[0] else None
    except Exception:
        pass

    return {
        "status": "ok" if db_ok else "degraded",
        "version": "1.0.0",
        "env": settings.app_env,
        "db": "reachable" if db_ok else "unreachable",
        "uptime_seconds": round(time.time() - APP_START_TIME, 1),
        "last_poll_run": last_poll_run,
    }

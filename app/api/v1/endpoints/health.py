from fastapi import APIRouter, Request
from sqlalchemy import text
from app.settings import get_settings

router = APIRouter()
settings = get_settings()


@router.get("/health", summary="Health check")
async def health(request: Request):
    db_ok = False
    try:
        engine = request.app.state.engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    return {
        "status": "ok" if db_ok else "degraded",
        "version": "1.0.0",
        "env": settings.app_env,
        "db": "reachable" if db_ok else "unreachable",
    }

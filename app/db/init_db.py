from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy import text
from app.logger import get_logger

logger = get_logger(__name__)

SCHEMA_PATH = Path(__file__).parent.parent.parent / "assets" / "db" / "sqlite_schema.sql"


async def create_tables(engine: AsyncEngine) -> None:
    """Execute the canonical schema SQL. All statements are idempotent (IF NOT EXISTS)."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")

    # Split on semicolons, skip empty statements and PRAGMA lines handled at connect time
    statements = [
        s.strip() for s in sql.split(";")
        if s.strip() and not s.strip().upper().startswith("PRAGMA")
    ]

    async with engine.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))

    logger.info("Database tables verified/created", extra={"schema": str(SCHEMA_PATH)})

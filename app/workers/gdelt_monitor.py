"""
GDELT monitoring worker.

Polls the GDELT Document 2.0 API for supply-chain disruption news,
normalises results into AlertEvent records, and broadcasts via WebSocket.

Deduplication is enforced by the unique index on (source_name, article_url).
IntegrityError on insert → mark as duplicate, do not raise.

Demo fallback: POST /api/v1/monitor/trigger fires a one-shot poll.
If GDELT is unreachable, use scripts/gdelt_seed.py to insert fixture alerts.
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AlertEvent, PollRun
from app.db.repositories.alert_repo import (
    create_poll_run,
    insert_alert_event,
    update_poll_run,
)
from app.db.session import get_session_factory
from app.api.v1.ws.connection_manager import manager
from app.settings import get_settings
from app.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
SOURCE_NAME = "gdelt"


class GdeltMonitor:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle (called from lifespan)
    # ------------------------------------------------------------------
    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="gdelt_monitor")
        logger.info(
            "GDELT monitor started",
            extra={"interval_seconds": settings.poll_interval_seconds, "query": settings.gdelt_query},
        )

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("GDELT monitor stopped")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                factory = get_session_factory()
                async with factory() as session:
                    await self._run_once(session)
                    await session.commit()
            except Exception:
                logger.exception("GDELT poll loop error")
            await asyncio.sleep(settings.poll_interval_seconds)

    # ------------------------------------------------------------------
    # One-shot trigger (for demo endpoint and background tasks)
    # ------------------------------------------------------------------
    async def schedule_once(self, background_tasks: BackgroundTasks, _session: AsyncSession) -> str:
        poll_run_id = str(uuid.uuid4())
        background_tasks.add_task(self._run_once_standalone, poll_run_id)
        return poll_run_id

    async def _run_once_standalone(self, poll_run_id: str) -> None:
        factory = get_session_factory()
        async with factory() as session:
            await self._run_once(session, poll_run_id)
            await session.commit()

    # ------------------------------------------------------------------
    # Core poll logic
    # ------------------------------------------------------------------
    async def _run_once(self, session: AsyncSession, poll_run_id: str | None = None) -> None:
        poll_run_id = poll_run_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        poll_run = PollRun(
            id=poll_run_id,
            source_name=SOURCE_NAME,
            query_text=settings.gdelt_query,
            run_status="started",
            started_at=now,
        )
        await create_poll_run(session, poll_run)
        await session.commit()

        logger.info("GDELT poll started", extra={"poll_run_id": poll_run_id})

        items_seen = 0
        alerts_created = 0
        error_message = None

        try:
            articles = await self._fetch_gdelt(settings.gdelt_query)
            items_seen = len(articles)

            for article in articles:
                created = await self._process_article(session, poll_run_id, article)
                if created:
                    alerts_created += 1

            status = "completed"
        except Exception as exc:
            logger.exception("GDELT fetch failed", extra={"poll_run_id": poll_run_id})
            status = "failed"
            error_message = str(exc)

        await update_poll_run(
            session,
            poll_run_id,
            status=status,
            items_seen=items_seen,
            alerts_created=alerts_created,
            completed_at=datetime.now(timezone.utc).isoformat(),
            error_message=error_message,
        )

        # Broadcast poll_run_complete to all WS clients
        await manager.broadcast(
            "poll_run_complete",
            {
                "poll_run_id": poll_run_id,
                "status": status,
                "items_seen": items_seen,
                "alerts_created": alerts_created,
            },
        )

        logger.info(
            "GDELT poll complete",
            extra={"poll_run_id": poll_run_id, "items_seen": items_seen, "alerts_created": alerts_created},
        )

    async def _fetch_gdelt(self, query: str) -> list[dict[str, Any]]:
        params = {
            "query": query,
            "mode": "artlist",
            "maxrecords": str(settings.gdelt_max_records),
            "format": "json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(GDELT_BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("articles", [])

    async def _process_article(
        self, session: AsyncSession, poll_run_id: str, article: dict[str, Any]
    ) -> bool:
        """Normalise a GDELT article and insert as AlertEvent. Returns True if newly created."""
        url = article.get("url", "")
        if not url:
            return False

        title = article.get("title") or article.get("url", "Untitled")
        published_at = article.get("seendate") or article.get("socialimage")
        matched_terms = [t for t in settings.gdelt_query.split() if len(t) > 3]

        alert = AlertEvent(
            id=str(uuid.uuid4()),
            poll_run_id=poll_run_id,
            source_name=SOURCE_NAME,
            source_item_id=article.get("url"),  # stable dedup key
            article_url=url,
            article_title=title[:500],
            published_at=published_at,
            matched_terms_json=json.dumps(matched_terms),
            payload_json=json.dumps(article),
            alert_status="detected",
            detected_at=datetime.now(timezone.utc).isoformat(),
        )

        _, created = await insert_alert_event(session, alert)

        if created:
            await manager.broadcast(
                "alert_detected",
                {
                    "alert_id": alert.id,
                    "title": title,
                    "url": url,
                    "matched_terms": matched_terms,
                },
                correlation_id=poll_run_id,
            )

        return created

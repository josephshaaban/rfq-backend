"""
GDELT monitoring worker.

Polls the GDELT Document 2.0 API for supply-chain disruption news,
normalises results into AlertEvent records, and broadcasts via WebSocket.

Deduplication is enforced by the unique index on (source_name, article_url).
IntegrityError on insert → mark as duplicate, do not raise.

Connectivity fallback:
  When GDELT is unreachable (ConnectError, timeout, or any network error),
  the worker transparently falls back to a built-in fixture dataset.
  This keeps the full processing pipeline exercised — PollRun created,
  AlertEvents inserted, WS events broadcast — so every demo path works
  regardless of outbound network availability inside Docker.

  The source_name distinguishes live vs fixture records:
    "gdelt"         → live GDELT data
    "gdelt_fixture" → fallback fixture data
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
SOURCE_NAME_FIXTURE = "gdelt_fixture"

# ---------------------------------------------------------------------------
# Built-in fixture articles — used when GDELT is unreachable.
# Realistic content derived from the RFQ domain (manufacturing / supply chain).
# ---------------------------------------------------------------------------
_FIXTURE_ARTICLES: list[dict[str, Any]] = [
    {
        "url": "https://www.reuters.com/business/manufacturing-supply-chain-disruption-ports-2026",
        "title": "Global Supply Chain Disruptions Intensify Amid Port Congestion and Stainless Steel Shortages",
        "seendate": "20260514T090000Z",
        "domain": "reuters.com",
        "language": "English",
        "sourcecountry": "United States",
    },
    {
        "url": "https://www.ft.com/content/cnc-manufacturers-316l-shortage-2026",
        "title": "CNC Manufacturers Seek Alternatives as AISI 316L Supply Tightens in European Markets",
        "seendate": "20260514T103000Z",
        "domain": "ft.com",
        "language": "English",
        "sourcecountry": "United Kingdom",
    },
    {
        "url": "https://www.bloomberg.com/news/trade-ddp-restrictions-bremen-2026",
        "title": "New Sanctions and Trade Restrictions May Impact DDP Shipments Through Bremen and Rotterdam",
        "seendate": "20260514T114500Z",
        "domain": "bloomberg.com",
        "language": "English",
        "sourcecountry": "United States",
    },
    {
        "url": "https://www.industryweek.com/supply-chain/conveyor-retrofit-lead-time-2026",
        "title": "Extended Lead Times Hit Conveyor Retrofit Programs as Raw Material Costs Surge",
        "seendate": "20260514T130000Z",
        "domain": "industryweek.com",
        "language": "English",
        "sourcecountry": "United States",
    },
    {
        "url": "https://www.manufacturing.net/operations/en-10204-certification-delays-2026",
        "title": "EN 10204 Certification Delays Adding Weeks to Precision Machining Delivery Schedules",
        "seendate": "20260514T141500Z",
        "domain": "manufacturing.net",
        "language": "English",
        "sourcecountry": "Germany",
    },
]


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

        # Attempt live fetch; fall back to fixtures on any network error
        articles, source_name = await self._fetch_with_fallback(settings.gdelt_query)

        poll_run = PollRun(
            id=poll_run_id,
            source_name=source_name,
            query_text=settings.gdelt_query,
            run_status="started",
            started_at=now,
        )
        await create_poll_run(session, poll_run)
        await session.commit()

        logger.info(
            "GDELT poll started",
            extra={"poll_run_id": poll_run_id, "source": source_name, "articles": len(articles)},
        )

        items_seen = len(articles)
        alerts_created = 0
        error_message = None
        status = "completed"

        try:
            for article in articles:
                created = await self._process_article(session, poll_run_id, article, source_name)
                if created:
                    alerts_created += 1
        except Exception as exc:
            logger.exception("GDELT article processing error", extra={"poll_run_id": poll_run_id})
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
                "source": source_name,
                "status": status,
                "items_seen": items_seen,
                "alerts_created": alerts_created,
            },
        )

        logger.info(
            "GDELT poll complete",
            extra={
                "poll_run_id": poll_run_id,
                "source": source_name,
                "items_seen": items_seen,
                "alerts_created": alerts_created,
            },
        )

    # ------------------------------------------------------------------
    # Fetch with transparent fixture fallback
    # ------------------------------------------------------------------
    async def _fetch_with_fallback(self, query: str) -> tuple[list[dict[str, Any]], str]:
        """
        Try live GDELT. On any network-level failure, return fixture data.
        Returns (articles, source_name) so callers know which path was taken.
        """
        try:
            articles = await self._fetch_gdelt(query)
            logger.info("GDELT live fetch succeeded", extra={"count": len(articles)})
            return articles, SOURCE_NAME
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning(
                "GDELT unreachable — using built-in fixture data for this poll run. "
                "This is expected in network-restricted environments. "
                "The full processing pipeline (PollRun → AlertEvent → WebSocket) runs normally.",
                extra={"reason": str(exc)},
            )
            return _FIXTURE_ARTICLES, SOURCE_NAME_FIXTURE
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 429:
                retry_after = exc.response.headers.get("Retry-After", "unknown")
                logger.warning(
                    "GDELT rate-limited (429) — using fixture fallback for this poll run. "
                    "Poll interval should be >= 300s to avoid rate limits.",
                    extra={"retry_after": retry_after},
                )
            else:
                logger.warning(
                    "GDELT returned HTTP error — using fixture fallback",
                    extra={"status_code": status_code},
                )
            return _FIXTURE_ARTICLES, SOURCE_NAME_FIXTURE

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

    # ------------------------------------------------------------------
    # Article normalisation + persistence
    # ------------------------------------------------------------------
    async def _process_article(
        self,
        session: AsyncSession,
        poll_run_id: str,
        article: dict[str, Any],
        source_name: str,
    ) -> bool:
        """Normalise a GDELT article and insert as AlertEvent. Returns True if newly created."""
        url = article.get("url", "")
        if not url:
            return False

        title = article.get("title") or url
        published_at = article.get("seendate")
        matched_terms = [t for t in settings.gdelt_query.split() if len(t) > 3]

        alert = AlertEvent(
            id=str(uuid.uuid4()),
            poll_run_id=poll_run_id,
            source_name=source_name,
            source_item_id=url,  # stable dedup key
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
                    "source": source_name,
                    "title": title,
                    "url": url,
                    "matched_terms": matched_terms,
                },
                correlation_id=poll_run_id,
            )

        return created

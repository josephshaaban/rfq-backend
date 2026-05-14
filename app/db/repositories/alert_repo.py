from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.db.models import AlertEvent, PollRun
from app.logger import get_logger

logger = get_logger(__name__)


async def create_poll_run(session: AsyncSession, poll_run: PollRun) -> PollRun:
    session.add(poll_run)
    await session.flush()
    return poll_run


async def update_poll_run(
    session: AsyncSession,
    poll_run_id: str,
    *,
    status: str,
    items_seen: int,
    alerts_created: int,
    completed_at: str,
    error_message: str | None = None,
) -> None:
    result = await session.execute(select(PollRun).where(PollRun.id == poll_run_id))
    run = result.scalar_one_or_none()
    if run:
        run.run_status = status
        run.items_seen = items_seen
        run.alerts_created = alerts_created
        run.completed_at = completed_at
        run.error_message = error_message
        await session.flush()


async def insert_alert_event(
    session: AsyncSession, alert: AlertEvent
) -> tuple[AlertEvent, bool]:
    """
    Insert an alert event.  Returns (alert, created).
    created=False means the URL already existed (duplicate).
    The unique index on (source_name, article_url) is the deduplication guard.
    """
    try:
        session.add(alert)
        await session.flush()
        return alert, True
    except IntegrityError:
        await session.rollback()
        logger.info(
            "Duplicate alert skipped",
            extra={"url": alert.article_url, "source": alert.source_name},
        )
        alert.alert_status = "duplicate"
        return alert, False


async def list_alert_events(
    session: AsyncSession,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
) -> list[AlertEvent]:
    q = select(AlertEvent).order_by(AlertEvent.detected_at.desc()).limit(limit).offset(offset)
    if status:
        q = q.where(AlertEvent.alert_status == status)
    result = await session.execute(q)
    return list(result.scalars().all())


async def list_poll_runs(session: AsyncSession, limit: int = 20) -> list[PollRun]:
    result = await session.execute(
        select(PollRun).order_by(PollRun.started_at.desc()).limit(limit)
    )
    return list(result.scalars().all())

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.api.v1.models.alert_models import MonitorTriggerResponse
from app.workers.gdelt_monitor import GdeltMonitor

router = APIRouter()


@router.post(
    "/monitor/trigger",
    response_model=MonitorTriggerResponse,
    summary="Manually trigger a GDELT poll run (useful for demo and testing)",
)
async def trigger_monitor(
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """
    Fires a one-shot GDELT poll in the background.
    Returns immediately with the poll_run_id — check GET /api/v1/monitor/runs for results.
    """
    monitor = GdeltMonitor()
    poll_run_id = await monitor.schedule_once(background_tasks, session)
    return MonitorTriggerResponse(
        poll_run_id=poll_run_id,
        status="triggered",
        message=f"Poll run {poll_run_id} started. Check GET /api/v1/monitor/runs for results.",
    )

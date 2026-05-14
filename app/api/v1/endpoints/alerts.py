from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.repositories import alert_repo
from app.api.v1.models.alert_models import (
    AlertsListResponse,
    AlertEventResponse,
    PollRunResponse,
)

router = APIRouter()


@router.get(
    "/alerts",
    response_model=AlertsListResponse,
    summary="List generated alert events",
)
async def list_alerts(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, description="Filter by alert_status"),
    session: AsyncSession = Depends(get_session),
):
    alerts = await alert_repo.list_alert_events(session, limit=limit, offset=offset, status=status)
    return AlertsListResponse(
        count=len(alerts),
        alerts=[AlertEventResponse.model_validate(a) for a in alerts],
    )


@router.get(
    "/monitor/runs",
    response_model=list[PollRunResponse],
    summary="List GDELT poll run history",
)
async def list_poll_runs(
    limit: int = Query(default=20, le=100),
    session: AsyncSession = Depends(get_session),
):
    runs = await alert_repo.list_poll_runs(session, limit=limit)
    return [PollRunResponse.model_validate(r) for r in runs]

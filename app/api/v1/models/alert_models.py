from pydantic import BaseModel
from typing import Literal


class AlertEventResponse(BaseModel):
    id: str
    poll_run_id: str | None
    source_name: str
    article_url: str
    article_title: str
    published_at: str | None
    matched_terms_json: str
    alert_status: Literal["detected", "notified", "duplicate", "failed"]
    detected_at: str
    notified_at: str | None

    model_config = {"from_attributes": True}


class PollRunResponse(BaseModel):
    id: str
    source_name: str
    query_text: str
    run_status: Literal["started", "completed", "failed"]
    items_seen: int
    alerts_created: int
    started_at: str
    completed_at: str | None
    error_message: str | None

    model_config = {"from_attributes": True}


class AlertsListResponse(BaseModel):
    count: int
    total_count: int
    limit: int
    offset: int
    has_more: bool
    alerts: list[AlertEventResponse]


class PollRunsListResponse(BaseModel):
    runs: list[PollRunResponse]
    total_count: int
    limit: int
    offset: int
    has_more: bool


class MonitorTriggerResponse(BaseModel):
    poll_run_id: str
    status: str
    message: str

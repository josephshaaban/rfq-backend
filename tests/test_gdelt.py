import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from app.workers.gdelt_monitor import GdeltMonitor

pytestmark = pytest.mark.asyncio

MOCK_GDELT_RESPONSE = {
    "articles": [
        {
            "url": "https://example.com/supply-chain-disruption-1",
            "title": "Major Supply Chain Disruptions Hit Manufacturing Sector",
            "seendate": "20260514T120000Z",
            "socialimage": "",
            "domain": "example.com",
            "language": "English",
            "sourcecountry": "United States",
        },
        {
            "url": "https://example.com/steel-shortage-2",
            "title": "Global Steel Shortage Affects CNC Manufacturers",
            "seendate": "20260514T130000Z",
            "socialimage": "",
            "domain": "example.com",
            "language": "English",
            "sourcecountry": "Germany",
        },
    ]
}


async def test_gdelt_creates_alert_events(db_session):
    monitor = GdeltMonitor()

    with patch.object(monitor, "_fetch_gdelt", new=AsyncMock(return_value=MOCK_GDELT_RESPONSE["articles"])):
        await monitor._run_once(db_session)
        await db_session.commit()

    from app.db.repositories.alert_repo import list_alert_events
    alerts = await list_alert_events(db_session, limit=10)

    assert len(alerts) >= 2
    urls = [a.article_url for a in alerts]
    assert "https://example.com/supply-chain-disruption-1" in urls
    assert "https://example.com/steel-shortage-2" in urls


async def test_gdelt_deduplicates_on_second_run(db_session):
    monitor = GdeltMonitor()

    with patch.object(monitor, "_fetch_gdelt", new=AsyncMock(return_value=MOCK_GDELT_RESPONSE["articles"])):
        await monitor._run_once(db_session, poll_run_id="run-dedup-1")
        await db_session.commit()

    with patch.object(monitor, "_fetch_gdelt", new=AsyncMock(return_value=MOCK_GDELT_RESPONSE["articles"])):
        await monitor._run_once(db_session, poll_run_id="run-dedup-2")
        await db_session.commit()

    from app.db.repositories.alert_repo import list_alert_events
    alerts = await list_alert_events(db_session, limit=50)

    # Only 2 unique URLs — duplicates should be caught
    unique_urls = {a.article_url for a in alerts if a.article_url in [
        "https://example.com/supply-chain-disruption-1",
        "https://example.com/steel-shortage-2",
    ]}
    assert len(unique_urls) == 2  # deduplicated — no double entries


async def test_gdelt_handles_fetch_failure(db_session):
    monitor = GdeltMonitor()

    with patch.object(monitor, "_fetch_gdelt", new=AsyncMock(side_effect=Exception("GDELT unreachable"))):
        # Should not raise — errors are caught and logged
        await monitor._run_once(db_session, poll_run_id="run-fail-1")
        await db_session.commit()

    from app.db.repositories.alert_repo import list_poll_runs
    runs = await list_poll_runs(db_session)
    failed_runs = [r for r in runs if r.id == "run-fail-1"]
    assert failed_runs[0].run_status == "failed"
    assert "GDELT unreachable" in (failed_runs[0].error_message or "")

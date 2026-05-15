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

    # Patch _fetch_with_fallback — the single entry point after our refactor
    with patch.object(
        monitor,
        "_fetch_with_fallback",
        new=AsyncMock(return_value=(MOCK_GDELT_RESPONSE["articles"], "gdelt")),
    ):
        await monitor._run_once(db_session, poll_run_id="run-create-1")
        await db_session.commit()

    from app.db.repositories.alert_repo import list_alert_events
    alerts = await list_alert_events(db_session, limit=10)

    assert len(alerts) >= 2
    urls = [a.article_url for a in alerts]
    assert "https://example.com/supply-chain-disruption-1" in urls
    assert "https://example.com/steel-shortage-2" in urls


async def test_gdelt_deduplicates_on_second_run(db_session):
    monitor = GdeltMonitor()

    with patch.object(
        monitor,
        "_fetch_with_fallback",
        new=AsyncMock(return_value=(MOCK_GDELT_RESPONSE["articles"], "gdelt")),
    ):
        await monitor._run_once(db_session, poll_run_id="run-dedup-1")
        await db_session.commit()

    with patch.object(
        monitor,
        "_fetch_with_fallback",
        new=AsyncMock(return_value=(MOCK_GDELT_RESPONSE["articles"], "gdelt")),
    ):
        await monitor._run_once(db_session, poll_run_id="run-dedup-2")
        await db_session.commit()

    from app.db.repositories.alert_repo import list_alert_events
    alerts = await list_alert_events(db_session, limit=50)

    # Unique URLs — the unique index on (source_name, article_url) prevents duplicates
    target_urls = {
        "https://example.com/supply-chain-disruption-1",
        "https://example.com/steel-shortage-2",
    }
    unique_urls = {a.article_url for a in alerts if a.article_url in target_urls}
    assert len(unique_urls) == 2  # deduplicated — no double entries


async def test_gdelt_falls_back_to_fixtures_on_connect_error(db_session):
    """ConnectError must NOT propagate — worker uses fixture data transparently."""
    import httpx
    monitor = GdeltMonitor()

    with patch.object(
        monitor,
        "_fetch_gdelt",
        new=AsyncMock(side_effect=httpx.ConnectError("All connection attempts failed")),
    ):
        articles, source = await monitor._fetch_with_fallback("manufacturing supply chain")

    assert source == "gdelt_fixture"
    assert len(articles) > 0


async def test_gdelt_fixture_fallback_creates_alerts(db_session):
    """End-to-end: even when GDELT is unreachable, alerts are persisted and WS fires."""
    import httpx
    monitor = GdeltMonitor()

    with patch.object(
        monitor,
        "_fetch_gdelt",
        new=AsyncMock(side_effect=httpx.ConnectError("blocked")),
    ):
        await monitor._run_once(db_session, poll_run_id="run-fixture-1")
        await db_session.commit()

    from app.db.repositories.alert_repo import list_alert_events, list_poll_runs
    alerts = await list_alert_events(db_session, limit=20)
    runs = await list_poll_runs(db_session)

    fixture_alerts = [a for a in alerts if a.source_name == "gdelt_fixture"]
    assert len(fixture_alerts) >= 5  # all 5 built-in fixtures inserted

    fixture_run = next((r for r in runs if r.id == "run-fixture-1"), None)
    assert fixture_run is not None
    assert fixture_run.run_status == "completed"  # not "failed"
    assert fixture_run.source_name == "gdelt_fixture"

#!/usr/bin/env python3
"""
Seed script for demo fallback when GDELT API is unreachable.

Usage:
    python scripts/gdelt_seed.py

Inserts 3 realistic fixture alert events so the demo can proceed
without live GDELT connectivity.
"""
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.settings import get_settings
from app.db.session import init_engine, get_session_factory
from app.db.init_db import create_tables
from app.db.models import PollRun, AlertEvent

settings = get_settings()

FIXTURE_ARTICLES = [
    {
        "url": "https://www.reuters.com/business/supply-chain-disruption-fixture-1",
        "title": "Global Supply Chain Disruptions Intensify Amid Port Congestion",
        "published_at": "2026-05-14T09:00:00Z",
        "matched_terms": ["manufacturing", "supply", "chain", "disruption"],
    },
    {
        "url": "https://www.ft.com/content/stainless-steel-shortage-fixture-2",
        "title": "Stainless Steel Shortage Forces CNC Manufacturers to Seek Alternatives",
        "published_at": "2026-05-14T10:30:00Z",
        "matched_terms": ["manufacturing", "supply", "disruption"],
    },
    {
        "url": "https://www.bloomberg.com/news/trade-restrictions-fixture-3",
        "title": "New Trade Restrictions May Impact DDP Shipments to European Ports",
        "published_at": "2026-05-14T11:45:00Z",
        "matched_terms": ["supply", "chain", "disruption"],
    },
]


async def seed():
    engine = await init_engine(settings.sqlite_db_path)
    await create_tables(engine)
    factory = get_session_factory()

    async with factory() as session:
        now = datetime.now(timezone.utc).isoformat()
        poll_run_id = str(uuid.uuid4())

        poll_run = PollRun(
            id=poll_run_id,
            source_name="gdelt_fixture",
            query_text=settings.gdelt_query,
            run_status="completed",
            items_seen=len(FIXTURE_ARTICLES),
            alerts_created=len(FIXTURE_ARTICLES),
            started_at=now,
            completed_at=now,
        )
        session.add(poll_run)

        for article in FIXTURE_ARTICLES:
            alert = AlertEvent(
                id=str(uuid.uuid4()),
                poll_run_id=poll_run_id,
                source_name="gdelt_fixture",
                source_item_id=article["url"],
                article_url=article["url"],
                article_title=article["title"],
                published_at=article["published_at"],
                matched_terms_json=json.dumps(article["matched_terms"]),
                payload_json=json.dumps(article),
                alert_status="detected",
                detected_at=now,
            )
            session.add(alert)

        await session.commit()
        print(f"✓ Seeded {len(FIXTURE_ARTICLES)} fixture alerts (poll_run_id: {poll_run_id})")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())

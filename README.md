# RFQ Backend Platform

A FastAPI service demonstrating three communication patterns:
REST document ingestion with AI extraction, WebSocket live events, and GDELT supply-chain monitoring.

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- Python 3.12+ (for local run without Docker)

### Start with Docker (recommended)

```bash
cp .env .env.local   # already set to safe defaults
docker compose up --build
```

API available at: http://localhost:8000  
Swagger UI: http://localhost:8000/docs  
WebSocket test page: http://localhost:8000/ws-test

---

## Local Run (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.server:app --reload --port 8000
```

---

## Run Tests

```bash
pip install -r requirements.txt
pytest -v
```

---

## Full Demo (Interview Panel)

```bash
# 1. Start the service
docker compose up --build

# 2. Run the automated demo script (in another terminal)
bash scripts/demo.sh
```

---

## REST API — Exact Commands

### Health check
```bash
curl http://localhost:8000/health
```

### Upload the sample RFQ document
```bash
curl -X POST http://localhost:8000/api/v1/documents \
  -F "file=@assets/input/manufacturing_rfq_sample.txt;type=text/plain"
# Returns: {"document_id": "<uuid>", "status": "accepted", ...}
```

### Get document status
```bash
curl http://localhost:8000/api/v1/documents/<document_id>
```

### Get extracted keywords
```bash
curl http://localhost:8000/api/v1/documents/<document_id>/keywords
```

### Get extracted entities
```bash
curl http://localhost:8000/api/v1/documents/<document_id>/entities
```

### Validation failure example (empty file upload)
```bash
curl -X POST http://localhost:8000/api/v1/documents \
  -F "file=@/dev/null;type=text/plain"
# Returns: 422 {"detail": {"detail": "Uploaded file is empty", "type": "validation_error"}}
```

### Duplicate upload (idempotency check)
```bash
# Upload the same file twice — second call returns 409 Conflict
curl -X POST http://localhost:8000/api/v1/documents \
  -F "file=@assets/input/manufacturing_rfq_sample.txt;type=text/plain"
```

---

## WebSocket — Exact Steps

### Connect via browser
1. Open http://localhost:8000/ws-test
2. URL is pre-filled: `ws://localhost:8000/api/v1/ws/events`
3. Click **Connect** → you'll see `{"event": "connected", ...}`
4. Upload a document (curl command above) → watch `extraction_complete` event appear
5. Trigger a GDELT poll → watch `alert_detected` events appear

### Connect via CLI
```bash
# Install wscat: npm install -g wscat
wscat -c ws://localhost:8000/api/v1/ws/events
```

### WebSocket event shapes

**On connect:**
```json
{"event": "connected", "client_id": "...", "message": "Connected to RFQ event stream."}
```

**After document extraction:**
```json
{"event": "extraction_complete", "document_id": "...", "keyword_count": 9, "entity_count": 7, "ts": "..."}
```

**After GDELT alert:**
```json
{"event": "alert_detected", "alert_id": "...", "title": "...", "url": "...", "matched_terms": [...], "ts": "..."}
```

---

## GDELT Monitoring — Exact Steps

### One-shot trigger (for demo)
```bash
curl -X POST http://localhost:8000/api/v1/monitor/trigger
# Returns: {"poll_run_id": "<uuid>", "status": "triggered", ...}
```

### Check poll run results
```bash
curl http://localhost:8000/api/v1/monitor/runs
```

### View alert events created
```bash
curl http://localhost:8000/api/v1/alerts
```

### If GDELT is unreachable (demo fallback)
```bash
# Seed 3 realistic fixture alerts from local fixtures
python scripts/gdelt_seed.py
curl http://localhost:8000/api/v1/alerts  # shows seeded alerts
```

---

## Monitored Topics

Query: `manufacturing supply chain disruption` (configurable via `GDELT_QUERY` env var)

Topics covered: manufacturing disruptions, supply chain interruptions, raw material shortages, trade restrictions.

Deduplication is enforced by a unique index on `(source_name, article_url)`. An `IntegrityError` on duplicate insert is caught and the alert is marked `duplicate` — no exception raised, no duplicate rows created.

---

## AI Extraction Configuration

Set `EXTRACTION_MODEL` in `.env`:

| Value | Requires | Behaviour |
|-------|----------|-----------|
| `rule_based` | Nothing | Regex + keyword scan — always works locally |
| `anthropic` | `ANTHROPIC_API_KEY` | Claude claude-3-haiku-20240307 |
| `openai` | `OPENAI_API_KEY` | GPT-4o-mini |

Fallback chain: configured model → `rule_based` if API key missing or call fails.

---

## Folder Structure

```
rfq_backend/
├── app/
│   ├── server.py          # FastAPI assembly + lifespan
│   ├── settings.py        # Pydantic BaseSettings
│   ├── logger.py          # Structured logging
│   ├── api/v1/
│   │   ├── endpoints/     # Thin route handlers
│   │   ├── models/        # Pydantic request/response models
│   │   └── ws/            # WebSocket connection manager + endpoint
│   ├── db/
│   │   ├── models.py      # SQLAlchemy ORM models
│   │   ├── session.py     # Async engine + session factory
│   │   ├── init_db.py     # Table creation from schema SQL
│   │   └── repositories/  # Data access layer
│   ├── services/          # Business logic (extraction, document ingestion)
│   └── workers/           # GDELT background monitor
├── tests/                 # pytest test suite
├── scripts/               # demo.sh, gdelt_seed.py
├── assets/
│   ├── db/                # sqlite_schema.sql
│   ├── input/             # sample RFQ document
│   └── static/            # WebSocket test page
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Assumptions & Trade-offs

- **SQLite in-container**: Chosen for local simplicity. The `./data` volume mounts to the host so the DB survives container restarts. Production: replace with RDS Aurora PostgreSQL.
- **In-memory WebSocket manager**: Works for a single-instance deployment. Production: Redis pub/sub-backed manager for horizontal scaling.
- **Rule-based extraction default**: Works without any API keys, making the local demo reproducible. AI model is opt-in via env var.
- **GDELT polling interval**: Default 300s. Configurable via `POLL_INTERVAL_SECONDS`. One-shot trigger available for demo.
- **Background extraction via `BackgroundTasks`**: Returns 202 immediately; extraction runs after response. Sufficient for this scope. Production: use Celery or ARQ with a persistent queue.

---

## AWS Production Architecture

| Local | AWS |
|-------|-----|
| Uvicorn single process | ECS Fargate (auto-scaling) |
| SQLite + volume | RDS Aurora PostgreSQL (Multi-AZ) |
| In-memory WS manager | ElastiCache Redis (pub/sub) |
| asyncio background poll | EventBridge Scheduler → Lambda or ECS task |
| Local file upload | API Gateway + S3 pre-signed URLs |
| stdout logs | CloudWatch Logs + Log Insights |

---

## Data Governance Notes

- Documents contain potentially confidential RFQ data. In production: encrypt at rest (RDS encryption, S3 SSE), enforce TLS in transit, apply row-level access control per tenant.
- GDELT articles are public news — no PII concern. Article URLs and titles only are stored; full article text is not persisted.
- No secrets are committed to source control. `.env` is in `.gitignore`; `sample.env` contains only safe defaults.
- **Authentication:** No authentication is implemented in this build. Before any shared deployment — including internal staging — add OAuth2/JWT middleware or API key validation. Every endpoint currently returns data to any caller.
- **Retention:** The `retention_days` field on `Document` supports per-document TTL. A scheduled job (EventBridge + Lambda or pg_cron in prod) should purge rows where `created_at < NOW() - INTERVAL retention_days DAY`.
- **Audit:** Document reads are logged as structured events (`event=document_read`) to stdout. In production, ship these to CloudTrail or a SIEM.

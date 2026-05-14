# Architecture Diagrams

All diagrams use Mermaid — render natively on GitHub and in most Markdown viewers.

---

## 1. System Architecture Overview

```mermaid
graph TB
    subgraph Client["Client / Caller"]
        C1[REST Client<br/>curl / Postman]
        C2[WebSocket Client<br/>Browser / wscat]
    end

    subgraph FastAPI["FastAPI Service  :8000"]
        GW[CORS Middleware]
        R1[REST Routes<br/>api/v1/]
        R2[WS Endpoint<br/>api/v1/ws/events]
        SVC1[Document Service]
        SVC2[Extraction Service]
        WM[Connection Manager<br/>in-memory]
        BG[Background Tasks<br/>asyncio]
        MON[GDELT Monitor<br/>asyncio loop]
    end

    subgraph DB["Persistence"]
        SQ[(SQLite<br/>WAL mode)]
    end

    subgraph External["External"]
        GDELT[GDELT API<br/>v2/doc/doc]
        AI[Claude / OpenAI<br/>optional]
    end

    C1 -->|HTTP| GW --> R1
    C2 -->|WS upgrade| R2 --> WM
    R1 --> SVC1 --> BG --> SVC2
    SVC2 -->|optional| AI
    SVC1 --> SQ
    SVC2 --> SQ
    BG --> WM
    MON -->|HTTP poll| GDELT
    MON --> SQ
    MON --> WM
```

---

## 2. REST Data Flow — Document Upload & Extraction

```mermaid
sequenceDiagram
    participant C as Client
    participant R as Route Handler
    participant DS as Document Service
    participant DB as SQLite
    participant BG as Background Task
    participant ES as Extraction Service
    participant WS as WS Manager

    C->>R: POST /api/v1/documents (multipart)
    R->>DS: ingest(file, background_tasks)
    DS->>DS: SHA-256 hash
    DS->>DB: SELECT by sha256 (dedup check)
    alt duplicate
        DB-->>DS: existing doc
        DS-->>R: raise 409 Conflict
        R-->>C: 409 {"type": "conflict", "existing_id": "..."}
    else new document
        DB-->>DS: null
        DS->>DB: INSERT document (status=pending)
        DS->>BG: add_task(run_extraction)
        DS-->>R: document_id
        R-->>C: 202 {"document_id": "...", "status": "accepted"}
        BG->>ES: extract_and_persist(doc_id, raw_text)
        ES->>ES: rule_based / AI extraction
        ES->>DB: INSERT keywords
        ES->>DB: INSERT entities
        ES->>DB: UPDATE document status=processed
        ES->>WS: broadcast("extraction_complete", {...})
    end

    C->>R: GET /api/v1/documents/{id}/keywords
    R->>DB: SELECT keywords WHERE document_id=id
    DB-->>R: keyword rows
    R-->>C: 200 {"keywords": [...]}
```

---

## 3. WebSocket Data Flow

```mermaid
sequenceDiagram
    participant B as Browser / wscat
    participant WE as WS Endpoint
    participant CM as Connection Manager
    participant SVC as Services / Workers

    B->>WE: WS upgrade ws://localhost:8000/api/v1/ws/events
    WE->>CM: connect(client_id, websocket)
    CM-->>B: {"event":"connected","client_id":"..."}

    Note over B,CM: Connection is open — client receives events passively

    SVC->>CM: broadcast("extraction_complete", {...})
    CM-->>B: {"event":"extraction_complete","document_id":"...","keyword_count":9}

    SVC->>CM: broadcast("alert_detected", {...})
    CM-->>B: {"event":"alert_detected","title":"...","url":"..."}

    SVC->>CM: broadcast("poll_run_complete", {...})
    CM-->>B: {"event":"poll_run_complete","items_seen":25,"alerts_created":3}

    B->>WE: disconnect (close frame)
    WE->>CM: disconnect(client_id)
```

---

## 4. GDELT Polling & Monitoring Data Flow

```mermaid
flowchart TD
    START([asyncio loop<br/>every 300s]) --> PR[Create PollRun record<br/>status=started]
    PR --> FETCH[GET gdeltproject.org/api/v2/doc/doc<br/>?query=manufacturing supply chain disruption]

    FETCH -->|success| NORM[Normalise articles<br/>url, title, published_at, matched_terms]
    FETCH -->|error| FAIL[Update PollRun<br/>status=failed, error_message]

    NORM --> LOOP{For each article}

    LOOP --> UPSERT[INSERT AlertEvent<br/>source_name + article_url]
    UPSERT -->|IntegrityError| DUP[Mark duplicate<br/>do not raise]
    UPSERT -->|success| ALERT[AlertEvent created<br/>status=detected]

    ALERT --> WS1[WS broadcast<br/>alert_detected]
    DUP --> LOOP
    WS1 --> LOOP

    LOOP -->|done| UPDATE[Update PollRun<br/>status=completed<br/>items_seen, alerts_created]
    UPDATE --> WS2[WS broadcast<br/>poll_run_complete]
    FAIL --> WS2
    WS2 --> REST[Queryable via<br/>GET /api/v1/alerts<br/>GET /api/v1/monitor/runs]
```

---

## Deduplication Detail

The unique index `ux_alert_events_source_url ON alert_events(source_name, article_url)` is the single guard.

On duplicate insert:
1. SQLAlchemy raises `IntegrityError`
2. `alert_repo.insert_alert_event()` catches it, rolls back the savepoint
3. Returns `(alert, created=False)` — caller skips WS broadcast
4. No duplicate row exists in the DB

This makes the polling worker fully idempotent — re-running it any number of times on the same GDELT window produces the same DB state.

# Production Gaps

Each section names a local shortcut, its production replacement, and why the swap matters.

---

## BackgroundTasks → SQS

**Local:** FastAPI `BackgroundTasks` runs the extraction coroutine in-process immediately after returning the 202 response.

**Production:** Publish a message to an SQS FIFO queue on upload. A separate ECS service (the extraction worker) consumes from the queue.

**Rationale:** If the Fargate task is replaced mid-extraction, the job is silently lost. SQS provides at-least-once delivery and a dead-letter queue for failed extractions.

---

## In-memory WS manager → ElastiCache Redis

**Local:** `ConnectionManager` holds WebSocket connections in a Python dict inside the single process.

**Production:** Back the manager with Redis pub/sub (e.g. `aioredis`). Each Fargate task subscribes to the same channel; any task can publish and all clients receive it.

**Rationale:** `broadcast()` only reaches clients on the same instance. Redis pub/sub fans out across all Fargate tasks.

---

## ALB sticky sessions

**Local:** One Fargate task — stickiness is irrelevant.

**Production:** Enable ALB sticky sessions (`stickiness_type=lb_cookie`) on the target group. Without it, a WebSocket reconnect may land on a different task that has no record of the client.

**Rationale:** WebSocket connections are stateful. Without sticky sessions, a reconnect may land on a different task that has no record of the client.

---

## SQLite → Aurora PostgreSQL

**Local:** SQLite with WAL mode handles single-writer concurrency adequately for a demo.

**Production:** Replace with RDS Aurora PostgreSQL. Update `DATABASE_URL` and swap `aiosqlite` for `asyncpg`.

**Rationale:** WAL mode handles single-instance concurrency. Aurora provides Multi-AZ, automated backups, and read replicas.

---

## S3 pre-signed uploads

**Local:** The API tier receives multipart file bytes, hashes them, and writes them to SQLite.

**Production:** Return a pre-signed S3 POST URL on the initial upload request. The client POSTs directly to S3. An S3 event notification triggers the extraction queue message.

**Rationale:** Routing large binary files through the API tier wastes Fargate CPU and memory. Pre-signed POSTs let clients upload directly to S3.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    source_filename TEXT NOT NULL,
    source_mime_type TEXT,
    source_sha256 TEXT NOT NULL UNIQUE,
    raw_text TEXT NOT NULL,
    document_type TEXT NOT NULL,
    upload_origin TEXT NOT NULL DEFAULT 'local',
    processing_status TEXT NOT NULL CHECK (
        processing_status IN ('pending', 'processed', 'failed')
    ),
    created_at TEXT NOT NULL,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS extracted_keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    keyword TEXT NOT NULL,
    normalized_keyword TEXT NOT NULL,
    score REAL NOT NULL,
    source_method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_extracted_keywords_document_keyword
    ON extracted_keywords(document_id, normalized_keyword);

CREATE TABLE IF NOT EXISTS extracted_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_value TEXT NOT NULL,
    normalized_value TEXT,
    confidence REAL NOT NULL,
    quantity_value REAL,
    unit TEXT,
    start_offset INTEGER,
    end_offset INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_extracted_entities_document_id
    ON extracted_entities(document_id);

CREATE INDEX IF NOT EXISTS ix_extracted_entities_type
    ON extracted_entities(entity_type);

CREATE TABLE IF NOT EXISTS poll_runs (
    id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    query_text TEXT NOT NULL,
    window_start TEXT,
    window_end TEXT,
    run_status TEXT NOT NULL CHECK (
        run_status IN ('started', 'completed', 'failed')
    ),
    items_seen INTEGER NOT NULL DEFAULT 0,
    alerts_created INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS alert_events (
    id TEXT PRIMARY KEY,
    poll_run_id TEXT,
    source_name TEXT NOT NULL,
    source_item_id TEXT,
    article_url TEXT NOT NULL,
    article_title TEXT NOT NULL,
    published_at TEXT,
    matched_terms_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    alert_status TEXT NOT NULL CHECK (
        alert_status IN ('detected', 'notified', 'duplicate', 'failed')
    ),
    detected_at TEXT NOT NULL,
    notified_at TEXT,
    processing_error TEXT,
    FOREIGN KEY (poll_run_id) REFERENCES poll_runs(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_alert_events_source_item
    ON alert_events(source_name, source_item_id)
    WHERE source_item_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_alert_events_source_url
    ON alert_events(source_name, article_url);

CREATE TABLE IF NOT EXISTS websocket_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_name TEXT NOT NULL,
    event_name TEXT NOT NULL,
    correlation_id TEXT,
    message_json TEXT NOT NULL,
    emitted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_websocket_messages_channel_name
    ON websocket_messages(channel_name);
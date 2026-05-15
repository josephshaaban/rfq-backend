"""
SQLAlchemy ORM models.  Column names and constraints mirror assets/db/sqlite_schema.sql exactly.
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Integer, Float, Text, String, ForeignKey, Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_filename: Mapped[str] = mapped_column(Text, nullable=False)
    source_mime_type: Mapped[str | None] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    upload_origin: Mapped[str] = mapped_column(Text, nullable=False, default="local")
    processing_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="pending",
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)
    processed_at: Mapped[str | None] = mapped_column(Text)
    # Set via org policy; a background job should hard-delete rows where created_at < now() - retention_days
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('pending', 'processed', 'failed')",
            name="ck_documents_status",
        ),
    )

    keywords: Mapped[list["ExtractedKeyword"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    entities: Mapped[list["ExtractedEntity"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class ExtractedKeyword(Base):
    __tablename__ = "extracted_keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_keyword: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    source_method: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)

    __table_args__ = (
        UniqueConstraint("document_id", "normalized_keyword", name="ux_extracted_keywords_document_keyword"),
    )

    document: Mapped["Document"] = relationship(back_populates="keywords")


class ExtractedEntity(Base):
    __tablename__ = "extracted_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    quantity_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(Text)
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)

    __table_args__ = (
        Index("ix_extracted_entities_document_id", "document_id"),
        Index("ix_extracted_entities_type", "entity_type"),
    )

    document: Mapped["Document"] = relationship(back_populates="entities")


class PollRun(Base):
    __tablename__ = "poll_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    window_start: Mapped[str | None] = mapped_column(Text)
    window_end: Mapped[str | None] = mapped_column(Text)
    run_status: Mapped[str] = mapped_column(Text, nullable=False, default="started")
    items_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alerts_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)
    completed_at: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "run_status IN ('started', 'completed', 'failed')",
            name="ck_poll_runs_status",
        ),
    )

    alerts: Mapped[list["AlertEvent"]] = relationship(back_populates="poll_run")


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    poll_run_id: Mapped[str | None] = mapped_column(ForeignKey("poll_runs.id", ondelete="SET NULL"))
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_item_id: Mapped[str | None] = mapped_column(Text)
    article_url: Mapped[str] = mapped_column(Text, nullable=False)
    article_title: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[str | None] = mapped_column(Text)
    matched_terms_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    alert_status: Mapped[str] = mapped_column(Text, nullable=False, default="detected")
    detected_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)
    notified_at: Mapped[str | None] = mapped_column(Text)
    processing_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "alert_status IN ('detected', 'notified', 'duplicate', 'failed')",
            name="ck_alert_events_status",
        ),
        UniqueConstraint("source_name", "article_url", name="ux_alert_events_source_url"),
    )

    poll_run: Mapped["PollRun"] = relationship(back_populates="alerts")


class WebsocketMessage(Base):
    __tablename__ = "websocket_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_name: Mapped[str] = mapped_column(Text, nullable=False)
    event_name: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(Text)
    message_json: Mapped[str] = mapped_column(Text, nullable=False)
    emitted_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now_iso)

    __table_args__ = (
        Index("ix_websocket_messages_channel_name", "channel_name"),
    )

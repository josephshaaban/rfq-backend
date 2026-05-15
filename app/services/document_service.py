import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import BackgroundTasks, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document
from app.db.repositories import document_repo
from app.db.session import get_session_factory
from app.services.extraction_service import ExtractionService
from app.api.v1.ws.connection_manager import manager
from app.exceptions import (
    DocumentConflictError,
    DocumentEmptyError,
    DocumentTooLargeError,
    DocumentTypeNotSupportedError,
)
from app.logger import get_logger

logger = get_logger(__name__)

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_ACCEPTED_MIME_TYPES = {"text/plain", "application/pdf", "application/octet-stream"}


class DocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ingest(self, file: UploadFile, background_tasks: BackgroundTasks) -> str:
        raw_bytes = await file.read()
        if len(raw_bytes) > _MAX_BYTES:
            raise DocumentTooLargeError(max_mb=10)
        if file.content_type not in _ACCEPTED_MIME_TYPES:
            raise DocumentTypeNotSupportedError(content_type=file.content_type or "unknown")
        if not raw_bytes:
            raise DocumentEmptyError()

        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        document_id = str(uuid.uuid4())

        # Idempotency: return existing document if same content already ingested
        existing = await document_repo.get_document_by_sha256(self._session, sha256)
        if existing:
            raise DocumentConflictError(document_id, existing.id)
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        doc = Document(
            id=document_id,
            source_filename=file.filename or "unknown",
            source_mime_type=file.content_type,
            source_sha256=sha256,
            raw_text=raw_text,
            document_type="rfq",
            upload_origin="local",
            processing_status="pending",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        await document_repo.create_document(self._session, doc)
        logger.info("Document ingested", extra={"document_id": document_id, "file_name": file.filename})

        # Queue extraction as a background task so we return 202 immediately
        background_tasks.add_task(self._run_extraction, document_id, raw_text)
        return document_id

    # Production: replace BackgroundTasks with an SQS message publish.
    # The extraction worker runs as a separate ECS service consuming from the queue.
    # This provides at-least-once delivery and a DLQ for failed extractions.
    async def _run_extraction(self, document_id: str, raw_text: str) -> None:
        """Runs in the background after the upload response is sent."""
        logger.info("Extraction started", extra={"document_id": document_id})
        factory = get_session_factory()
        final_status = "failed"
        keyword_count = entity_count = 0
        async with factory() as session:
            try:
                service = ExtractionService(session)
                keyword_count, entity_count = await service.extract_and_persist(document_id, raw_text)
                final_status = "processed"
            except Exception:
                logger.exception("Extraction failed", extra={"document_id": document_id})
            finally:
                try:
                    await document_repo.update_document_status(session, document_id, final_status)
                    await session.commit()
                except Exception:
                    logger.exception(
                        "Failed to update document status",
                        extra={"document_id": document_id, "target_status": final_status},
                    )
        if final_status == "processed":
            await manager.broadcast(
                "extraction_complete",
                {
                    "document_id": document_id,
                    "keyword_count": keyword_count,
                    "entity_count": entity_count,
                },
                correlation_id=document_id,
            )

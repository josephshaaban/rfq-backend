import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document
from app.db.repositories import document_repo
from app.db.session import get_session_factory
from app.services.extraction_service import ExtractionService
from app.api.v1.ws.connection_manager import manager
from app.logger import get_logger

logger = get_logger(__name__)


class DocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ingest(self, file: UploadFile, background_tasks: BackgroundTasks) -> str:
        raw_bytes = await file.read()
        if not raw_bytes:
            raise HTTPException(
                status_code=422,
                detail={"detail": "Uploaded file is empty", "type": "validation_error"},
            )

        sha256 = hashlib.sha256(raw_bytes).hexdigest()

        # Idempotency: return existing document if same content already ingested
        existing = await document_repo.get_document_by_sha256(self._session, sha256)
        if existing:
            raise HTTPException(
                status_code=409,
                detail={
                    "detail": "Document with identical content already exists",
                    "type": "conflict",
                    "existing_id": existing.id,
                },
            )

        document_id = str(uuid.uuid4())
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

    async def _run_extraction(self, document_id: str, raw_text: str) -> None:
        """Runs in the background after the upload response is sent."""
        factory = get_session_factory()
        async with factory() as session:
            try:
                service = ExtractionService(session)
                keyword_count, entity_count = await service.extract_and_persist(document_id, raw_text)

                await session.commit()
                logger.info(
                    "Extraction complete",
                    extra={"document_id": document_id, "keywords": keyword_count, "entities": entity_count},
                )

                # Broadcast extraction_complete event to WebSocket clients
                await manager.broadcast(
                    "extraction_complete",
                    {
                        "document_id": document_id,
                        "keyword_count": keyword_count,
                        "entity_count": entity_count,
                    },
                    correlation_id=document_id,
                )

            except Exception as exc:
                await session.rollback()
                logger.exception("Extraction failed", extra={"document_id": document_id, "error": str(exc)})
                async with factory() as err_session:
                    await document_repo.update_document_status(err_session, document_id, "failed")
                    await err_session.commit()

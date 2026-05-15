from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import Document, ExtractedKeyword, ExtractedEntity
from app.logger import get_logger

logger = get_logger(__name__)


async def create_document(session: AsyncSession, document: Document) -> Document:
    session.add(document)
    await session.flush()
    await session.refresh(document)
    return document


async def get_document_by_id(session: AsyncSession, document_id: str) -> Document | None:
    result = await session.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


async def get_document_by_sha256(session: AsyncSession, sha256: str) -> Document | None:
    result = await session.execute(select(Document).where(Document.source_sha256 == sha256))
    return result.scalar_one_or_none()


async def update_document_status(
    session: AsyncSession,
    document_id: str,
    status: str,
    processed_at: str | None = None,
) -> None:
    doc = await get_document_by_id(session, document_id)
    if doc:
        doc.processing_status = status
        if processed_at:
            doc.processed_at = processed_at
        await session.flush()
    else:
        logger.warning("Document not found for status update", extra={"document_id": document_id})


async def log_document_read(session: AsyncSession, document_id: str, read_by: str = "api") -> None:
    logger.info("Document read", extra={"document_id": document_id, "read_by": read_by, "event": "document_read"})


async def bulk_insert_keywords(
    session: AsyncSession, keywords: list[ExtractedKeyword]
) -> None:
    session.add_all(keywords)
    await session.flush()


async def bulk_insert_entities(
    session: AsyncSession, entities: list[ExtractedEntity]
) -> None:
    session.add_all(entities)
    await session.flush()


async def get_keywords_for_document(
    session: AsyncSession, document_id: str
) -> list[ExtractedKeyword]:
    result = await session.execute(
        select(ExtractedKeyword)
        .where(ExtractedKeyword.document_id == document_id)
        .order_by(ExtractedKeyword.score.desc())
    )
    return list(result.scalars().all())


async def get_entities_for_document(
    session: AsyncSession, document_id: str, entity_type: str | None = None
) -> list[ExtractedEntity]:
    q = select(ExtractedEntity).where(ExtractedEntity.document_id == document_id)
    if entity_type:
        q = q.where(ExtractedEntity.entity_type == entity_type)
    result = await session.execute(q.order_by(ExtractedEntity.confidence.desc()))
    return list(result.scalars().all())

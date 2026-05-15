from fastapi import APIRouter, Depends, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.repositories import document_repo
from app.db.repositories.document_repo import log_document_read
from app.api.v1.models.document_models import (
    DocumentResponse,
    DocumentUploadResponse,
    KeywordsListResponse,
    EntitiesListResponse,
    KeywordResponse,
    EntityResponse,
)
from app.exceptions import DocumentNotFoundError, InvalidEntityTypeError
from app.services.document_service import DocumentService
from app.services.extraction_service import VALID_ENTITY_TYPES

router = APIRouter()


@router.post(
    "/documents",
    response_model=DocumentUploadResponse,
    status_code=202,
    summary="Upload a document for extraction",
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    service = DocumentService(session)
    document_id = await service.ingest(file, background_tasks)
    return DocumentUploadResponse(
        document_id=document_id,
        status="accepted",
        message="Document accepted for processing. Poll GET /api/v1/documents/{id} for status.",
    )


@router.get(
    "/documents/{document_id}",
    response_model=DocumentResponse,
    summary="Get document record and processing status",
)
async def get_document(
    document_id: str,
    session: AsyncSession = Depends(get_session),
):
    doc = await document_repo.get_document_by_id(session, document_id)
    if not doc:
        raise DocumentNotFoundError(document_id)
    await log_document_read(session, document_id)
    return DocumentResponse.model_validate(doc)


@router.get(
    "/documents/{document_id}/keywords",
    response_model=KeywordsListResponse,
    summary="Get extracted keywords for a document",
)
async def get_keywords(
    document_id: str,
    session: AsyncSession = Depends(get_session),
):
    doc = await document_repo.get_document_by_id(session, document_id)
    if not doc:
        raise DocumentNotFoundError(document_id)

    keywords = await document_repo.get_keywords_for_document(session, document_id)
    return KeywordsListResponse(
        document_id=document_id,
        count=len(keywords),
        keywords=[KeywordResponse.model_validate(k) for k in keywords],
    )


@router.get(
    "/documents/{document_id}/entities",
    response_model=EntitiesListResponse,
    summary="Get extracted structured entities for a document",
)
async def get_entities(
    document_id: str,
    entity_type: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    doc = await document_repo.get_document_by_id(session, document_id)
    if not doc:
        raise DocumentNotFoundError(document_id)

    if entity_type is not None and entity_type not in VALID_ENTITY_TYPES:
        raise InvalidEntityTypeError(entity_type, sorted(VALID_ENTITY_TYPES))

    entities = await document_repo.get_entities_for_document(session, document_id, entity_type)
    return EntitiesListResponse(
        document_id=document_id,
        count=len(entities),
        entities=[EntityResponse.model_validate(e) for e in entities],
    )

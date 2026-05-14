from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.repositories import document_repo
from app.api.v1.models.document_models import (
    DocumentResponse,
    DocumentUploadResponse,
    KeywordsListResponse,
    EntitiesListResponse,
    KeywordResponse,
    EntityResponse,
)
from app.services.document_service import DocumentService

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
    if not file.filename:
        raise HTTPException(
            status_code=422,
            detail={"detail": "Filename is required", "type": "validation_error"},
        )

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
        raise HTTPException(status_code=404, detail={"detail": "Document not found", "type": "not_found"})
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
        raise HTTPException(status_code=404, detail={"detail": "Document not found", "type": "not_found"})

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
        raise HTTPException(status_code=404, detail={"detail": "Document not found", "type": "not_found"})

    entities = await document_repo.get_entities_for_document(session, document_id, entity_type)
    return EntitiesListResponse(
        document_id=document_id,
        count=len(entities),
        entities=[EntityResponse.model_validate(e) for e in entities],
    )

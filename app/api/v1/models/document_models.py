from pydantic import BaseModel, Field
from typing import Literal


class DocumentResponse(BaseModel):
    id: str
    source_filename: str
    source_mime_type: str | None
    source_sha256: str
    document_type: str
    upload_origin: str
    processing_status: Literal["pending", "processed", "failed"]
    created_at: str
    processed_at: str | None
    retention_days: int | None = None

    model_config = {"from_attributes": True}


class KeywordResponse(BaseModel):
    id: int
    keyword: str
    normalized_keyword: str
    score: float
    source_method: str
    created_at: str

    model_config = {"from_attributes": True}


class EntityResponse(BaseModel):
    id: int
    entity_type: str
    entity_value: str
    normalized_value: str | None
    confidence: float
    quantity_value: float | None
    unit: str | None
    start_offset: int | None
    end_offset: int | None
    created_at: str

    model_config = {"from_attributes": True}


class DocumentUploadResponse(BaseModel):
    document_id: str
    status: str = "accepted"
    message: str


class ErrorDetail(BaseModel):
    detail: str
    type: str
    field: str | None = None


class KeywordsListResponse(BaseModel):
    document_id: str
    count: int
    keywords: list[KeywordResponse]


class EntitiesListResponse(BaseModel):
    document_id: str
    count: int
    entities: list[EntityResponse]

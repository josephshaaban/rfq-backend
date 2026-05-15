from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DocumentNotFoundError(Exception):
    def __init__(self, document_id: str) -> None:
        self.document_id = document_id
        super().__init__(f"Document '{document_id}' not found")


class DocumentConflictError(Exception):
    def __init__(self, document_id: str, existing_id: str) -> None:
        self.document_id = document_id
        self.existing_id = existing_id
        super().__init__(f"Document with identical content already exists (existing_id={existing_id})")


class DocumentEmptyError(Exception):
    def __init__(self) -> None:
        super().__init__("Uploaded file is empty")


class DocumentTooLargeError(Exception):
    def __init__(self, max_mb: int) -> None:
        self.max_mb = max_mb
        super().__init__(f"Document exceeds maximum size of {max_mb} MB")


class DocumentTypeNotSupportedError(Exception):
    def __init__(self, content_type: str) -> None:
        self.content_type = content_type
        super().__init__(f"Content type '{content_type}' is not supported")


class InvalidEntityTypeError(Exception):
    def __init__(self, value: str, allowed: list[str]) -> None:
        self.value = value
        self.allowed = allowed
        super().__init__(f"Entity type '{value}' is not valid; allowed: {allowed}")


# ---------------------------------------------------------------------------
# Internal helper — builds the consistent inner body dict.
# Shape: {"detail": "msg", "type": "code", "field": null|str, **extra}
# Wrapped by JSONResponse as {"detail": <this dict>} to preserve test compat.
# ---------------------------------------------------------------------------
def _body(detail: str, type_: str, field: str | None = None, **extra: object) -> dict:
    payload: dict = {"detail": detail, "type": type_, "field": field}
    payload.update(extra)
    return payload


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DocumentNotFoundError)
    async def _not_found(request: Request, exc: DocumentNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": _body("Document not found", "not_found")},
        )

    @app.exception_handler(DocumentConflictError)
    async def _conflict(request: Request, exc: DocumentConflictError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": _body(
                "Document with identical content already exists",
                "conflict",
                existing_id=exc.existing_id,
            )},
        )

    @app.exception_handler(DocumentEmptyError)
    async def _empty(request: Request, exc: DocumentEmptyError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": _body("Uploaded file is empty", "validation_error", field="file")},
        )

    @app.exception_handler(DocumentTooLargeError)
    async def _too_large(request: Request, exc: DocumentTooLargeError) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content={"detail": _body(
                f"File exceeds maximum size of {exc.max_mb} MB",
                "payload_too_large",
                field="file",
            )},
        )

    @app.exception_handler(DocumentTypeNotSupportedError)
    async def _unsupported_type(request: Request, exc: DocumentTypeNotSupportedError) -> JSONResponse:
        return JSONResponse(
            status_code=415,
            content={"detail": _body(
                f"Content type '{exc.content_type}' is not supported",
                "unsupported_media_type",
                field="file",
            )},
        )

    @app.exception_handler(InvalidEntityTypeError)
    async def _invalid_entity_type(request: Request, exc: InvalidEntityTypeError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": _body(
                f"Entity type '{exc.value}' is not valid",
                "invalid_entity_type",
                field="entity_type",
                allowed=exc.allowed,
            )},
        )

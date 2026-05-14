import io
import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio

SAMPLE_RFQ = b"""RFQ Reference: RFQ-2026-0417
Buyer: Northshore Industrial Systems Ltd.
Delivery Location: Bremen, Germany
Currency: EUR
Incoterm: DDP Bremen
Material Grade: AISI 316L
Manufacturing Process: CNC milling and finishing
Quantity: 1200 pieces
Tolerance: +/- 0.10 mm on critical faces
Certification Required: EN 10204 3.1 material certificate
"""


async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert "db" in data


async def test_upload_document_202(client: AsyncClient):
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("rfq_test.txt", io.BytesIO(SAMPLE_RFQ), "text/plain")},
    )
    assert response.status_code == 202
    data = response.json()
    assert "document_id" in data
    assert data["status"] == "accepted"


async def test_upload_duplicate_409(client: AsyncClient):
    # Upload once
    await client.post(
        "/api/v1/documents",
        files={"file": ("rfq_dup.txt", io.BytesIO(b"Unique content for dup test"), "text/plain")},
    )
    # Upload same content again → 409
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("rfq_dup2.txt", io.BytesIO(b"Unique content for dup test"), "text/plain")},
    )
    assert response.status_code == 409
    data = response.json()
    assert data["detail"]["type"] == "conflict"
    assert "existing_id" in data["detail"]


async def test_get_document_not_found(client: AsyncClient):
    response = await client.get("/api/v1/documents/nonexistent-id-xyz")
    assert response.status_code == 404
    assert response.json()["detail"]["type"] == "not_found"


async def test_get_document(client: AsyncClient):
    upload = await client.post(
        "/api/v1/documents",
        files={"file": ("rfq_get.txt", io.BytesIO(b"Get test document content"), "text/plain")},
    )
    doc_id = upload.json()["document_id"]

    response = await client.get(f"/api/v1/documents/{doc_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == doc_id
    assert data["processing_status"] in ("pending", "processed", "failed")


async def test_get_keywords_endpoint(client: AsyncClient):
    upload = await client.post(
        "/api/v1/documents",
        files={"file": ("rfq_kw.txt", io.BytesIO(SAMPLE_RFQ + b" extra"), "text/plain")},
    )
    doc_id = upload.json()["document_id"]

    response = await client.get(f"/api/v1/documents/{doc_id}/keywords")
    assert response.status_code == 200
    data = response.json()
    assert "keywords" in data
    assert "count" in data


async def test_get_entities_endpoint(client: AsyncClient):
    upload = await client.post(
        "/api/v1/documents",
        files={"file": ("rfq_ent.txt", io.BytesIO(SAMPLE_RFQ + b" more"), "text/plain")},
    )
    doc_id = upload.json()["document_id"]

    response = await client.get(f"/api/v1/documents/{doc_id}/entities")
    assert response.status_code == 200
    data = response.json()
    assert "entities" in data
    assert "count" in data


async def test_list_alerts(client: AsyncClient):
    response = await client.get("/api/v1/alerts")
    assert response.status_code == 200
    data = response.json()
    assert "alerts" in data
    assert isinstance(data["alerts"], list)


async def test_list_poll_runs(client: AsyncClient):
    response = await client.get("/api/v1/monitor/runs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

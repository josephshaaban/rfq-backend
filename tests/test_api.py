import asyncio
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
    assert "total_count" in data
    assert data["total_count"] >= 0


async def test_list_poll_runs(client: AsyncClient):
    response = await client.get("/api/v1/monitor/runs")
    assert response.status_code == 200
    data = response.json()
    assert "runs" in data
    assert isinstance(data["runs"], list)
    assert "total_count" in data
    assert data["total_count"] >= 0


async def test_health_db_reachable(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def _wait_for_processed(client: AsyncClient, doc_id: str, retries: int = 3) -> None:
    for _ in range(retries):
        await asyncio.sleep(0.5)
        resp = await client.get(f"/api/v1/documents/{doc_id}")
        if resp.json()["processing_status"] == "processed":
            return


async def test_get_keywords_has_content(client: AsyncClient):
    upload = await client.post(
        "/api/v1/documents",
        files={"file": ("rfq_kw_content.txt", io.BytesIO(SAMPLE_RFQ + b" kw_content"), "text/plain")},
    )
    doc_id = upload.json()["document_id"]
    await _wait_for_processed(client, doc_id)

    response = await client.get(f"/api/v1/documents/{doc_id}/keywords")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] > 0
    kw_set = {k["keyword"] for k in data["keywords"]}
    assert kw_set & {"cnc", "tolerance", "316l", "ddp", "bremen"}


async def test_get_entities_has_content(client: AsyncClient):
    upload = await client.post(
        "/api/v1/documents",
        files={"file": ("rfq_ent_content.txt", io.BytesIO(SAMPLE_RFQ + b" ent_content"), "text/plain")},
    )
    doc_id = upload.json()["document_id"]
    await _wait_for_processed(client, doc_id)

    response = await client.get(f"/api/v1/documents/{doc_id}/entities")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] > 0
    assert any(
        e["entity_type"] == "incoterm" and e["entity_value"] == "DDP"
        for e in data["entities"]
    )


async def test_get_entities_filter_by_type(client: AsyncClient):
    upload = await client.post(
        "/api/v1/documents",
        files={"file": ("rfq_ent_filter.txt", io.BytesIO(SAMPLE_RFQ + b" ent_filter"), "text/plain")},
    )
    doc_id = upload.json()["document_id"]
    await _wait_for_processed(client, doc_id)

    response = await client.get(f"/api/v1/documents/{doc_id}/entities?entity_type=incoterm")
    assert response.status_code == 200
    data = response.json()
    assert len(data["entities"]) > 0
    assert all(e["entity_type"] == "incoterm" for e in data["entities"])


async def test_get_entities_invalid_type_400(client: AsyncClient):
    response = await client.get("/api/v1/documents/any-doc-id/entities?entity_type=INVALID_TYPE")
    assert response.status_code == 400
    data = response.json()
    assert data["detail"]["type"] == "invalid_entity_type"


async def test_list_alerts_has_pagination_fields(client: AsyncClient):
    response = await client.get("/api/v1/alerts")
    assert response.status_code == 200
    data = response.json()
    assert "total_count" in data
    assert "has_more" in data


async def test_upload_too_large_413(client: AsyncClient):
    large_content = b"x" * (11 * 1024 * 1024)
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("large.txt", io.BytesIO(large_content), "text/plain")},
    )
    assert response.status_code == 413

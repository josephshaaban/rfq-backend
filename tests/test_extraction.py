import pytest
from app.services.extraction_service import ExtractionService

pytestmark = pytest.mark.asyncio

RFQ_TEXT = """RFQ Reference: RFQ-2026-0417
Issue Date: 2026-04-17
Buyer: Northshore Industrial Systems Ltd.
Delivery Location: Bremen, Germany
Requested Delivery Date: 2026-06-20
Currency: EUR
Incoterm: DDP Bremen

Material Grade: AISI 316L
Manufacturing Process: CNC milling and finishing
Surface Finish: Ra 1.6 max
Quantity: 1200 pieces
Tolerance: +/- 0.10 mm on critical faces
Certification Required: EN 10204 3.1 material certificate
"""


async def test_rule_based_extracts_material(db_session):
    service = ExtractionService(db_session)
    keywords, entities = service._extract_rule_based(RFQ_TEXT)

    entity_types = [e["type"] for e in entities]
    entity_values = [e["value"].upper() for e in entities]

    assert "material" in entity_types, "Should detect material entity"
    assert any("316L" in v or "STAINLESS" in v for v in entity_values), "Should find AISI 316L"


async def test_rule_based_extracts_incoterm(db_session):
    service = ExtractionService(db_session)
    _, entities = service._extract_rule_based(RFQ_TEXT)

    incoterms = [e["value"] for e in entities if e["type"] == "incoterm"]
    assert any("DDP" in v for v in incoterms), "Should extract DDP incoterm"


async def test_rule_based_extracts_tolerance(db_session):
    service = ExtractionService(db_session)
    _, entities = service._extract_rule_based(RFQ_TEXT)

    tolerances = [e["value"] for e in entities if e["type"] == "tolerance"]
    assert len(tolerances) > 0, "Should extract tolerance value"
    assert any("0.10" in t for t in tolerances)


async def test_rule_based_extracts_currency(db_session):
    service = ExtractionService(db_session)
    _, entities = service._extract_rule_based(RFQ_TEXT)

    currencies = [e["value"] for e in entities if e["type"] == "currency"]
    assert "EUR" in currencies


async def test_rule_based_extracts_keywords(db_session):
    service = ExtractionService(db_session)
    keywords, _ = service._extract_rule_based(RFQ_TEXT)

    kw_names = [k["keyword"] for k in keywords]
    assert "stainless steel" in kw_names
    assert "cnc" in kw_names
    assert "tolerance" in kw_names


async def test_rule_based_extracts_process(db_session):
    service = ExtractionService(db_session)
    _, entities = service._extract_rule_based(RFQ_TEXT)

    processes = [e["value"] for e in entities if e["type"] == "process"]
    assert any("CNC" in p for p in processes)


async def test_llm_response_parser(db_session):
    service = ExtractionService(db_session)
    raw = '{"keywords": [{"keyword": "CNC", "score": 0.9}], "entities": [{"type": "material", "value": "AISI 316L", "confidence": 0.95, "quantity_value": null, "unit": null}]}'
    keywords, entities = service._parse_llm_response(raw)

    assert len(keywords) == 1
    assert keywords[0]["keyword"] == "CNC"
    assert keywords[0]["source_method"] == "llm"
    assert entities[0]["type"] == "material"
    assert entities[0]["value"] == "AISI 316L"

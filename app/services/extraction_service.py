"""
Extraction service.

Strategy selection (configured via EXTRACTION_MODEL env var):
  rule_based  — regex + keyword scan, no external API needed (default, always works locally)
  anthropic   — Claude API via ANTHROPIC_API_KEY
  openai      — OpenAI API via OPENAI_API_KEY

The fallback chain is: configured model → rule_based.
"""
import re
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExtractedKeyword, ExtractedEntity
from app.db.repositories.document_repo import (
    bulk_insert_keywords,
    bulk_insert_entities,
    update_document_status,
)
from app.settings import get_settings
from app.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Entity patterns for rule-based extraction
# ---------------------------------------------------------------------------
ENTITY_PATTERNS: list[tuple[str, str]] = [
    ("material", r"\bAISI\s+\d+[A-Z]?\b|\bstainless\s+steel\b|\baluminum\b|\btitanium\b"),
    ("quantity", r"\b\d[\d,]*\s*(?:pcs|pieces|units|ea|each)\b"),
    ("tolerance", r"[+\-±]\s*/?\s*\d+\.?\d*\s*mm"),
    ("incoterm", r"\b(?:DDP|DAP|FOB|CIF|EXW|FCA|CPT|CIP|DAT|DPU)\b"),
    ("currency", r"\bEUR\b|\bUSD\b|\bGBP\b|\bJPY\b"),
    ("certification", r"\bEN\s+\d+[\w\s.]+certificate\b|\bISO\s+\d+\b|\bAS\s+\d+\b"),
    ("location", r"\b[A-Z][a-z]+,\s+(?:Germany|France|USA|UK|China|Japan)\b"),
    ("due_date", r"\b\d{4}-\d{2}-\d{2}\b"),
    ("process", r"\bCNC\s+\w+\b|\bmilling\b|\bturning\b|\bgrinding\b|\bwelding\b"),
]

# Keywords of interest extracted verbatim from the RFQ document hint
VALID_ENTITY_TYPES: frozenset[str] = frozenset(ep[0] for ep in ENTITY_PATTERNS) | {"unit"}

RFQ_SEED_KEYWORDS = [
    "stainless steel", "cnc", "tolerance", "316l", "certificate",
    "bremen", "ddp", "conveyor", "retrofit", "lead time",
]


class ExtractionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def extract_and_persist(self, document_id: str, raw_text: str) -> tuple[int, int]:
        """Returns (keyword_count, entity_count)."""
        model = settings.extraction_model

        try:
            if model == "anthropic" and settings.anthropic_api_key:
                keywords, entities = await self._extract_with_anthropic(raw_text)
            elif model == "openai" and settings.openai_api_key:
                keywords, entities = await self._extract_with_openai(raw_text)
            else:
                if model != "rule_based":
                    logger.warning(
                        "Requested extraction model unavailable, falling back to rule_based",
                        extra={"requested": model},
                    )
                keywords, entities = self._extract_rule_based(raw_text)
        except Exception as exc:
            logger.exception("AI extraction failed, falling back to rule_based", extra={"error": str(exc)})
            keywords, entities = self._extract_rule_based(raw_text)

        now = datetime.now(timezone.utc).isoformat()

        kw_models = [
            ExtractedKeyword(
                document_id=document_id,
                keyword=kw["keyword"],
                normalized_keyword=kw["keyword"].lower().strip(),
                score=kw.get("score", 0.5),
                source_method=kw.get("source_method", "rule_based"),
                created_at=now,
            )
            for kw in keywords
        ]

        ent_models = [
            ExtractedEntity(
                document_id=document_id,
                entity_type=ent["type"],
                entity_value=ent["value"],
                normalized_value=ent.get("normalized_value"),
                confidence=ent.get("confidence", 0.8),
                quantity_value=ent.get("quantity_value"),
                unit=ent.get("unit"),
                start_offset=ent.get("start_offset"),
                end_offset=ent.get("end_offset"),
                created_at=now,
            )
            for ent in entities
        ]

        await bulk_insert_keywords(self._session, kw_models)
        await bulk_insert_entities(self._session, ent_models)
        await update_document_status(self._session, document_id, "processed", processed_at=now)

        return len(kw_models), len(ent_models)

    # ------------------------------------------------------------------
    # Rule-based extraction (no external dependencies)
    # ------------------------------------------------------------------
    def _extract_rule_based(self, text: str) -> tuple[list[dict], list[dict]]:
        text_lower = text.lower()
        keywords = []
        seen_kw: set[str] = set()

        # Score keywords by frequency
        for kw in RFQ_SEED_KEYWORDS:
            count = text_lower.count(kw)
            if count > 0 and kw not in seen_kw:
                keywords.append({"keyword": kw, "score": min(1.0, count * 0.2), "source_method": "rule_based"})
                seen_kw.add(kw)

        entities = []
        for entity_type, pattern in ENTITY_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                entities.append({
                    "type": entity_type,
                    "value": match.group(0).strip(),
                    "confidence": 0.75,
                    "start_offset": match.start(),
                    "end_offset": match.end(),
                })

        return keywords, entities

    # ------------------------------------------------------------------
    # Anthropic extraction (requires ANTHROPIC_API_KEY)
    # ------------------------------------------------------------------
    async def _extract_with_anthropic(self, text: str) -> tuple[list[dict], list[dict]]:
        import anthropic  # type: ignore

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        prompt = self._build_extraction_prompt(text)
        message = await client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text
        return self._parse_llm_response(raw)

    # ------------------------------------------------------------------
    # OpenAI extraction (requires OPENAI_API_KEY)
    # ------------------------------------------------------------------
    async def _extract_with_openai(self, text: str) -> tuple[list[dict], list[dict]]:
        import openai  # type: ignore

        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        prompt = self._build_extraction_prompt(text)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        return self._parse_llm_response(raw)

    def _build_extraction_prompt(self, text: str) -> str:
        return f"""You are a manufacturing document parser. Extract structured data from this RFQ document.

Return ONLY a valid JSON object with this exact schema (no markdown, no explanation):
{{
  "keywords": [
    {{"keyword": "string", "score": 0.0-1.0}}
  ],
  "entities": [
    {{
      "type": "material|quantity|unit|due_date|tolerance|incoterm|currency|process|certification|location",
      "value": "string",
      "confidence": 0.0-1.0,
      "quantity_value": null or number,
      "unit": null or "string"
    }}
  ]
}}

Document text:
{text[:4000]}"""

    def _parse_llm_response(self, raw: str) -> tuple[list[dict], list[dict]]:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"```\w*\n?", "", raw).strip()
        data = json.loads(raw)
        keywords = [
            {**kw, "source_method": "llm"}
            for kw in data.get("keywords", [])
        ]
        entities = data.get("entities", [])
        return keywords, entities

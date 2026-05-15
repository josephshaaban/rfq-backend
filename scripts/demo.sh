#!/usr/bin/env bash
# demo.sh — full end-to-end demo for the interview panel
# Usage: bash scripts/demo.sh
# Assumes the API is running on localhost:8000 (docker compose up --build)
# Idempotent: safe to run multiple times — reuses existing document on 409.

set -euo pipefail

BASE="http://localhost:8000"
RFQ="assets/input/manufacturing_rfq_sample.txt"
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m'

echo -e "\n${BLUE}=== RFQ Backend Platform Demo ===${NC}\n"

# 1. Health check
echo -e "${GREEN}1. Health check${NC}"
curl -s "$BASE/health" | python -m json.tool
echo

# 2. Upload sample document — idempotent: reuses existing doc on 409
echo -e "${GREEN}2. Upload sample RFQ document${NC}"
UPLOAD_RESP=$(curl -s -X POST "$BASE/api/v1/documents" -F "file=@$RFQ;type=text/plain")

# Check if fresh upload (has document_id) or conflict (has detail.existing_id)
if echo "$UPLOAD_RESP" | python -c "import sys,json; d=json.load(sys.stdin); exit(0 if 'document_id' in d else 1)" 2>/dev/null; then
  DOC_ID=$(echo "$UPLOAD_RESP" | python -c "import sys,json; print(json.load(sys.stdin)['document_id'])")
  echo "$UPLOAD_RESP" | python -m json.tool
  echo -e "${GREEN}✓ Document uploaded — ID: $DOC_ID${NC}"
else
  DOC_ID=$(echo "$UPLOAD_RESP" | python -c "import sys,json; print(json.load(sys.stdin)['detail']['existing_id'])")
  echo -e "${YELLOW}↩ Document already ingested (idempotency check passed) — reusing ID: $DOC_ID${NC}"
fi
echo

# 3. Wait briefly for background extraction to complete
echo -e "${GREEN}3. Waiting for extraction...${NC}"
sleep 2

# 4. Check document status
echo -e "${GREEN}4. Document status${NC}"
curl -s "$BASE/api/v1/documents/$DOC_ID" | python -m json.tool
echo

# 5. Retrieve extracted keywords
echo -e "${GREEN}5. Extracted keywords${NC}"
curl -s "$BASE/api/v1/documents/$DOC_ID/keywords" | python -m json.tool
echo

# 6. Retrieve structured entities
echo -e "${GREEN}6. Extracted entities${NC}"
curl -s "$BASE/api/v1/documents/$DOC_ID/entities" | python -m json.tool
echo

# 7. Trigger GDELT monitor poll
echo -e "${GREEN}7. Trigger GDELT monitor poll${NC}"
TRIGGER_RESP=$(curl -s -X POST "$BASE/api/v1/monitor/trigger")
echo "$TRIGGER_RESP" | python -m json.tool
echo -e "${YELLOW}Waiting for poll to complete...${NC}"
sleep 3
echo

# 8. Show alert events
echo -e "${GREEN}8. Alert events from GDELT${NC}"
curl -s "$BASE/api/v1/alerts" | python -m json.tool
echo

# 9. Show poll run history
echo -e "${GREEN}9. Poll run history${NC}"
curl -s "$BASE/api/v1/monitor/runs" | python -m json.tool
echo

echo -e "${BLUE}=== Demo complete ===${NC}"
echo "Open Swagger UI: $BASE/docs"
echo "WebSocket test:  open assets/static/ws-test.html in a browser"
echo "Or connect:      wscat -c ws://localhost:8000/api/v1/ws/events"

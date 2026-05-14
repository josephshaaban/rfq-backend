#!/usr/bin/env bash
# demo.sh — full end-to-end demo for the interview panel
# Usage: bash scripts/demo.sh
# Assumes the API is running on localhost:8000 (docker compose up --build)

set -euo pipefail

BASE="http://localhost:8000"
RFQ="assets/input/manufacturing_rfq_sample.txt"
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "\n${BLUE}=== RFQ Backend Platform Demo ===${NC}\n"

# 1. Health check
echo -e "${GREEN}1. Health check${NC}"
curl -s "$BASE/health" | python3 -m json.tool
echo

# 2. Upload sample document
echo -e "${GREEN}2. Upload sample RFQ document${NC}"
UPLOAD_RESP=$(curl -s -X POST "$BASE/api/v1/documents" -F "file=@$RFQ;type=text/plain")
echo "$UPLOAD_RESP" | python3 -m json.tool
DOC_ID=$(echo "$UPLOAD_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['document_id'])")
echo "Document ID: $DOC_ID"
echo

# 3. Wait briefly for background extraction to complete
echo -e "${GREEN}3. Waiting for extraction...${NC}"
sleep 2

# 4. Check document status
echo -e "${GREEN}4. Document status${NC}"
curl -s "$BASE/api/v1/documents/$DOC_ID" | python3 -m json.tool
echo

# 5. Retrieve extracted keywords
echo -e "${GREEN}5. Extracted keywords${NC}"
curl -s "$BASE/api/v1/documents/$DOC_ID/keywords" | python3 -m json.tool
echo

# 6. Retrieve structured entities
echo -e "${GREEN}6. Extracted entities${NC}"
curl -s "$BASE/api/v1/documents/$DOC_ID/entities" | python3 -m json.tool
echo

# 7. Trigger GDELT monitor poll
echo -e "${GREEN}7. Trigger GDELT monitor poll${NC}"
TRIGGER_RESP=$(curl -s -X POST "$BASE/api/v1/monitor/trigger")
echo "$TRIGGER_RESP" | python3 -m json.tool
echo "Waiting for poll to complete..."
sleep 3
echo

# 8. Show alert events
echo -e "${GREEN}8. Alert events from GDELT${NC}"
curl -s "$BASE/api/v1/alerts" | python3 -m json.tool
echo

# 9. Show poll run history
echo -e "${GREEN}9. Poll run history${NC}"
curl -s "$BASE/api/v1/monitor/runs" | python3 -m json.tool
echo

echo -e "${BLUE}=== Demo complete ===${NC}"
echo "Open Swagger UI: $BASE/docs"
echo "WebSocket test:  open assets/static/ws-test.html in a browser"
echo "Or connect:      wscat -c ws://localhost:8000/api/v1/ws/events"

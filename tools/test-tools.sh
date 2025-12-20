#!/bin/bash
# Quick test script for all RAG tools

set -e

echo "==== Testing RAG Tools ===="
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

test_endpoint() {
    local name=$1
    local url=$2

    echo -n "Testing $name... "

    if response=$(curl -s -f "$url" 2>&1); then
        if echo "$response" | grep -q '"status":"ok"'; then
            echo -e "${GREEN}OK${NC}"
            return 0
        else
            echo -e "${YELLOW}? Unexpected response${NC}"
            echo "Response: $response"
            return 1
        fi
    else
        echo -e "${RED}FAILED${NC}"
        echo "Error: $response"
        return 1
    fi
}

echo "Testing health endpoints..."
echo ""

# Test each tool
test_endpoint "tool-archive" "http://127.0.0.1:9101/healthz"
test_endpoint "tool-office " "http://127.0.0.1:9102/healthz"
test_endpoint "tool-ocr    " "http://127.0.0.1:9103/healthz"
test_endpoint "tool-gpu    " "http://127.0.0.1:9104/healthz"

echo ""
echo "==== Check systemd status ===="
echo ""

for tool in archive office ocr gpu; do
    echo "tool-$tool:"
    systemctl --user is-active "tool-$tool.socket" >/dev/null 2>&1 && \
        echo -e "  Socket: ${GREEN}active${NC}" || \
        echo -e "  Socket: ${RED}inactive${NC}"

    systemctl --user is-active "tool-$tool.service" >/dev/null 2>&1 && \
        echo -e "  Service: ${GREEN}running${NC}" || \
        echo -e "  Service: ${YELLOW}stopped${NC} (will start on demand)"
done

echo ""
echo "==== GPU Info ===="
echo ""
curl -s http://127.0.0.1:9104/gpu-info | python3 -m json.tool || echo "Failed to get GPU info"

echo ""
echo "==== All tests complete ===="

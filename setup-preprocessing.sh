#!/bin/bash
# Setup script for RAG preprocessing tools
# This script ensures sockets are enabled and tools are ready

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}====================================================================${NC}"
echo -e "${BLUE}RAG Preprocessing Tools - Setup & Verification${NC}"
echo -e "${BLUE}====================================================================${NC}"
echo ""

# Check if images are built
echo "Checking if tool images are built..."
if ! podman images | grep -q "rag-tool-office\|rag-tool-archive"; then
    echo -e "${YELLOW}WARN  Tool images not found. Building now...${NC}"
    echo ""
    cd tools
    ./build-all.sh
    cd ..
    echo ""
else
    echo -e "${GREEN}OK${NC} Tool images found"
fi

# Check if systemd units are installed
echo ""
echo "Checking systemd units..."
if [ ! -f ~/.config/systemd/user/tool-office.socket ]; then
    echo -e "${YELLOW}WARN  Systemd units not installed. Installing now...${NC}"
    echo ""
    cd tools
    ./install-systemd.sh
    cd ..
    echo ""
else
    echo -e "${GREEN}OK${NC} Systemd units installed"
fi

# Enable sockets
echo ""
echo "Enabling preprocessing tool sockets..."

for tool in office archive; do
    socket_name="tool-${tool}.socket"

    if systemctl --user is-enabled "$socket_name" &>/dev/null; then
        echo -e "${GREEN}OK${NC} $socket_name already enabled"
    else
        echo -e "${YELLOW}->${NC} Enabling $socket_name..."
        systemctl --user enable --now "$socket_name"
    fi
done

# Check OCR (optional, disabled by default)
if grep -q "ENABLE_OCR=true" .env 2>/dev/null; then
    echo -e "${YELLOW}->${NC} OCR is enabled in .env, enabling socket..."
    systemctl --user enable --now tool-ocr.socket
else
    echo -e "${BLUE}INFO${NC}  OCR disabled (ENABLE_OCR=false). Skipping tool-ocr.socket"
fi

# Check GPU (optional, disabled by default)
if grep -q "ENABLE_GPU_ACCELERATION=true" .env 2>/dev/null; then
    echo -e "${YELLOW}->${NC} GPU acceleration is enabled in .env, enabling socket..."
    systemctl --user enable --now tool-gpu.socket
else
    echo -e "${BLUE}INFO${NC}  GPU disabled (ENABLE_GPU_ACCELERATION=false). Skipping tool-gpu.socket"
fi

echo ""
echo "==================================================================="
echo ""

# Verify sockets are listening
echo "Verifying sockets are active..."
echo ""

if systemctl --user list-sockets | grep -q "tool-"; then
    systemctl --user list-sockets | grep "tool-" | while read line; do
        echo -e "${GREEN}OK${NC} $line"
    done
else
    echo -e "${RED}ERR${NC} No tool sockets found!"
    exit 1
fi

echo ""
echo "==================================================================="
echo ""

# Test tools (quick health check)
echo "Testing tool endpoints..."
echo ""

test_endpoint() {
    local name=$1
    local port=$2

    if curl -s -f -m 2 "http://127.0.0.1:${port}/healthz" >/dev/null 2>&1; then
        echo -e "${GREEN}OK${NC} ${name} responding on port ${port}"
        return 0
    else
        # First request might take time (container starting)
        echo -e "${YELLOW}->${NC} ${name} not responding yet (port ${port})"
        echo "   This is normal on first run. Container will start on first use."
        return 1
    fi
}

test_endpoint "tool-office " "9102"
test_endpoint "tool-archive" "9101"

if grep -q "ENABLE_OCR=true" .env 2>/dev/null; then
    test_endpoint "tool-ocr    " "9103"
fi

if grep -q "ENABLE_GPU_ACCELERATION=true" .env 2>/dev/null; then
    test_endpoint "tool-gpu    " "9104"
fi

echo ""
echo "==================================================================="
echo ""
echo -e "${GREEN}OK  Preprocessing tools setup complete!${NC}"
echo ""
echo "Configuration:"
echo "  - Office conversion: ENABLED  (DOCX/XLSX/PPTX -> TXT)"
echo "  - Archive extraction: ENABLED  (ZIP/7z/tar)"
echo "  - OCR: $(grep -q 'ENABLE_OCR=true' .env && echo 'ENABLED' || echo 'DISABLED') (change in .env)"
echo "  - GPU: $(grep -q 'ENABLE_GPU_ACCELERATION=true' .env && echo 'ENABLED' || echo 'DISABLED') (change in .env)"
echo ""
echo "Next steps:"
echo "  1. Run your ingestion: python -m src.main"
echo "  2. Files will be automatically preprocessed as needed"
echo "  3. First request to each tool will take 5-10s (container starts)"
echo "  4. Subsequent requests are instant (container stays running)"
echo ""
echo "To check tool status at any time:"
echo "  systemctl --user list-sockets | grep tool-"
echo ""
echo "To view tool logs:"
echo "  journalctl --user -u tool-office.service -f"
echo "  journalctl --user -u tool-archive.service -f"
echo ""

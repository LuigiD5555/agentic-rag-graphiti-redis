#!/bin/bash
# ============================================================================
# RAG Agentic Graphiti - Complete Setup & Start Script
# ============================================================================
# This script handles the full setup:
# 1. Verify dependencies
# 2. Build tool images (if missing)
# 3. Install and enable systemd sockets
# 4. Start core services (Weaviate, Neo4j, Redis)
# 5. Verify everything is running
# ============================================================================

set -e

# Wait time for services to respond (seconds)
SERVICE_WAIT_SECONDS=${SERVICE_WAIT_SECONDS:-30}
SERVICE_WAIT_INTERVAL=${SERVICE_WAIT_INTERVAL:-2}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Utility helpers
print_header() {
    echo ""
    echo -e "${BLUE}====================================================================${NC}"
    echo -e "${BLUE}${BOLD}$1${NC}"
    echo -e "${BLUE}====================================================================${NC}"
    echo ""
}

print_step() {
    echo -e "${CYAN}>${NC} ${BOLD}$1${NC}"
}

print_success() {
    echo -e "${GREEN}OK${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}WARN${NC} $1"
}

print_error() {
    echo -e "${RED}ERR${NC} $1"
}

print_info() {
    echo -e "${BLUE}INFO${NC} $1"
}

# ============================================================================
# STEP 1: VERIFY DEPENDENCIES
# ============================================================================

print_header "STEP 1: Verifying System Dependencies"

check_command() {
    if command -v "$1" &> /dev/null; then
        print_success "$1 installed"
        return 0
    else
        print_error "$1 NOT installed"
        return 1
    fi
}

deps_ok=true

print_step "Checking required commands..."
check_command podman || deps_ok=false
check_command systemctl || deps_ok=false
check_command curl || deps_ok=false
check_command python3 || deps_ok=false

if [ "$deps_ok" = false ]; then
    print_error "Missing dependencies. Please install the required packages."
    exit 1
fi

print_success "All dependencies are installed"

# ============================================================================
# STEP 2: BUILD TOOL IMAGES
# ============================================================================

print_header "STEP 2: Building Tool Images"

# Check if images already exist
if podman images | grep -q "rag-tool-office" && \
   podman images | grep -q "rag-tool-archive"; then
    print_success "Tool images are already built"
    read -p "Rebuild images? (y/N): " rebuild
    if [[ ! "$rebuild" =~ ^[yY]$ ]]; then
        print_info "Using existing images"
    else
        print_step "Rebuilding all images..."
        cd tools
        ./build-all.sh
        cd ..
    fi
else
    print_step "Building images for the first time..."
    print_warning "This can take 10-15 minutes..."
    cd tools
    ./build-all.sh
    cd ..
fi

# ============================================================================
# STEP 3: INSTALL AND ENABLE SYSTEMD SOCKETS
# ============================================================================

print_header "STEP 3: Configuring Systemd Sockets"

# Check if systemd units are already installed
if [ -f ~/.config/systemd/user/tool-office.socket ]; then
    print_success "Systemd units are already installed"
else
    print_step "Installing systemd units..."
    cd tools
    ./install-systemd.sh
    cd ..
fi

# Enable sockets
print_step "Enabling preprocessing sockets..."

for tool in office archive; do
    socket_name="tool-${tool}.socket"

    if systemctl --user is-enabled "$socket_name" &>/dev/null; then
        print_success "$socket_name is already enabled"
    else
        print_step "Enabling $socket_name..."
        systemctl --user enable --now "$socket_name"
        print_success "$socket_name enabled"
    fi
done

# OCR (optional)
if grep -q "ENABLE_OCR=true" .env 2>/dev/null; then
    print_step "Enabling OCR (detected in .env)..."
    systemctl --user enable --now tool-ocr.socket
else
    print_info "OCR disabled (ENABLE_OCR=false in .env)"
fi

# GPU (optional)
if grep -q "ENABLE_GPU_ACCELERATION=true" .env 2>/dev/null; then
    print_step "Enabling GPU (detected in .env)..."
    systemctl --user enable --now tool-gpu.socket
else
    print_info "GPU disabled (ENABLE_GPU_ACCELERATION=false in .env)"
fi

# ============================================================================
# STEP 4: START CORE SERVICES
# ============================================================================

print_header "STEP 4: Starting Core Services (Weaviate, Neo4j, Redis)"

print_step "Checking if services are already running..."

if podman ps | grep -q "weaviate\|neo4j\|redis"; then
    print_success "Core services are already running"
    read -p "Restart services? (y/N): " restart
    if [[ "$restart" =~ ^[yY]$ ]]; then
        print_step "Restarting services..."
        podman-compose down
        podman-compose up -d
    else
        print_info "Using existing services"
    fi
else
    print_step "Starting core services..."
    podman-compose up -d

    print_step "Waiting for services to be ready..."
    sleep 5
fi

# ============================================================================
# STEP 5: VERIFY THE SYSTEM
# ============================================================================

print_header "STEP 5: System Verification"

# Verify core services
print_step "Verifying core services..."

check_service() {
    local name=$1
    local port=$2
    local wait_enabled=${3:-yes}
    local deadline=$((SECONDS + SERVICE_WAIT_SECONDS))

    while true; do
        if curl -s -f -m 2 "http://localhost:${port}" >/dev/null 2>&1 || \
           curl -s -f -m 2 "http://localhost:${port}/v1/.well-known/ready" >/dev/null 2>&1; then
            print_success "$name responding on port $port"
            return 0
        fi

        if [ "$wait_enabled" = "no" ]; then
            print_warning "$name not responding on port $port (may still be starting...)"
            return 1
        fi

        if [ "$SECONDS" -ge "$deadline" ]; then
            print_warning "$name not responding on port $port after ${SERVICE_WAIT_SECONDS}s (may still be starting...)"
            return 1
        fi

        sleep "$SERVICE_WAIT_INTERVAL"
    done
}

print_info "Waiting up to ${SERVICE_WAIT_SECONDS}s for services..."
check_service "Weaviate" "8080"
check_service "Neo4j  " "7474"
check_service "Redis  " "6379" "no" || print_info "Redis has no HTTP endpoint (normal)"

# Verify sockets
print_step "Verifying preprocessing sockets..."

echo ""
if systemctl --user list-sockets | grep -q "tool-"; then
    systemctl --user list-sockets | grep "tool-" | while read line; do
        print_success "$line"
    done
else
    print_error "No tool sockets found"
fi

# Quick tool checks (does not wait for startup)
print_step "Testing tool endpoints (no startup wait)..."

test_tool_endpoint() {
    local name=$1
    local port=$2

    if curl -s -f -m 2 "http://127.0.0.1:${port}/healthz" >/dev/null 2>&1; then
        print_success "$name ready on port $port"
        return 0
    else
        print_info "$name on port $port (will start automatically when used)"
        return 1
    fi
}

test_tool_endpoint "tool-office " "9102"
test_tool_endpoint "tool-archive" "9101"

if grep -q "ENABLE_OCR=true" .env 2>/dev/null; then
    test_tool_endpoint "tool-ocr    " "9103"
fi

if grep -q "ENABLE_GPU_ACCELERATION=true" .env 2>/dev/null; then
    test_tool_endpoint "tool-gpu    " "9104"
fi

# ============================================================================
# STEP 6: SUMMARY AND NEXT STEPS
# ============================================================================

print_header "System Ready"

echo -e "${GREEN}${BOLD}OK: EVERYTHING IS CONFIGURED AND RUNNING${NC}"
echo ""
echo "==================================================================="
echo ""
echo -e "${BOLD}Core Services:${NC}"
echo "  - Weaviate: http://localhost:8080"
echo "  - Neo4j:    http://localhost:7474 (user: neo4j)"
echo "  - Redis:    localhost:6379"
echo ""
echo -e "${BOLD}Preprocessing Tools (Socket-Activated):${NC}"
echo "  - tool-office:  http://127.0.0.1:9102 (DOCX/XLSX/PPTX -> TXT)"
echo "  - tool-archive: http://127.0.0.1:9101 (ZIP/7z/tar)"
if grep -q "ENABLE_OCR=true" .env 2>/dev/null; then
echo "  - tool-ocr:     http://127.0.0.1:9103 (OCR with Tesseract)"
fi
if grep -q "ENABLE_GPU_ACCELERATION=true" .env 2>/dev/null; then
echo "  - tool-gpu:     http://127.0.0.1:9104 (GPU accelerated)"
fi
echo ""
echo "==================================================================="
echo ""
echo -e "${BOLD}Useful Commands:${NC}"
echo ""
echo -e "${CYAN}1. Run ingestion:${NC}"
echo "   python -m src.main"
echo "   ${YELLOW}-> DOCX, ZIP, etc. will be processed automatically${NC}"
echo ""
echo -e "${CYAN}2. Run a query:${NC}"
echo "   python -m src.rag.cli query \"your question here\""
echo ""
echo -e "${CYAN}3. View tool logs:${NC}"
echo "   journalctl --user -u tool-office.service -f"
echo "   journalctl --user -u tool-archive.service -f"
echo ""
echo -e "${CYAN}4. View service status:${NC}"
echo "   podman ps                                    # Core services"
echo "   systemctl --user list-sockets | grep tool-  # Tool sockets"
echo ""
echo -e "${CYAN}5. Stop everything:${NC}"
echo "   podman-compose down                          # Core services"
echo "   systemctl --user stop tool-*.service         # Tools (optional)"
echo ""
echo "==================================================================="
echo ""
echo -e "${BOLD}How Automatic Preprocessing Works:${NC}"
echo ""
echo "1. You run: ${CYAN}python -m src.main${NC}"
echo ""
echo "2. The pipeline discovers a file ${YELLOW}report.docx${NC}"
echo ""
echo "3. ${GREEN}Automatically:${NC}"
echo "   - Detects an Office file"
echo "   - Sends HTTP request to tool-office (127.0.0.1:9102)"
echo "   - systemd detects the socket request"
echo "   - systemd starts the container automatically (5-10s first time)"
echo "   - Container converts DOCX -> TXT"
echo "   - Pipeline processes the converted TXT"
echo ""
echo "4. ${CYAN}Next Office files:${NC} < 1 second (container already running)"
echo ""
echo "==================================================================="
echo ""
echo -e "${GREEN}${BOLD}Ready to use!${NC}"
echo ""
echo "Run ingestion now:"
echo -e "  ${CYAN}python -m src.main${NC}"
echo ""

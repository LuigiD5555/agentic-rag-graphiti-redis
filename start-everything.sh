#!/bin/bash
# ============================================================================
# RAG Agentic Graphiti - Complete Setup & Start Script
# ============================================================================
# This script handles the full setup:
# 1. Verify system dependencies
# 2. Build tool images (if missing)
# 3. Install and enable systemd sockets
# 4. Check and prepare volumes
# 5. Build and start all services (Weaviate, Neo4j, Redis, RAG API, Open WebUI)
# 6. Verify everything is running and run pre-flight checks
# 7. Display summary and next steps
# ============================================================================

set -e

# Ensure Podman Compose does not emit the Bake warning when we delegate.
export COMPOSE_BAKE=false

# Wait time for services to respond (seconds)
SERVICE_WAIT_SECONDS=${SERVICE_WAIT_SECONDS:-50}
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
        if ! python3 -m src.utils.tools.systemd_manager build; then
            print_error "Failed to build tool images"
            exit 1
        fi
    fi
else
    print_step "Building images for the first time..."
    print_warning "This can take 10-15 minutes..."
    if ! python3 -m src.utils.tools.systemd_manager build; then
        print_error "Failed to build tool images"
        exit 1
    fi
fi

# ============================================================================
# STEP 3: INSTALL AND ENABLE SYSTEMD SOCKETS
# ============================================================================

print_header "STEP 3: Configuring Systemd Sockets"

# Running inside a container? systemd --user sockets won't work here.
if [ -f "/.dockerenv" ] || grep -qE "(podman|docker|container)" /proc/1/cgroup 2>/dev/null; then
    print_warning "Detected container environment. systemd --user sockets must be configured on the host."
    print_info "Run this on the host instead:"
    print_info "  ./start-everything.sh"
    print_info "Or use Python:"
    print_info "  python -m src.utils.tools.systemd_manager install"
    print_info "  python -m src.utils.tools.systemd_manager enable"
else
    # Use Python module for systemd management
    print_step "Installing and enabling systemd sockets..."

    if ! python3 -m src.utils.tools.systemd_manager install; then
        print_error "Failed to install systemd units"
        exit 1
    fi

    if ! python3 -m src.utils.tools.systemd_manager enable; then
        print_error "Failed to enable sockets"
        exit 1
    fi

    # Apply timeout configuration from .env/settings.json to systemd services
    print_step "Applying tool timeout configuration..."
    if ! python3 -m src.utils.tools.timeout_manager apply -q; then
        print_warning "Could not apply timeout settings (continuing with defaults)"
    else
        print_success "Timeout configuration applied"
        # Reload systemd to pick up the updated service files
        systemctl --user daemon-reload
    fi

    print_success "Socket activation configured"
fi

# ============================================================================
# STEP 4: CHECK AND PREPARE VOLUMES
# ============================================================================

print_header "STEP 4: Checking and Preparing Volumes"

print_step "Verifying external volumes and setting up fallbacks if needed..."
if ! python3 -m pytest tests/infrastructure/test_volumes.py::TestVolumeIntegration::test_libros_volume_with_fallback_setup --setup-fallback -v -s; then
    print_error "Volume check failed"
    exit 1
fi

# Verify that volume configuration was written to .env
if grep -q "^ACTIVE_LIBROS_DIR=" .env 2>/dev/null; then
    print_success "Volume configuration written to .env"
else
    print_error "ACTIVE_LIBROS_DIR not found in .env - volume check may have failed"
    exit 1
fi

# ============================================================================
# STEP 5: BUILD AND START ALL SERVICES
# ============================================================================

print_header "STEP 5: Building and Starting All Services"

print_step "Checking if services are already running..."

if podman ps | grep -q "weaviate\|neo4j\|redis\|rag-api\|open-webui"; then
    print_success "Services are already running"
    read -p "Rebuild and restart all services? (y/N): " restart
    if [[ "$restart" =~ ^[yY]$ ]]; then
        print_step "Stopping all services..."
        podman-compose down

        print_step "Building custom images (rag-api)..."
        podman-compose build rag-api

        print_step "Starting all services..."
        podman-compose up -d

        print_step "Waiting for services to initialize..."
        sleep 10
    else
        print_info "Using existing services"
    fi
else
    print_step "Building custom images (rag-api)..."
    if ! podman-compose build rag-api; then
        print_error "Failed to build rag-api image"
        exit 1
    fi

    print_step "Starting all services (Weaviate, Neo4j, Redis, RAG API, Open WebUI)..."
    podman-compose up -d

    print_step "Waiting for services to initialize..."
    sleep 10
fi

# ============================================================================
# STEP 6: VERIFY THE SYSTEM
# ============================================================================

print_header "STEP 6: System Verification"

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
check_service "Weaviate  " "8080"
check_service "Neo4j     " "7474"
check_service "Redis     " "6379" "no" || print_info "Redis has no HTTP endpoint (normal)"
check_service "RAG API   " "8000"
check_service "Open WebUI" "5555"

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

# Run comprehensive pre-flight checks now that containers are running
print_step "Running comprehensive pre-flight checks..."

if python3 -c "import pytest" 2>/dev/null; then
    if ! python3 -m pytest tests/infrastructure/test_preflight.py -v --tb=short; then
        print_warning "Some pre-flight checks failed. Review the output above."
        print_info "System is running but may have configuration issues."
    else
        print_success "All pre-flight checks passed"
    fi
else
    print_warning "pytest not installed on host, skipping pre-flight checks"
    print_info "To run checks later: pip install pytest && pytest tests/infrastructure/test_preflight.py -v"
    print_info "Or run inside container: podman exec -it rag-api pytest tests/infrastructure/test_preflight.py -v"
fi

# ============================================================================
# STEP 7: SUMMARY AND NEXT STEPS
# ============================================================================

print_header "System Ready"

echo -e "${GREEN}${BOLD}OK: EVERYTHING IS CONFIGURED AND RUNNING${NC}"
echo ""
echo "==================================================================="
echo ""
echo -e "${BOLD}🌐 Web Interfaces:${NC}"
echo -e "  ${GREEN}${BOLD}➜ Open WebUI:${NC}  http://localhost:5555"
echo "    └─ ChatGPT-like interface for your RAG system"
echo ""
echo -e "  ${CYAN}➜ RAG API:${NC}     http://localhost:8000"
echo "    ├─ Docs:      http://localhost:8000/docs"
echo "    ├─ Health:    http://localhost:8000/health"
echo "    └─ Ollama-compatible endpoints at /api/*"
echo ""
echo -e "${BOLD}Database Services:${NC}"
echo "  - Weaviate:    http://localhost:8080 (Vector DB)"
echo "  - Neo4j:       http://localhost:7474 (Graph DB, user: neo4j)"
echo "  - Redis:       localhost:6379 (Cache)"
echo ""
echo -e "${BOLD}Preprocessing Tools (Socket-Activated):${NC}"
echo "  - tool-office:  http://127.0.0.1:9102 (DOCX/XLSX/PPTX → TXT)"
echo "  - tool-archive: http://127.0.0.1:9101 (ZIP/7z/tar extraction)"
if grep -q "ENABLE_OCR=true" .env 2>/dev/null; then
echo "  - tool-ocr:     http://127.0.0.1:9103 (OCR with Tesseract)"
fi
if grep -q "ENABLE_GPU_ACCELERATION=true" .env 2>/dev/null; then
echo "  - tool-gpu:     http://127.0.0.1:9104 (GPU accelerated)"
fi
echo ""
echo "==================================================================="
echo ""
echo -e "${BOLD}Quick Start:${NC}"
echo ""
echo -e "${CYAN}➜ Use the Web Interface (Recommended):${NC}"
echo -e "   Open: ${GREEN}${BOLD}http://localhost:5555${NC}"
echo "   - Create an account (local only, no data leaves your machine)"
echo "   - Start chatting with your RAG system"
echo "   - Upload documents, ask questions, view sources"
echo ""
echo -e "${CYAN}➜ Use the API directly:${NC}"
echo "   curl -X POST http://localhost:8000/api/chat \\"
echo "     -H \"Content-Type: application/json\" \\"
echo "     -d '{\"model\": \"rag\", \"messages\": [{\"role\": \"user\", \"content\": \"hello\"}]}'"
echo ""
echo -e "${CYAN}➜ Run ingestion (Terminal):${NC}"
echo "   python -m src.main"
echo "   ${YELLOW}→ DOCX, ZIP, etc. will be processed automatically${NC}"
echo ""
echo -e "${CYAN}➜ Run a query (Terminal):${NC}"
echo "   python -m src.query.cli \"your question here\""
echo ""
echo "==================================================================="
echo ""
echo -e "${BOLD}Monitoring & Management:${NC}"
echo ""
echo -e "${CYAN}View service status:${NC}"
echo "   podman ps                                    # All running containers"
echo "   podman-compose logs -f rag-api               # RAG API logs"
echo "   podman-compose logs -f open-webui            # Web interface logs"
echo "   systemctl --user list-sockets | grep tool-   # Tool sockets"
echo ""
echo -e "${CYAN}View tool logs:${NC}"
echo "   journalctl --user -u tool-office.service -f"
echo "   journalctl --user -u tool-archive.service -f"
echo ""
echo -e "${CYAN}Stop everything:${NC}"
echo "   podman-compose down                          # All services"
echo "   systemctl --user stop tool-*.service         # Tools (optional)"
echo ""
echo "==================================================================="
echo ""
echo -e "${GREEN}${BOLD}✓ System is ready to use!${NC}"
echo ""
echo -e "Start using your RAG system now:"
echo -e "  ${GREEN}${BOLD}→ Open http://localhost:5555 in your browser${NC}"
echo ""

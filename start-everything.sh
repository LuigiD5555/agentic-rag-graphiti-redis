#!/bin/bash
# ============================================================================
# RAG Agentic Graphiti - Complete Setup & Start Script
# ============================================================================
# This script handles the full setup:
# 1. Verify system dependencies
# 2. Build tool images (if missing)
# 3. Install and enable systemd sockets
# 4. Check and prepare volumes
# 5. Build and start all services (Weaviate, Neo4j, Redis, App, Open WebUI, Monitoring)
# 6. Verify everything is running and run pre-flight checks
# 7. Display summary and next steps
# ============================================================================

set -e

# Prefer the project's virtual environment python if available.
PYTHON_CMD="${PYTHON_CMD:-python3}"
if [ -x "./.venv/bin/python" ]; then
    PYTHON_CMD="./.venv/bin/python"
elif [ -x "./.venv/bin/python3" ]; then
    PYTHON_CMD="./.venv/bin/python3"
fi

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
if podman images | grep -q "rag-tool-document-processor" && \
   podman images | grep -q "rag-tool-extractor"; then
    print_success "Tool images are already built"
    read -p "Rebuild images? (y/N): " rebuild
    if [[ ! "$rebuild" =~ ^[yY]$ ]]; then
        print_info "Using existing images"
    else
        print_step "Rebuilding all images..."
        if ! "$PYTHON_CMD" -m src.utils.tools.systemd_manager build --tools extractor document-processor websearch; then
            print_error "Failed to build tool images"
            exit 1
        fi
    fi
else
    print_step "Building images for the first time..."
    print_warning "This can take 10-15 minutes..."
    if ! "$PYTHON_CMD" -m src.utils.tools.systemd_manager build --tools extractor document-processor websearch; then
        print_error "Failed to build tool images"
        exit 1
    fi
fi

# ============================================================================
# STEP 3: INSTALL AND ENABLE SYSTEMD SOCKETS
# ============================================================================

# Leer configuración de auto-inicio desde .env
RAG_AUTOSTART_CONFIG="true"
if [ -f ".env" ]; then
    RAG_AUTOSTART_CONFIG="$(grep -E "^RAG_AUTOSTART=" .env | tail -n 1 | cut -d '=' -f2- | tr -d '\"' || echo "true")"
fi

export RAG_AUTOSTART="$RAG_AUTOSTART_CONFIG"

print_header "STEP 3: Configuring Systemd Sockets"
print_info "Configuración de auto-inicio: RAG_AUTOSTART=$RAG_AUTOSTART_CONFIG"

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

    if ! "$PYTHON_CMD" -m src.utils.tools.systemd_manager install; then
        print_error "Failed to install systemd units"
        exit 1
    fi

    # Do not enable sockets on boot; start them only for this session.
    print_step "Disabling tool sockets autostart..."
    systemctl --user disable --now tool-extractor.socket || true
    systemctl --user disable --now tool-document-processor.socket || true
    systemctl --user disable --now tool-websearch.socket || true

    print_step "Enabling tool sockets for this session..."
    RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    mkdir -p "$RUNTIME_DIR"
    touch "$RUNTIME_DIR/rag-tools-enabled"

    SOCKET_START_TIME="$(date --iso-8601=seconds)"

    print_step "Starting tool sockets (on-demand for this session only)..."
    systemctl --user daemon-reload || true
    systemctl --user start tool-extractor.socket || true
    systemctl --user start tool-document-processor.socket || true
    systemctl --user start tool-websearch.socket || true

    print_step "Checking tool sockets..."
    if systemctl --user list-sockets | grep -q "tool-"; then
        systemctl --user list-sockets | grep "tool-" | while read line; do
            print_success "$line"
        done
    else
        print_warning "No tool sockets reported by systemd"
    fi

    if ! systemctl --user is-enabled tool-extractor.socket >/dev/null 2>&1; then
        print_warning "tool-extractor.socket is not enabled. Diagnostics:"
        systemctl --user status tool-extractor.socket --no-page --lines=8 || true
        journalctl --user -u tool-extractor.socket --no-pager --since "$SOCKET_START_TIME" -n 30 || true
        print_warning "Attempting to start tool-extractor.socket anyway..."
        systemctl --user start tool-extractor.socket || true
    fi

    # Apply timeout configuration from .env/settings.json to systemd services
    print_step "Applying tool timeout configuration..."
    if ! "$PYTHON_CMD" -m src.utils.tools.timeout_manager apply -q; then
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
if ! "$PYTHON_CMD" -m pytest tests/infrastructure/test_volumes.py::TestVolumeIntegration::test_libros_volume_with_fallback_setup --setup-fallback -v -s; then
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

# Also verify volume compose generator configuration
if [ -f "src/utils/volume_compose_generator.py" ]; then
    print_step "Volume compose generator found, configuration available"
fi

# ============================================================================
# STEP 5: BUILD AND START ALL SERVICES
# ============================================================================

print_header "STEP 5: Building and Starting All Services"

print_step "Checking if services are already running..."

if podman ps | grep -q "weaviate\|neo4j\|redis\|app\|open-webui\|monitoring"; then
    print_success "Services are already running"
    read -p "Rebuild and restart all services? (y/N): " restart
    if [[ "$restart" =~ ^[yY]$ ]]; then
        print_step "Stopping all services..."
        podman-compose down

        print_step "Building custom images..."

        if ! podman-compose build app monitoring; then
            print_error "Failed to build app/monitoring images"
            exit 1
        fi

        # Build open-webui only if profile is enabled
        print_step "Checking if open-webui should be built..."
        if podman-compose config --services | grep -q "open-webui"; then
            if ! podman-compose --profile webui build open-webui; then
                print_warning "Failed to build open-webui image (continuing without it)"
            else
                print_success "open-webui image built"
            fi
        else
            print_info "open-webui service not available (profile not enabled)"
        fi

        print_step "Starting all services..."
        if podman-compose config --services | grep -q "open-webui"; then
            podman-compose --profile webui up -d
        else
            podman-compose up -d
        fi

        print_step "Waiting for services to initialize..."
        sleep 10
    else
        print_info "Using existing services"
    fi
else
    print_step "Building custom images..."

    if ! podman-compose build app monitoring; then
        print_error "Failed to build app/monitoring images"
        exit 1
    fi

    # Build open-webui only if profile is enabled
    print_step "Checking if open-webui should be built..."
    if podman-compose config --services | grep -q "open-webui"; then
        if ! podman-compose --profile webui build open-webui; then
            print_warning "Failed to build open-webui image (continuing without it)"
        else
            print_success "open-webui image built"
        fi
    else
        print_info "open-webui service not available (profile not enabled)"
    fi

    print_step "Starting all services (Weaviate, Neo4j, Redis, App, Open WebUI, Monitoring, RabbitMQ)..."
    if podman-compose config --services | grep -q "open-webui"; then
        podman-compose --profile webui up -d
    else
        podman-compose up -d
    fi

    print_step "Waiting for services to initialize..."
    sleep 10
fi

# ============================================================================
# STEP 5.5: START TOOL SERVICES
# ============================================================================

print_header "STEP 5.5: Starting Tool Services"

print_step "Starting tool services via systemd..."
if command -v systemctl >/dev/null 2>&1; then
    # Solo habilitar servicios si RAG_AUTOSTART=true
    if [ "$RAG_AUTOSTART_CONFIG" = "true" ]; then
        print_info "Auto-inicio habilitado - Configurando servicios para inicio automático"
        
        # Start Open WebUI service (independent)
        if [ -f "/home/luiginorp/.config/systemd/user/rag-tool-ui.service" ]; then
            print_step "Configurando Open WebUI para inicio automático..."
            systemctl --user daemon-reload
            systemctl --user enable --now rag-tool-ui.service || print_warning "Failed to start rag-tool-ui.service"
        fi
        
        # Start tool sockets (will activate services on-demand)
        print_step "Configurando tool sockets para inicio automático..."
        systemctl --user daemon-reload
        systemctl --user enable --now tool-extractor.socket || print_warning "Failed to start tool-extractor.socket"
        systemctl --user enable --now tool-document-processor.socket || print_warning "Failed to start tool-document-processor.socket"
        systemctl --user enable --now tool-websearch.socket || print_warning "Failed to start tool-websearch.socket"
        
        print_success "Servicios configurados para inicio automático"
    else
        print_info "Auto-inicio deshabilitado - Solo iniciando servicios para esta sesión"
        
        # Solo iniciar servicios para esta sesión, sin habilitarlos en el arranque
        if [ -f "/home/luiginorp/.config/systemd/user/rag-tool-ui.service" ]; then
            print_step "Iniciando Open WebUI para esta sesión..."
            systemctl --user daemon-reload
            systemctl --user start rag-tool-ui.service || print_warning "Failed to start rag-tool-ui.service"
        fi
        
        print_step "Iniciando tool sockets para esta sesión..."
        systemctl --user daemon-reload
        systemctl --user start tool-extractor.socket || print_warning "Failed to start tool-extractor.socket"
        systemctl --user start tool-document-processor.socket || print_warning "Failed to start tool-document-processor.socket"
        systemctl --user start tool-websearch.socket || print_warning "Failed to start tool-websearch.socket"
        
        print_success "Servicios iniciados para esta sesión (no se iniciarán automáticamente en el arranque)"
    fi
else
    print_warning "systemctl not available; tool services must be started manually"
fi

# ============================================================================
# STEP 5.6: OPTIONAL DEBUG CONTAINER
# ============================================================================

print_header "STEP 5.6: Optional Debug Container"

DEBUG_COMPOSE_FILE="tools/debug/podman-compose.debug.yml"
if [ -f "$DEBUG_COMPOSE_FILE" ]; then
    if ! read -r -t 10 -p "Start debug container (on-demand tools)? (y/N): " start_debug; then
        echo ""
        start_debug="n"
    fi
    if [[ "$start_debug" =~ ^[yY]$ ]]; then
        print_step "Starting debug container..."
        if ! podman-compose -f "$DEBUG_COMPOSE_FILE" up -d; then
            print_warning "Failed to start debug container (continuing)"
        else
            print_success "Debug container started"
        fi
    else
        print_info "Skipping debug container (on-demand)"
    fi
else
    print_warning "Debug compose file not found: $DEBUG_COMPOSE_FILE"
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
    local protocol=${4:-http}
    local deadline=$((SECONDS + SERVICE_WAIT_SECONDS))

    while true; do
        if [ "$protocol" = "tcp" ]; then
            if timeout 2 bash -c "cat < /dev/tcp/localhost:${port}" >/dev/null 2>&1; then
                print_success "$name responding on TCP port $port"
                return 0
            fi
        else
            if curl -s -f -m 2 "http://localhost:${port}" >/dev/null 2>&1 || \
               curl -s -f -m 2 "http://localhost:${port}/v1/.well-known/ready" >/dev/null 2>&1; then
                print_success "$name responding on port $port"
                return 0
            fi
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
check_service "Redis     " "6379" "no" "tcp" || print_info "Redis has no HTTP endpoint (normal)"
check_service "RAG API   " "8000"

if curl -s -f -m 2 "http://localhost:5555/health" >/dev/null 2>&1; then
    print_success "Open WebUI responding on port 5555"
else
    print_warning "Open WebUI not responding on port 5555 (may still be starting...)"
fi

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

test_tool_endpoint "tool-extractor (extractor)" "9101"
test_tool_endpoint "tool-docproc" "9106"

# Run comprehensive pre-flight checks now that containers are running
print_step "Running comprehensive pre-flight checks..."

if "$PYTHON_CMD" -c "import pytest" 2>/dev/null; then
    if ! "$PYTHON_CMD" -m pytest tests/infrastructure/test_preflight.py -v --tb=short; then
        print_warning "Some pre-flight checks failed. Review the output above."
        print_info "System is running but may have configuration issues."
    else
        print_success "All pre-flight checks passed"
    fi
else
    print_warning "pytest not installed on host, skipping pre-flight checks"
    print_info "To run checks later: pip install pytest && pytest tests/infrastructure/test_preflight.py -v"
    print_info "Or run inside container: podman exec -it app pytest tests/infrastructure/test_preflight.py -v"
fi

# ============================================================================
# STEP 7: SUMMARY AND NEXT STEPS
# ============================================================================

print_header "System Ready"

echo -e "${GREEN}${BOLD}OK: EVERYTHING IS CONFIGURED AND RUNNING${NC}"
echo ""
echo "==================================================================="
echo ""
echo -e "${BOLD}[Globe With Meridians] Web Interfaces:${NC}"
echo -e "  ${CYAN}${BOLD}[Heavy Round-Tipped Rightwards Arrow] RAG API:${NC}     http://localhost:8000"
echo "    ├─ Docs:      http://localhost:8000/docs"
echo "    ├─ Health:    http://localhost:8000/health"
echo "    └─ Ollama-compatible endpoints at /api/*"
echo ""
echo -e "  ${CYAN}[Heavy Round-Tipped Rightwards Arrow] Open WebUI:${NC}  http://localhost:5555"
echo ""
echo -e "${BOLD}Database Services:${NC}"
echo "  - Weaviate:    http://localhost:8080 (Vector DB)"
echo "  - Neo4j:       http://localhost:7474 (Graph DB, user: neo4j)"
echo "  - Redis:       localhost:6379 (Cache)"
echo "  - RabbitMQ:    http://localhost:15672 (Message Queue, user: admin/change-me-rabbitmq)"
echo ""
echo -e "${BOLD}Preprocessing Tools (Socket-Activated):${NC}"
echo "  - tool-extractor (extractor): http://127.0.0.1:9101 (ZIP/7z/tar extraction)"
echo "  - tool-docproc: http://127.0.0.1:9106 (OCR + Office unified)"
echo ""
echo "==================================================================="
echo ""
echo -e "${BOLD}Quick Start:${NC}"
echo ""
echo -e "${CYAN}[Heavy Round-Tipped Rightwards Arrow] Use the API directly:${NC}"
echo "   curl -X POST http://localhost:8000/api/chat \\"
echo "     -H \"Content-Type: application/json\" \\"
echo "     -d '{\"model\": \"rag\", \"messages\": [{\"role\": \"user\", \"content\": \"hello\"}]}'"
echo ""
echo -e "${CYAN}[Heavy Round-Tipped Rightwards Arrow] Run ingestion (Terminal):${NC}"
echo "   python -m src.main"
echo "   ${YELLOW}→ DOCX, ZIP, etc. will be processed automatically${NC}"
echo ""
echo -e "${CYAN}[Heavy Round-Tipped Rightwards Arrow] Run a query (Terminal):${NC}"
echo "   python -m src.query.cli \"your question here\""
echo ""
echo "==================================================================="
echo ""
echo -e "${BOLD}Monitoring & Management:${NC}"
echo ""
echo -e "${CYAN}View service status:${NC}"
echo "   podman ps                                    # All running containers"
echo "   podman-compose logs -f app                   # RAG API logs"
echo "   podman-compose logs -f open-webui            # Web UI logs"
echo ""
echo "   podman-compose logs -f monitoring            # Monitoring logs"
echo "   systemctl --user list-sockets | grep tool-   # Tool sockets"
echo ""
echo -e "${CYAN}View tool logs:${NC}"
echo "   journalctl --user -u tool-document-processor.service -f"
echo "   journalctl --user -u tool-extractor.service -f"
echo ""
echo -e "${CYAN}Stop everything:${NC}"
echo "   podman-compose down                          # All services"
echo "   systemctl --user stop tool-*.service         # Tools (optional)"
echo ""
echo "==================================================================="
echo ""
echo -e "${GREEN}${BOLD}✓ System is ready to use!${NC}"
echo ""

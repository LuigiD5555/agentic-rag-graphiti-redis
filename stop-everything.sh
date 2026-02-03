#!/bin/bash
# ============================================================================
# RAG Agentic Graphiti - Stop & Cleanup Script
# ============================================================================
# Stops all services started by start-everything.sh and cleans project containers.
# - Does NOT remove images
# - Volume cleanup is optional (--volumes)
# ============================================================================

set -e

# Use the explicitly provided Python, otherwise default to system python3.
PYTHON_CMD="${PYTHON_CMD:-python3}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

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

get_env_value() {
    local key="$1"
    if [ -f ".env" ]; then
        local value
        value="$(grep -E "^${key}=" .env | tail -n 1 | cut -d '=' -f2- | tr -d '\"' || true)"
        if [ -n "$value" ]; then
            echo "$value"
            return 0
        fi
    fi
    return 1
}

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$(get_env_value COMPOSE_PROJECT_NAME)}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-rag-graphiti-agentic}"

REMOVE_VOLUMES=false

usage() {
    cat <<EOF
Usage: ./stop-everything.sh [--volumes]

Options:
  --volumes    Remove project volumes (optional)
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --volumes|-v)
            REMOVE_VOLUMES=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

print_header "STOPPING SERVICES AND CLEANING PROJECT CONTAINERS"

print_step "Stopping podman-compose services..."
if [ "$REMOVE_VOLUMES" = true ]; then
    podman-compose down -v || print_warning "podman-compose down failed (continuing)"
else
    podman-compose down || print_warning "podman-compose down failed (continuing)"
fi

DEBUG_COMPOSE_FILE="tools/debug/podman-compose.debug.yml"
if [ -f "$DEBUG_COMPOSE_FILE" ]; then
    print_step "Stopping debug compose services..."
    podman-compose -f "$DEBUG_COMPOSE_FILE" down || print_warning "Debug compose down failed"
fi

print_step "Stopping systemd tool sockets/services (if available)..."
if command -v systemctl >/dev/null 2>&1; then
    # Stop Open WebUI service
    systemctl --user stop rag-tool-ui.service 2>/dev/null || true
    systemctl --user disable rag-tool-ui.service 2>/dev/null || true
    systemctl --user reset-failed rag-tool-ui.service 2>/dev/null || true
    
    # Stop tool sockets and services
    TOOLS=(
        document-processor
        extractor
        websearch
        ocr
        llm
        gpu
        archive
    )
    for tool in "${TOOLS[@]}"; do
        systemctl --user stop "tool-${tool}.socket" "tool-${tool}.service" 2>/dev/null || true
        systemctl --user disable "tool-${tool}.socket" "tool-${tool}.service" 2>/dev/null || true
        systemctl --user reset-failed "tool-${tool}.service" 2>/dev/null || true
    done

    RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    rm -f "$RUNTIME_DIR/rag-tools-enabled"
else
    print_warning "systemctl not available; skipping systemd stop"
fi

print_step "Removing project containers (by label/name)..."
project_label="io.podman.compose.project=${COMPOSE_PROJECT_NAME}"
container_ids="$(podman ps -a --filter "label=${project_label}" --format "{{.ID}}" || true)"
if [ -n "$container_ids" ]; then
    echo "$container_ids" | xargs -r podman rm -f
fi

name_prefix="${COMPOSE_PROJECT_NAME}_"
extra_ids="$(podman ps -a --format "{{.ID}} {{.Names}}" | awk -v p="$name_prefix" '$2 ~ "^"p {print $1}' || true)"
if [ -n "$extra_ids" ]; then
    echo "$extra_ids" | xargs -r podman rm -f
fi

print_step "Removing tool containers (if present)..."
for tool in rag-tool-document-processor rag-tool-extractor rag-tool-websearch rag-tool-ocr rag-tool-archive rag-tool-ui; do
    if podman ps -a --format "{{.Names}}" | grep -q "^${tool}$"; then
        podman rm -f "$tool" || true
    fi
done

print_step "Checking for orphaned processes..."
# Kill any remaining processes that might be related to the project
if command -v pkill >/dev/null 2>&1; then
    # Look for processes with project-related names
    for proc_name in weaviate neo4j rabbitmq rag-agentic open-webui; do
        pkill -f "$proc_name" 2>/dev/null || true
    done
    # Give processes time to terminate
    sleep 2
fi

print_step "Removing project pods (if present)..."
pod_ids="$(podman pod ps --format "{{.Id}} {{.Name}}" | awk -v p="$name_prefix" '$2 ~ "^"p {print $1}' || true)"
if [ -n "$pod_ids" ]; then
    echo "$pod_ids" | xargs -r podman pod rm -f
fi

if [ "$REMOVE_VOLUMES" = true ]; then
    print_step "Removing project volumes..."
    volume_ids="$(podman volume ls --filter "label=${project_label}" --format "{{.Name}}" || true)"
    if [ -n "$volume_ids" ]; then
        echo "$volume_ids" | xargs -r podman volume rm
    fi

    volume_prefix="${COMPOSE_PROJECT_NAME}_"
    extra_vols="$(podman volume ls --format "{{.Name}}" | awk -v p="$volume_prefix" '$1 ~ "^"p {print $1}' || true)"
    if [ -n "$extra_vols" ]; then
        echo "$extra_vols" | xargs -r podman volume rm
    fi
fi

print_success "Stop and cleanup completed (images preserved)."

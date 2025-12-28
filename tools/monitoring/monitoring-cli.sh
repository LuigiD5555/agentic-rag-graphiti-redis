#!/bin/bash
# Monitoring CLI - Wrapper script for monitoring container operations

set -e

COMPOSE_FILE="${COMPOSE_FILE:-podman-compose.yml}"
CONTAINER_NAME="${COMPOSE_PROJECT_NAME:-rag-graphiti-agentic}_monitoring_1"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

success() {
    echo -e "${GREEN}✓${NC} $1"
}

warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

error() {
    echo -e "${RED}✗${NC} $1"
}

# Check if monitoring container is running
check_container() {
    if ! podman ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        error "Monitoring container is not running"
        info "Start it with: podman-compose up -d monitoring"
        exit 1
    fi
}

# Show usage
usage() {
    cat << EOF
${BLUE}Monitoring CLI${NC} - Manage RAG monitoring container

${YELLOW}Usage:${NC}
    $0 <command> [options]

${YELLOW}Commands:${NC}

  ${GREEN}Container Management:${NC}
    start                  Start monitoring container
    stop                   Stop monitoring container
    restart                Restart monitoring container
    logs [-f]             View container logs
    shell                  Interactive shell in container
    status                 Show container status

  ${GREEN}Log Analysis:${NC}
    analyze [OPTIONS]      Analyze logs
      --since TIME         Time range (e.g., "1 week ago", "24 hours ago")
      --tool TOOL          Specific tool (office, archive, ocr, gpu)
      --format FORMAT      Output format (text, json)
      --all                Analyze all tools

  ${GREEN}Verification:${NC}
    verify [--json]        Verify setup and configuration
    diagnose               Run full diagnostic suite
    verify-data            Verify Weaviate data
    health                 Check service health

  ${GREEN}Volume Monitoring:${NC}
    volumes                Check volume status
    watch-volumes          Monitor volumes continuously

  ${GREEN}Reports:${NC}
    reports list           List generated reports
    reports view REPORT    View specific report
    reports clean          Clean old reports

${YELLOW}Examples:${NC}
    # Analyze logs from last 24 hours
    $0 analyze --since "24 hours ago"

    # Verify setup and export to JSON
    $0 verify --json > setup-status.json

    # Run diagnostics
    $0 diagnose

    # Watch logs in real-time
    $0 logs -f

    # Interactive shell
    $0 shell

EOF
    exit 0
}

# Command implementations
cmd_start() {
    info "Starting monitoring container..."
    podman-compose up -d monitoring
    success "Monitoring container started"
}

cmd_stop() {
    info "Stopping monitoring container..."
    podman-compose stop monitoring
    success "Monitoring container stopped"
}

cmd_restart() {
    info "Restarting monitoring container..."
    podman-compose restart monitoring
    success "Monitoring container restarted"
}

cmd_logs() {
    check_container
    podman-compose logs "$@" monitoring
}

cmd_shell() {
    check_container
    info "Opening shell in monitoring container..."
    podman exec -it "$CONTAINER_NAME" /bin/bash
}

cmd_status() {
    info "Monitoring container status:"
    echo ""
    if podman ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        success "Running"
        podman ps --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
        warning "Not running"
    fi
}

cmd_analyze() {
    check_container
    info "Running log analysis..."
    podman exec "$CONTAINER_NAME" /entrypoint.sh logs "$@"
}

cmd_verify() {
    check_container
    info "Running setup verification..."
    podman exec "$CONTAINER_NAME" /entrypoint.sh verify "$@"
}

cmd_diagnose() {
    check_container
    info "Running diagnostics..."
    podman exec "$CONTAINER_NAME" /entrypoint.sh diagnose
}

cmd_verify_data() {
    check_container
    info "Verifying Weaviate data..."
    podman exec "$CONTAINER_NAME" /entrypoint.sh verify-data
}

cmd_health() {
    check_container
    info "Checking service health..."

    # Get latest health report
    podman exec "$CONTAINER_NAME" bash -c '
        if [ -f /app/reports/health_*.json ]; then
            latest=$(ls -t /app/reports/health_*.json | head -1)
            cat "$latest" | python3 -m json.tool
        else
            echo "No health reports found yet. Wait for first monitoring cycle."
        fi
    '
}

cmd_volumes() {
    check_container
    info "Checking volume status..."
    podman exec "$CONTAINER_NAME" /entrypoint.sh volumes
}

cmd_watch_volumes() {
    check_container
    info "Monitoring volumes (Ctrl+C to stop)..."
    podman exec -it "$CONTAINER_NAME" /entrypoint.sh volumes
}

cmd_reports_list() {
    check_container
    info "Generated reports:"
    echo ""
    podman exec "$CONTAINER_NAME" bash -c '
        echo "Health Reports:"
        ls -lh /app/reports/health_*.json 2>/dev/null | tail -10 || echo "  None"
        echo ""
        echo "Log Analysis Reports:"
        ls -lh /app/reports/logs_*.json 2>/dev/null | tail -10 || echo "  None"
    '
}

cmd_reports_view() {
    check_container
    local report="$1"

    if [ -z "$report" ]; then
        error "Please specify a report file"
        exit 1
    fi

    info "Viewing report: $report"
    podman exec "$CONTAINER_NAME" cat "/app/reports/$report" | python3 -m json.tool
}

cmd_reports_clean() {
    check_container
    warning "This will delete old reports (>30 days)"
    read -p "Continue? (y/N) " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        info "Cleaning old reports..."
        podman exec "$CONTAINER_NAME" bash -c '
            find /app/reports -type f -name "*.json" -mtime +30 -delete
            echo "Cleaned reports older than 30 days"
        '
        success "Done"
    else
        info "Cancelled"
    fi
}

# Main command dispatcher
main() {
    if [ $# -eq 0 ]; then
        usage
    fi

    case "$1" in
        start)
            shift
            cmd_start "$@"
            ;;
        stop)
            shift
            cmd_stop "$@"
            ;;
        restart)
            shift
            cmd_restart "$@"
            ;;
        logs)
            shift
            cmd_logs "$@"
            ;;
        shell)
            shift
            cmd_shell "$@"
            ;;
        status)
            shift
            cmd_status "$@"
            ;;
        analyze)
            shift
            cmd_analyze "$@"
            ;;
        verify)
            shift
            cmd_verify "$@"
            ;;
        diagnose)
            shift
            cmd_diagnose "$@"
            ;;
        verify-data)
            shift
            cmd_verify_data "$@"
            ;;
        health)
            shift
            cmd_health "$@"
            ;;
        volumes)
            shift
            cmd_volumes "$@"
            ;;
        watch-volumes)
            shift
            cmd_watch_volumes "$@"
            ;;
        reports)
            shift
            case "$1" in
                list)
                    shift
                    cmd_reports_list "$@"
                    ;;
                view)
                    shift
                    cmd_reports_view "$@"
                    ;;
                clean)
                    shift
                    cmd_reports_clean "$@"
                    ;;
                *)
                    error "Unknown reports command: $1"
                    usage
                    ;;
            esac
            ;;
        help|--help|-h)
            usage
            ;;
        *)
            error "Unknown command: $1"
            usage
            ;;
    esac
}

main "$@"

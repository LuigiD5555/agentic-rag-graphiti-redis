#!/bin/bash
# Monitoring CLI for RAG Agentic Graphiti

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MONITORING_DIR="$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Python is available
check_python() {
    if ! command -v python3 &> /dev/null; then
        log_error "Python3 is not installed"
        exit 1
    fi
}

# Check if required packages are installed
check_dependencies() {
    log_info "Checking dependencies..."
    
    # Check coverage
    if ! python3 -c "import coverage" 2>/dev/null; then
        log_warning "coverage package not found. Installing..."
        pip install coverage
    fi
    
    # Check vulture
    if ! python3 -c "import vulture" 2>/dev/null; then
        log_warning "vulture package not found. Installing..."
        pip install vulture
    fi
    
    # Check astor
    if ! python3 -c "import astor" 2>/dev/null; then
        log_warning "astor package not found. Installing..."
        pip install astor
    fi
}

# Run bloat analysis
run_bloat_analysis() {
    log_info "Running bloat analysis..."
    
    cd "$PROJECT_ROOT"
    
    python3 -m tools.monitoring.src.bloat_analyzer
    
    if [ $? -eq 0 ]; then
        log_success "Bloat analysis completed"
        echo "Reports available in: /app/reports/bloat/"
    else
        log_error "Bloat analysis failed"
        exit 1
    fi
}

# Start real-time monitoring
start_realtime_monitoring() {
    log_info "Starting real-time monitoring..."
    
    cd "$PROJECT_ROOT"
    
    python3 -m tools.monitoring.src.realtime_monitor start
    
    if [ $? -eq 0 ]; then
        log_success "Real-time monitoring started"
        echo "Monitoring coverage across all pipelines..."
        echo "Press Ctrl+C to stop and generate report"
    else
        log_error "Failed to start real-time monitoring"
        exit 1
    fi
}

# Stop real-time monitoring
stop_realtime_monitoring() {
    log_info "Stopping real-time monitoring..."
    
    cd "$PROJECT_ROOT"
    
    python3 -m tools.monitoring.src.realtime_monitor stop
    
    if [ $? -eq 0 ]; then
        log_success "Real-time monitoring stopped"
        echo "Reports available in: /app/reports/realtime/"
    else
        log_error "Failed to stop real-time monitoring"
        exit 1
    fi
}

# Generate report from existing data
generate_report() {
    local format="$1"
    
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

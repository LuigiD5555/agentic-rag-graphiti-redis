#!/bin/bash
# Monitoring Container Entry Point

set -e

MODE="${1:-daemon}"

echo "=========================================="
echo "RAG Monitoring Container"
echo "=========================================="
echo "Mode: $MODE"
echo ""

case "$MODE" in
    daemon)
        echo "Starting monitoring daemon..."
        exec python -m src.monitor_daemon
        ;;

    logs)
        echo "Running log analysis..."
        shift
        exec python -m src.utils.tools.analyze_logs "$@"
        ;;

    verify)
        echo "Running setup verification..."
        shift
        exec python -m src.utils.tools.setup_verifier "$@"
        ;;

    volumes)
        echo "Monitoring volumes..."
        exec python -m src.volume_monitor_service
        ;;

    dashboard)
        echo "Starting web dashboard on port 8888..."
        exec python -m src.dashboard
        ;;

    shell)
        echo "Starting interactive shell..."
        exec /bin/bash
        ;;

    *)
        echo "Unknown mode: $MODE"
        echo ""
        echo "Available modes:"
        echo "  daemon          - Run monitoring daemon (default)"
        echo "  logs [ARGS]     - Analyze logs"
        echo "  verify [ARGS]   - Verify setup"
        echo "  volumes         - Monitor volumes"
        echo "  dashboard       - Start web dashboard"
        echo "  shell           - Interactive shell"
        exit 1
        ;;
esac

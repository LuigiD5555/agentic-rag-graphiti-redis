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
        exec python -m src.tools.analyze_logs "$@"
        ;;

    verify)
        echo "Running setup verification..."
        shift
        exec python -m src.tools.setup_verifier "$@"
        ;;

    diagnose)
        echo "Running configuration diagnostics..."
        exec python scripts/diagnose_config.py
        ;;

    verify-data)
        echo "Verifying Weaviate data..."
        exec python scripts/verify_data.py
        ;;

    verify-streaming)
        echo "Verifying streaming ingestion..."
        shift
        exec python scripts/verify_streaming.py "$@"
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
        echo "  diagnose        - Diagnose configuration"
        echo "  verify-data     - Verify Weaviate data"
        echo "  verify-streaming - Verify streaming ingestion"
        echo "  volumes         - Monitor volumes"
        echo "  dashboard       - Start web dashboard"
        echo "  shell           - Interactive shell"
        exit 1
        ;;
esac

#!/bin/sh
# Debug tools entry point

set -e

MODE="${1:-list}"

case "$MODE" in
    diagnose)
        exec python /debug/scripts/diagnose_config.py
        ;;
    verify-data)
        exec python /debug/scripts/verify_data.py
        ;;
    verify-streaming)
        shift
        exec python /debug/scripts/verify_streaming.py "$@"
        ;;
    list)
        echo "Available debugging tools:"
        ls -1 /debug/scripts/
        echo ""
        echo "Usage: /debug/entrypoint.sh <mode>"
        ;;
    shell)
        exec /bin/sh
        ;;
    *)
        echo "Unknown mode: $MODE"
        echo "Available modes: diagnose, verify-data, verify-streaming, list, shell"
        exit 1
        ;;
esac

#!/bin/sh
# Debug CLI - Wrapper script for debug container operations

set -e

COMPOSE_FILE="${COMPOSE_FILE:-tools/debug/podman-compose.debug.yml}"
CONTAINER_NAME="${DEBUG_CONTAINER_NAME:-rag-debug}"

usage() {
    cat << EOF
Debug CLI - Manage RAG debug container

Usage:
  $0 <command> [options]

Commands:
  start                 Start debug container
  stop                  Stop debug container
  shell                 Interactive shell in container
  diagnose              Run configuration diagnostics
  verify-data           Verify Weaviate data
  verify-streaming [A]  Verify streaming ingestion
  list                  List available debug scripts
EOF
    exit 0
}

check_container() {
    if ! podman ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "Debug container is not running"
        echo "Start it with: podman-compose -f ${COMPOSE_FILE} up -d"
        exit 1
    fi
}

case "${1:-}" in
    start)
        podman-compose -f "$COMPOSE_FILE" up -d
        ;;
    stop)
        podman-compose -f "$COMPOSE_FILE" stop
        ;;
    shell)
        check_container
        podman exec -it "$CONTAINER_NAME" /bin/sh
        ;;
    diagnose|verify-data|verify-streaming|list)
        cmd="$1"
        shift
        check_container
        podman exec "$CONTAINER_NAME" /debug/entrypoint.sh "$cmd" "$@"
        ;;
    help|-h|--help|"")
        usage
        ;;
    *)
        echo "Unknown command: $1"
        usage
        ;;
esac

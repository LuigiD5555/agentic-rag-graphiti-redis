#!/bin/bash
# Memory Monitoring Script for RAG Ingestion Pipeline
#
# Usage: ./monitor_memory.sh [threshold_percent]
# Example: ./monitor_memory.sh 90  (alert at 90% memory usage)

THRESHOLD=${1:-85}  # Default 85% threshold
LOG_FILE="memory_monitor.log"
ALERT_SHOWN=0

# Pick first running container that matches "app" (case-insensitive), unless provided.
CONTAINER_NAME=${2:-}
if [ -z "$CONTAINER_NAME" ]; then
    if command -v rg >/dev/null 2>&1; then
        CONTAINER_NAME=$(podman ps --format "{{.Names}}" | rg -m1 -i "app")
    else
        CONTAINER_NAME=$(podman ps --format "{{.Names}}" | grep -i -m1 "app")
    fi
fi

if [ -z "$CONTAINER_NAME" ]; then
    echo "ERROR: No running container name matched 'app'"
    echo "   Try: podman ps --format \"{{.Names}}\" | grep -i app"
    echo "   Or pass a container name: ./monitor_memory.sh 85 <name>"
    exit 1
fi

echo "Starting memory monitor for '${CONTAINER_NAME}' container..."
echo "   Threshold: ${THRESHOLD}%"
echo "   Log file: ${LOG_FILE}"
echo "   Press Ctrl+C to stop"
echo ""

# Color codes
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

while true; do
    # Get memory stats from podman
    STATS=$(podman stats "$CONTAINER_NAME" --no-stream --format "table {{.MemUsage}}\t{{.MemPerc}}" 2>/dev/null)

    if [ $? -ne 0 ]; then
        echo -e "${RED}ERROR: Cannot get stats for '${CONTAINER_NAME}' container${NC}"
        echo "   Make sure the container is running: podman ps | grep ${CONTAINER_NAME}"
        sleep 10
        continue
    fi

    # Parse memory usage and percentage
    MEM_USAGE=$(echo "$STATS" | tail -1 | awk '{print $1}')
    MEM_PERC=$(echo "$STATS" | tail -1 | awk '{print $3}' | sed 's/%//')

    # Get current timestamp
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

    # Log to file
    echo "${TIMESTAMP} | Memory: ${MEM_USAGE} (${MEM_PERC}%)" >> "$LOG_FILE"

    # Color-coded output based on usage
    if (( $(echo "$MEM_PERC > $THRESHOLD" | bc -l 2>/dev/null || echo "0") )); then
        # Critical - Red
        echo -e "${RED}${TIMESTAMP} | CRITICAL: ${MEM_USAGE} (${MEM_PERC}%)${NC}"

        # Show alert once
        if [ $ALERT_SHOWN -eq 0 ]; then
            echo ""
            echo -e "${RED}┌────────────────────────────────────────────────────┐${NC}"
            echo -e "${RED}│  MEMORY USAGE CRITICAL                            │${NC}"
            echo -e "${RED}│                                                    │${NC}"
            echo -e "${RED}│  Current: ${MEM_PERC}% (threshold: ${THRESHOLD}%)                  │${NC}"
            echo -e "${RED}│                                                    │${NC}"
            echo -e "${RED}│  Recommendations:                                  │${NC}"
            echo -e "${RED}│  1. Increase APP_MEMORY in .env                   │${NC}"
            echo -e "${RED}│  2. Reduce RAG_PIPELINE_WORKERS                   │${NC}"
            echo -e "${RED}│  3. Reduce RAG_EMBED_BATCH_SIZE                   │${NC}"
            echo -e "${RED}│                                                    │${NC}"
            echo -e "${RED}│  See MEMORY_FIX.md for detailed solutions         │${NC}"
            echo -e "${RED}└────────────────────────────────────────────────────┘${NC}"
            echo ""
            ALERT_SHOWN=1
        fi

    elif (( $(echo "$MEM_PERC > 70" | bc -l 2>/dev/null || echo "0") )); then
        # Warning - Yellow
        echo -e "${YELLOW}${TIMESTAMP} | WARNING: ${MEM_USAGE} (${MEM_PERC}%)${NC}"
        ALERT_SHOWN=0

    else
        # Normal - Green
        echo -e "${GREEN}${TIMESTAMP} | OK: ${MEM_USAGE} (${MEM_PERC}%)${NC}"
        ALERT_SHOWN=0
    fi

    # Check if container is still running
    if ! podman ps --format "{{.Names}}" | grep -q "$CONTAINER_NAME"; then
        echo -e "${RED}WARNING: Container '${CONTAINER_NAME}' stopped unexpectedly${NC}"
        echo "   Checking last logs..."
        podman logs "$CONTAINER_NAME" --tail 50 | tail -20
        break
    fi

    # Wait before next check
    sleep 10
done

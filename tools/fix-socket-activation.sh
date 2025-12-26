#!/bin/bash
# ============================================================================
# Fix Socket Activation - Ensures tools only start on-demand
# ============================================================================
# This script:
# 1. Stops and disables all running tool services
# 2. Reinstalls the corrected systemd units
# 3. Enables ONLY the sockets (not the services)
# 4. Verifies proper configuration
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BLUE}====================================================================${NC}"
echo -e "${BOLD}Fixing Socket Activation for Tool Services${NC}"
echo -e "${BLUE}====================================================================${NC}"
echo ""

# Check if running in systemd user environment
if ! command -v systemctl >/dev/null 2>&1; then
  echo -e "${RED}ERROR:${NC} systemctl not available. Run this on the host."
  exit 1
fi

# ============================================================================
# STEP 1: Stop and disable all tool services
# ============================================================================

echo -e "${CYAN}Step 1:${NC} Stopping and disabling tool services..."
echo ""

for tool in office archive ocr gpu; do
  echo -e "  Stopping tool-${tool}..."

  # Stop service if running
  systemctl --user stop "tool-${tool}.service" 2>/dev/null || true

  # Disable service (prevents auto-start)
  systemctl --user disable "tool-${tool}.service" 2>/dev/null || true

  # Stop socket
  systemctl --user stop "tool-${tool}.socket" 2>/dev/null || true
done

echo ""
echo -e "${GREEN}OK${NC} All tool services stopped and disabled"

# ============================================================================
# STEP 2: Stop containers
# ============================================================================

echo ""
echo -e "${CYAN}Step 2:${NC} Stopping tool containers..."
echo ""

for tool in office archive ocr gpu; do
  if podman ps -a --format "{{.Names}}" | grep -q "rag-tool-${tool}"; then
    echo -e "  Stopping rag-tool-${tool}..."
    podman stop -t 5 "rag-tool-${tool}" 2>/dev/null || true
    podman rm -f "rag-tool-${tool}" 2>/dev/null || true
  fi
done

echo ""
echo -e "${GREEN}OK${NC} All tool containers stopped"

# ============================================================================
# STEP 3: Reinstall systemd units
# ============================================================================

echo ""
echo -e "${CYAN}Step 3:${NC} Reinstalling systemd units..."
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

"$SCRIPT_DIR/install-systemd.sh"

# ============================================================================
# STEP 4: Enable ONLY sockets (not services)
# ============================================================================

echo ""
echo -e "${CYAN}Step 4:${NC} Enabling sockets (services will start on-demand)..."
echo ""

# Enable sockets ONLY
systemctl --user enable tool-office.socket
systemctl --user enable tool-archive.socket

if grep -q "ENABLE_OCR=true" "$PROJECT_ROOT/.env" 2>/dev/null; then
  systemctl --user enable tool-ocr.socket
  echo -e "  ${GREEN}✓${NC} tool-ocr.socket enabled (OCR enabled in .env)"
else
  echo -e "  ${YELLOW}⊘${NC} tool-ocr.socket skipped (ENABLE_OCR not set in .env)"
fi

if grep -q "ENABLE_GPU_ACCELERATION=true" "$PROJECT_ROOT/.env" 2>/dev/null; then
  systemctl --user enable tool-gpu.socket
  echo -e "  ${GREEN}✓${NC} tool-gpu.socket enabled (GPU enabled in .env)"
else
  echo -e "  ${YELLOW}⊘${NC} tool-gpu.socket skipped (ENABLE_GPU_ACCELERATION not set in .env)"
fi

# Start sockets
echo ""
echo -e "${CYAN}Step 5:${NC} Starting sockets..."
echo ""

systemctl --user start tool-office.socket
systemctl --user start tool-archive.socket

if grep -q "ENABLE_OCR=true" "$PROJECT_ROOT/.env" 2>/dev/null; then
  systemctl --user start tool-ocr.socket
fi

if grep -q "ENABLE_GPU_ACCELERATION=true" "$PROJECT_ROOT/.env" 2>/dev/null; then
  systemctl --user start tool-gpu.socket
fi

echo ""
echo -e "${GREEN}OK${NC} Sockets started"

# ============================================================================
# STEP 6: Verify configuration
# ============================================================================

echo ""
echo -e "${BLUE}====================================================================${NC}"
echo -e "${BOLD}Verification${NC}"
echo -e "${BLUE}====================================================================${NC}"
echo ""

echo -e "${CYAN}Active Sockets:${NC}"
systemctl --user list-sockets --no-pager | grep "tool-" || echo "  No tool sockets found"

echo ""
echo -e "${CYAN}Service Status (should be 'inactive'):${NC}"

for tool in office archive ocr gpu; do
  status=$(systemctl --user is-active "tool-${tool}.service" 2>/dev/null || echo "inactive")
  if [ "$status" = "inactive" ]; then
    echo -e "  ${GREEN}✓${NC} tool-${tool}.service: ${GREEN}inactive${NC} (correct, will start on first request)"
  else
    echo -e "  ${RED}✗${NC} tool-${tool}.service: ${RED}${status}${NC} (should be inactive)"
  fi
done

echo ""
echo -e "${CYAN}Container Status (should show none running):${NC}"
if podman ps | grep -q "rag-tool"; then
  echo -e "  ${YELLOW}WARNING:${NC} Some tool containers are still running"
  podman ps --format "table {{.Names}}\t{{.Status}}" | grep "rag-tool"
else
  echo -e "  ${GREEN}✓${NC} No tool containers running (correct)"
fi

# ============================================================================
# SUMMARY
# ============================================================================

echo ""
echo -e "${BLUE}====================================================================${NC}"
echo -e "${GREEN}${BOLD}Configuration Complete${NC}"
echo -e "${BLUE}====================================================================${NC}"
echo ""
echo -e "${BOLD}What happens now:${NC}"
echo ""
echo "1. ${CYAN}Sockets are listening${NC} on their ports (9101, 9102, etc.)"
echo "2. ${CYAN}Services are inactive${NC} (not running)"
echo "3. ${CYAN}On first request${NC}, systemd will:"
echo "   - Detect connection to the socket"
echo "   - Automatically start the corresponding service"
echo "   - Launch the container"
echo "   - Forward traffic to the container"
echo ""
echo -e "${BOLD}Testing:${NC}"
echo ""
echo "  curl http://127.0.0.1:9102/healthz  # This will start tool-office"
echo "  curl http://127.0.0.1:9101/healthz  # This will start tool-archive"
echo ""
echo -e "${BOLD}Check what happened:${NC}"
echo ""
echo "  systemctl --user status tool-office.service  # Should now be 'active (running)'"
echo "  podman ps | grep rag-tool                    # Should show running container"
echo ""
echo -e "${GREEN}Done!${NC}"
echo ""
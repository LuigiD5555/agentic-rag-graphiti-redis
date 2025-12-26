#!/bin/bash
# ============================================================================
# Verify Socket Activation Configuration
# ============================================================================
# This script verifies that socket activation is correctly configured:
# - Sockets are enabled and listening
# - Services are NOT enabled (will start on-demand)
# - No WantedBy=default.target in .service files
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo -e "${BLUE}====================================================================${NC}"
echo -e "${BOLD}Socket Activation Configuration Verification${NC}"
echo -e "${BLUE}====================================================================${NC}"
echo ""

ERRORS=0
WARNINGS=0

# ============================================================================
# Check 1: Systemd availability
# ============================================================================

echo -e "${CYAN}[1/6] Checking systemd availability...${NC}"
if ! command -v systemctl >/dev/null 2>&1; then
  echo -e "  ${RED}✗ FAIL${NC}: systemctl not available"
  echo ""
  echo "This script must run on a system with systemd."
  exit 1
fi
echo -e "  ${GREEN}✓ PASS${NC}: systemctl available"
echo ""

# ============================================================================
# Check 2: Service files don't have WantedBy=default.target
# ============================================================================

echo -e "${CYAN}[2/6] Checking .service files for incorrect WantedBy...${NC}"

for tool in office archive ocr gpu; do
  service_file="$PROJECT_ROOT/systemd/user/tool-${tool}.service"

  if [ -f "$service_file" ]; then
    if grep -q "^WantedBy=default.target" "$service_file"; then
      echo -e "  ${RED}✗ FAIL${NC}: tool-${tool}.service has WantedBy=default.target"
      ERRORS=$((ERRORS + 1))
    else
      echo -e "  ${GREEN}✓ PASS${NC}: tool-${tool}.service (no auto-start)"
    fi
  else
    echo -e "  ${YELLOW}⚠ WARN${NC}: tool-${tool}.service not found"
    WARNINGS=$((WARNINGS + 1))
  fi
done
echo ""

# ============================================================================
# Check 3: Socket files exist
# ============================================================================

echo -e "${CYAN}[3/6] Checking .socket files exist...${NC}"

for tool in office archive ocr gpu; do
  socket_file="$PROJECT_ROOT/systemd/user/tool-${tool}.socket"

  if [ -f "$socket_file" ]; then
    echo -e "  ${GREEN}✓ PASS${NC}: tool-${tool}.socket exists"
  else
    echo -e "  ${RED}✗ FAIL${NC}: tool-${tool}.socket not found"
    ERRORS=$((ERRORS + 1))
  fi
done
echo ""

# ============================================================================
# Check 4: Installed units
# ============================================================================

echo -e "${CYAN}[4/6] Checking installed systemd units...${NC}"

SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

for tool in office archive; do
  if [ -f "$SYSTEMD_USER_DIR/tool-${tool}.socket" ]; then
    echo -e "  ${GREEN}✓ PASS${NC}: tool-${tool}.socket installed"
  else
    echo -e "  ${YELLOW}⚠ WARN${NC}: tool-${tool}.socket not installed (run install-systemd.sh)"
    WARNINGS=$((WARNINGS + 1))
  fi

  if [ -f "$SYSTEMD_USER_DIR/tool-${tool}.service" ]; then
    echo -e "  ${GREEN}✓ PASS${NC}: tool-${tool}.service installed"
  else
    echo -e "  ${YELLOW}⚠ WARN${NC}: tool-${tool}.service not installed (run install-systemd.sh)"
    WARNINGS=$((WARNINGS + 1))
  fi
done
echo ""

# ============================================================================
# Check 5: Socket and Service status
# ============================================================================

echo -e "${CYAN}[5/6] Checking runtime status...${NC}"

for tool in office archive; do
  # Check socket status
  socket_status=$(systemctl --user is-active "tool-${tool}.socket" 2>/dev/null || echo "inactive")
  socket_enabled=$(systemctl --user is-enabled "tool-${tool}.socket" 2>/dev/null || echo "disabled")

  if [ "$socket_enabled" = "enabled" ] || [ "$socket_enabled" = "static" ]; then
    echo -e "  ${GREEN}✓ PASS${NC}: tool-${tool}.socket is enabled"
  else
    echo -e "  ${YELLOW}⚠ WARN${NC}: tool-${tool}.socket is not enabled (run enable-tool-sockets.sh)"
    WARNINGS=$((WARNINGS + 1))
  fi

  if [ "$socket_status" = "active" ]; then
    echo -e "  ${GREEN}✓ PASS${NC}: tool-${tool}.socket is active (listening)"
  else
    echo -e "  ${YELLOW}⚠ WARN${NC}: tool-${tool}.socket is $socket_status"
    WARNINGS=$((WARNINGS + 1))
  fi

  # Check service status (should be inactive or running)
  service_status=$(systemctl --user is-active "tool-${tool}.service" 2>&1 || true)
  service_enabled=$(systemctl --user is-enabled "tool-${tool}.service" 2>&1 || true)

  # Trim whitespace
  service_status=$(echo "$service_status" | tr -d '\n\r' | xargs)
  service_enabled=$(echo "$service_enabled" | tr -d '\n\r' | xargs)

  if [ "$service_enabled" = "disabled" ] || [ "$service_enabled" = "indirect" ] || [ "$service_enabled" = "static" ]; then
    echo -e "  ${GREEN}✓ PASS${NC}: tool-${tool}.service is not auto-enabled (correct for socket activation)"
  else
    echo -e "  ${RED}✗ FAIL${NC}: tool-${tool}.service is enabled (should be disabled, run fix-socket-activation.sh)"
    ERRORS=$((ERRORS + 1))
  fi

  case "$service_status" in
    "inactive")
      echo -e "  ${GREEN}✓ PASS${NC}: tool-${tool}.service is inactive (will start on-demand)"
      ;;
    "active")
      echo -e "  ${BLUE}ℹ INFO${NC}: tool-${tool}.service is active (responding to requests)"
      ;;
    *)
      echo -e "  ${YELLOW}⚠ WARN${NC}: tool-${tool}.service is ${service_status}"
      WARNINGS=$((WARNINGS + 1))
      ;;
  esac

  echo ""
done

# ============================================================================
# Check 6: Container images
# ============================================================================

echo -e "${CYAN}[6/6] Checking container images...${NC}"

for tool in office archive; do
  if podman images --format "{{.Repository}}" | grep -q "^localhost/rag-tool-${tool}$"; then
    echo -e "  ${GREEN}✓ PASS${NC}: rag-tool-${tool} image exists"
  else
    echo -e "  ${RED}✗ FAIL${NC}: rag-tool-${tool} image not found (run build-all.sh)"
    ERRORS=$((ERRORS + 1))
  fi
done
echo ""

# ============================================================================
# Summary
# ============================================================================

echo -e "${BLUE}====================================================================${NC}"
echo -e "${BOLD}Summary${NC}"
echo -e "${BLUE}====================================================================${NC}"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
  echo -e "${GREEN}${BOLD}✓ ALL CHECKS PASSED${NC}"
  echo ""
  echo "Socket activation is correctly configured!"
  echo ""
  echo "Next steps:"
  echo "  1. Test activation: curl http://127.0.0.1:9102/healthz"
  echo "  2. Check service started: systemctl --user status tool-office.service"
  echo ""
  exit 0
elif [ $ERRORS -eq 0 ]; then
  echo -e "${YELLOW}${BOLD}⚠ WARNINGS: $WARNINGS${NC}"
  echo ""
  echo "Configuration has minor issues but should work."
  echo ""
  echo "Recommendations:"
  echo "  - Run: ./tools/enable-tool-sockets.sh"
  echo ""
  exit 0
else
  echo -e "${RED}${BOLD}✗ ERRORS: $ERRORS, WARNINGS: $WARNINGS${NC}"
  echo ""
  echo "Configuration has issues that need to be fixed."
  echo ""
  echo "Run this to fix:"
  echo "  ./tools/fix-socket-activation.sh"
  echo ""
  exit 1
fi
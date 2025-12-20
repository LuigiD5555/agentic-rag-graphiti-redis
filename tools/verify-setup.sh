#!/bin/bash
# Verify RAG tools setup - Check all files are in place

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo -e "${BLUE}====================================================================${NC}"
echo -e "${BLUE}RAG Tools - Setup Verification Script${NC}"
echo -e "${BLUE}====================================================================${NC}"
echo ""

errors=0
warnings=0

check_file() {
    local file=$1
    local description=$2

    if [ -f "$file" ]; then
        echo -e "${GREEN}OK${NC} $description"
        return 0
    else
        echo -e "${RED}ERR${NC} $description - NOT FOUND: $file"
        ((errors++))
        return 1
    fi
}

check_executable() {
    local file=$1
    local description=$2

    if [ -f "$file" ] && [ -x "$file" ]; then
        echo -e "${GREEN}OK${NC} $description (executable)"
        return 0
    elif [ -f "$file" ]; then
        echo -e "${YELLOW}WARN${NC} $description (not executable)"
        ((warnings++))
        return 1
    else
        echo -e "${RED}ERR${NC} $description - NOT FOUND: $file"
        ((errors++))
        return 1
    fi
}

check_dir() {
    local dir=$1
    local description=$2

    if [ -d "$dir" ]; then
        echo -e "${GREEN}OK${NC} $description"
        return 0
    else
        echo -e "${RED}ERR${NC} $description - NOT FOUND: $dir"
        ((errors++))
        return 1
    fi
}

echo "Checking tool directories..."
echo "==================================================================="

check_dir "$SCRIPT_DIR/office" "Office tool directory"
check_dir "$SCRIPT_DIR/archive" "Archive tool directory"
check_dir "$SCRIPT_DIR/ocr" "OCR tool directory"
check_dir "$SCRIPT_DIR/gpu" "GPU tool directory"

echo ""
echo "Checking tool source files..."
echo "==================================================================="

check_file "$SCRIPT_DIR/office/src/app.py" "Office tool app.py"
check_file "$SCRIPT_DIR/office/Dockerfile" "Office tool Dockerfile"
check_file "$SCRIPT_DIR/office/requirements.txt" "Office tool requirements.txt"

check_file "$SCRIPT_DIR/archive/src/app.py" "Archive tool app.py"
check_file "$SCRIPT_DIR/archive/Dockerfile" "Archive tool Dockerfile"
check_file "$SCRIPT_DIR/archive/requirements.txt" "Archive tool requirements.txt"

check_file "$SCRIPT_DIR/ocr/src/app.py" "OCR tool app.py"
check_file "$SCRIPT_DIR/ocr/Dockerfile" "OCR tool Dockerfile"
check_file "$SCRIPT_DIR/ocr/requirements.txt" "OCR tool requirements.txt"

check_file "$SCRIPT_DIR/gpu/src/app.py" "GPU tool app.py"
check_file "$SCRIPT_DIR/gpu/Dockerfile" "GPU tool Dockerfile"
check_file "$SCRIPT_DIR/gpu/requirements.txt" "GPU tool requirements.txt"

echo ""
echo "Checking systemd units..."
echo "==================================================================="

check_file "$PROJECT_ROOT/systemd/user/tool-office.socket" "Office socket unit"
check_file "$PROJECT_ROOT/systemd/user/tool-office.service" "Office service unit"

check_file "$PROJECT_ROOT/systemd/user/tool-archive.socket" "Archive socket unit"
check_file "$PROJECT_ROOT/systemd/user/tool-archive.service" "Archive service unit"

check_file "$PROJECT_ROOT/systemd/user/tool-ocr.socket" "OCR socket unit"
check_file "$PROJECT_ROOT/systemd/user/tool-ocr.service" "OCR service unit"

check_file "$PROJECT_ROOT/systemd/user/tool-gpu.socket" "GPU socket unit"
check_file "$PROJECT_ROOT/systemd/user/tool-gpu.service" "GPU service unit"

echo ""
echo "Checking scripts..."
echo "==================================================================="

check_executable "$SCRIPT_DIR/build-all.sh" "Build script"
check_executable "$SCRIPT_DIR/install-systemd.sh" "Install script"
check_executable "$SCRIPT_DIR/test-tools.sh" "Test script"

echo ""
echo "Checking documentation..."
echo "==================================================================="

check_file "$SCRIPT_DIR/README.md" "README.md"
check_file "$SCRIPT_DIR/ARCHITECTURE.md" "ARCHITECTURE.md"
check_file "$SCRIPT_DIR/CONFIGURATION.md" "CONFIGURATION.md"
check_file "$SCRIPT_DIR/INDEX.md" "INDEX.md"
check_file "$SCRIPT_DIR/client_example.py" "Python client example"
check_file "$SCRIPT_DIR/example.env" "Environment config template"

check_file "$PROJECT_ROOT/NEXT_STEPS.md" "Next steps guide"
check_file "$PROJECT_ROOT/TOOLS_DEPLOYMENT.md" "Deployment guide"

echo ""
echo "Checking port configurations..."
echo "==================================================================="

# Check socket ports
ports=$(grep -h "ListenStream" "$PROJECT_ROOT/systemd/user/"*.socket 2>/dev/null | awk -F: '{print $NF}' | sort)
expected_ports="9101
9102
9103
9104"

if [ "$ports" = "$expected_ports" ]; then
    echo -e "${GREEN}OK${NC} Socket ports configured correctly (9101-9104)"
else
    echo -e "${RED}ERR${NC} Socket ports mismatch!"
    echo "Expected: 9101, 9102, 9103, 9104"
    echo "Found: $(echo $ports | tr '\n' ' ')"
    ((errors++))
fi

# Check internal ports
internal_ports=$(grep -h "socket-proxyd" "$PROJECT_ROOT/systemd/user/"*.service 2>/dev/null | grep -oE "191[0-9][0-9]" | sort)
expected_internal="19101
19102
19103
19104"

if [ "$internal_ports" = "$expected_internal" ]; then
    echo -e "${GREEN}OK${NC} Internal ports configured correctly (19101-19104)"
else
    echo -e "${RED}ERR${NC} Internal ports mismatch!"
    ((errors++))
fi

echo ""
echo "Checking prerequisites..."
echo "==================================================================="

if command -v podman &> /dev/null; then
    echo -e "${GREEN}OK${NC} podman installed ($(podman --version))"
else
    echo -e "${RED}ERR${NC} podman NOT installed"
    ((errors++))
fi

if command -v systemctl &> /dev/null; then
    echo -e "${GREEN}OK${NC} systemctl available"
else
    echo -e "${RED}ERR${NC} systemctl NOT available"
    ((errors++))
fi

if command -v systemd-socket-proxyd &> /dev/null; then
    echo -e "${GREEN}OK${NC} systemd-socket-proxyd available"
else
    echo -e "${YELLOW}WARN${NC} systemd-socket-proxyd NOT found (may be at /usr/lib/systemd/)"
    ((warnings++))
fi

if command -v curl &> /dev/null; then
    echo -e "${GREEN}OK${NC} curl installed"
else
    echo -e "${YELLOW}WARN${NC} curl NOT installed (needed for testing)"
    ((warnings++))
fi

echo ""
echo "==================================================================="
echo ""

if [ $errors -eq 0 ] && [ $warnings -eq 0 ]; then
    echo -e "${GREEN}OK All checks passed!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. cd tools && ./build-all.sh"
    echo "  2. ./install-systemd.sh"
    echo "  3. systemctl --user enable --now tool-{office,archive,ocr,gpu}.socket"
    echo "  4. ./test-tools.sh"
    echo ""
    echo "See NEXT_STEPS.md for detailed instructions."
    exit 0
elif [ $errors -eq 0 ]; then
    echo -e "${YELLOW}WARN Setup complete with ${warnings} warning(s)${NC}"
    echo ""
    echo "You can proceed with deployment, but check the warnings above."
    exit 0
else
    echo -e "${RED}ERR Setup incomplete: ${errors} error(s), ${warnings} warning(s)${NC}"
    echo ""
    echo "Please fix the errors above before proceeding."
    exit 1
fi

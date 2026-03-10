#!/bin/bash
# Legacy Code Cleanup Script
# Removes unused integration artifacts (qdrant, redis, etc.)
# Note: Excludes the vendor/open-webui directory as it contains external code

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if we're in the project root
if [ ! -f "requirements.txt" ] && [ ! -f "podman-compose.yml" ]; then
    print_error "Please run this script from the project root directory"
    exit 1
fi

print_info "Starting legacy code cleanup..."
echo ""

# Step 1: Find and remove qdrant-related files (excluding vendor/open-webui directory)
print_info "Step 1: Removing qdrant integration artifacts..."
qdrant_files=$(find . -type f \( -name "*qdrant*" -o -name "*Qdrant*" \) ! -path "./vendor/open-webui/*" ! -path "./vendor/open-webui/**" 2>/dev/null || true)
if [ -n "$qdrant_files" ]; then
    echo "Found qdrant files:"
    echo "$qdrant_files"
    echo ""
    read -p "Remove these files? (y/N): " confirm
    if [[ $confirm =~ ^[Yy]$ ]]; then
        echo "$qdrant_files" | xargs rm -f 2>/dev/null || true
        print_success "Removed qdrant files"
    else
        print_warning "Skipping qdrant file removal"
    fi
else
    print_info "No qdrant files found"
fi

# Step 2: Find and remove redis-related files (excluding vendor/open-webui directory)
print_info "Step 2: Removing redis integration artifacts..."
redis_files=$(find . -type f \( -name "*redis*" -o -name "*Redis*" \) ! -path "./vendor/open-webui/*" ! -path "./vendor/open-webui/**" 2>/dev/null || true)
if [ -n "$redis_files" ]; then
    echo "Found redis files:"
    echo "$redis_files"
    echo ""
    read -p "Remove these files? (y/N): " confirm
    if [[ $confirm =~ ^[Yy]$ ]]; then
        echo "$redis_files" | xargs rm -f 2>/dev/null || true
        print_success "Removed redis files"
    else
        print_warning "Skipping redis file removal"
    fi
else
    print_info "No redis files found"
fi

# Step 3: Clean up requirements.txt
print_info "Step 3: Cleaning up requirements.txt..."
if [ -f "requirements.txt" ]; then
    # Backup original
    cp requirements.txt requirements.txt.backup
    
    # Remove qdrant and redis packages
    grep -v -E "(qdrant|redis)" requirements.txt > requirements.txt.tmp
    mv requirements.txt.tmp requirements.txt
    
    print_success "Cleaned requirements.txt"
    print_info "Original saved as requirements.txt.backup"
fi

# Step 4: Clean up Dockerfile
print_info "Step 4: Cleaning up Dockerfile..."
if [ -f "Dockerfile" ]; then
    # Backup original
    cp Dockerfile Dockerfile.backup
    
    # Remove qdrant and redis installations
    sed -i '/qdrant/d' Dockerfile
    sed -i '/redis/d' Dockerfile
    
    print_success "Cleaned Dockerfile"
    print_info "Original saved as Dockerfile.backup"
fi

# Step 5: Clean up podman-compose.yml
print_info "Step 5: Cleaning up podman-compose.yml..."
if [ -f "podman-compose.yml" ]; then
    # Backup original
    cp podman-compose.yml podman-compose.yml.backup
    
    # Remove qdrant and redis services
    sed -i '/qdrant/,/^  [a-z]/d' podman-compose.yml 2>/dev/null || true
    sed -i '/redis/,/^  [a-z]/d' podman-compose.yml 2>/dev/null || true
    
    print_success "Cleaned podman-compose.yml"
    print_info "Original saved as podman-compose.yml.backup"
fi

# Step 6: Clean up .env file
print_info "Step 6: Cleaning up .env file..."
if [ -f ".env" ]; then
    # Backup original
    cp .env .env.backup
    
    # Remove qdrant and redis environment variables
    sed -i '/qdrant/d' .env
    sed -i '/redis/d' .env
    
    print_success "Cleaned .env file"
    print_info "Original saved as .env.backup"
fi

# Step 7: Clean up Python imports (excluding vendor/open-webui directory)
print_info "Step 7: Cleaning up Python imports..."
python_files=$(find . -name "*.py" -type f ! -path "./vendor/open-webui/*" ! -path "./vendor/open-webui/**" 2>/dev/null || true)
if [ -n "$python_files" ]; then
    for file in $python_files; do
        # Remove qdrant and redis imports
        sed -i '/import.*qdrant/d' "$file" 2>/dev/null || true
        sed -i '/from.*qdrant/d' "$file" 2>/dev/null || true
        sed -i '/import.*redis/d' "$file" 2>/dev/null || true
        sed -i '/from.*redis/d' "$file" 2>/dev/null || true
    done
    print_success "Cleaned Python imports"
fi

# Step 8: Run bloat analyzer to find more legacy code
print_info "Step 8: Running bloat analyzer to find more legacy code..."
if [ -f "tools/monitoring/src/bloat_analyzer.py" ]; then
    echo "Running bloat analyzer to detect unused code..."
    python -m tools.monitoring.src.bloat_analyzer 2>/dev/null || true
    print_info "Check /app/reports/bloat/ for detailed analysis"
else
    print_warning "Bloat analyzer not found, skipping analysis"
fi

echo ""
print_success "Legacy cleanup completed!"
echo ""
print_info "Summary of changes:"
echo "1. Removed qdrant integration files (excluding vendor/open-webui directory)"
echo "2. Removed redis integration files (excluding vendor/open-webui directory)"
echo "3. Cleaned requirements.txt"
echo "4. Cleaned Dockerfile"
echo "5. Cleaned podman-compose.yml"
echo "6. Cleaned .env file"
echo "7. Cleaned Python imports (excluding vendor/open-webui directory)"
echo "8. Ran bloat analyzer for further detection"
echo ""
print_warning "IMPORTANT: Review the changes before committing!"
print_warning "Backup files have been created with .backup extension"
echo ""
print_info "Next steps:"
echo "1. Review the changes: git diff"
echo "2. Test the system: ./start-everything.sh"
echo "3. Run tests: pytest tests/"
echo "4. Commit changes: git add . && git commit -m 'Clean up legacy qdrant/redis integration'"
echo ""

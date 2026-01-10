#!/bin/bash
# Simple configuration checker for dual embeddings

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 Dual Embeddings Configuration Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Load .env
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | grep -v '^$' | xargs)
fi

echo "📋 Configuration:"
echo "  ├─ ENABLE_DUAL_EMBEDDINGS: ${ENABLE_DUAL_EMBEDDINGS:-false}"
echo "  ├─ SMALL_EMBEDDING_DIM: ${SMALL_EMBEDDING_DIM:-384}"
echo "  ├─ LARGE_EMBEDDING_DIM: ${LARGE_EMBEDDING_DIM:-768}"
echo "  ├─ SMALL_COLLECTION: ${DUAL_EMBEDDINGS_SMALL_COLLECTION:-RAGDocument384}"
echo "  ├─ LARGE_COLLECTION: ${DUAL_EMBEDDINGS_LARGE_COLLECTION:-RAGDocument768}"
echo "  ├─ SMALL_MODEL: ${SMALL_EMBEDDING_MODEL:-text-embedding-bge-micro-v2}"
echo "  └─ LARGE_MODEL: ${LARGE_EMBEDDING_MODEL:-text-embedding-nomic-embed-text-v2-moe}"
echo ""

echo "🧪 Testing LM Studio models..."
echo ""

# Test small model
echo "  Testing SMALL model (${SMALL_EMBEDDING_MODEL})..."
SMALL_TEST=$(curl -s -X POST http://127.0.0.1:1234/v1/embeddings \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"${SMALL_EMBEDDING_MODEL}\", \"input\": \"test\"}" 2>/dev/null)

if echo "$SMALL_TEST" | grep -q "embedding"; then
    SMALL_DIM=$(echo "$SMALL_TEST" | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data['data'][0]['embedding']))" 2>/dev/null)
    if [ "$SMALL_DIM" == "${SMALL_EMBEDDING_DIM}" ]; then
        echo "    ✅ Model OK: ${SMALL_DIM} dimensions (matches config)"
    else
        echo "    ⚠️  Warning: ${SMALL_DIM} dimensions (expected ${SMALL_EMBEDDING_DIM})"
    fi
else
    echo "    ❌ ERROR: Model not available or failed"
fi

# Test large model
echo "  Testing LARGE model (${LARGE_EMBEDDING_MODEL})..."
LARGE_TEST=$(curl -s -X POST http://127.0.0.1:1234/v1/embeddings \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"${LARGE_EMBEDDING_MODEL}\", \"input\": \"test\"}" 2>/dev/null)

if echo "$LARGE_TEST" | grep -q "embedding"; then
    LARGE_DIM=$(echo "$LARGE_TEST" | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data['data'][0]['embedding']))" 2>/dev/null)
    if [ "$LARGE_DIM" == "${LARGE_EMBEDDING_DIM}" ]; then
        echo "    ✅ Model OK: ${LARGE_DIM} dimensions (matches config)"
    else
        echo "    ⚠️  Warning: ${LARGE_DIM} dimensions (expected ${LARGE_EMBEDDING_DIM})"
    fi
else
    echo "    ❌ ERROR: Model not available or failed"
fi

echo ""
echo "📊 Resource Limits (from .env):"
echo "  ├─ WEAVIATE_MEMORY: ${WEAVIATE_MEMORY:-8g}"
echo "  ├─ NEO4J_MEMORY: ${NEO4J_MEMORY:-3g}"
echo "  ├─ NEO4J_HEAP_MAX: ${NEO4J_HEAP_MAX:-2G}"
echo "  ├─ REDIS_MEMORY: ${REDIS_MEMORY:-1g}"
echo "  └─ APP_MEMORY: ${APP_MEMORY:-3g}"
echo ""

echo "🔧 Chunk Configuration:"
echo "  ├─ CHUNK_SIZE: ${CHUNK_SIZE:-500}"
echo "  └─ CHUNK_OVERLAP: ${CHUNK_OVERLAP:-50}"
echo ""

if [ "${ENABLE_DUAL_EMBEDDINGS}" == "true" ]; then
    echo "✅ Dual embeddings system is ENABLED and ready to use!"
    echo ""
    echo "📝 Next steps:"
    echo "  1. Restart containers: podman-compose down && podman-compose up -d"
    echo "  2. Ingest documents (they'll auto-route to small/large collections)"
    echo "  3. Monitor memory: podman stats"
else
    echo "⚠️  Dual embeddings system is DISABLED"
    echo ""
    echo "To enable:"
    echo "  1. Edit .env and set: ENABLE_DUAL_EMBEDDINGS=true"
    echo "  2. Run this script again to verify"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

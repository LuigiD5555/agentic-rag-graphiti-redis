#!/bin/bash
# LLM Server CLI Helper
# Quick commands for managing LLM models

set -e

BASE_URL="${LLM_SERVER_URL:-http://localhost:9104}"

function show_help() {
    cat << EOF
LLM Server CLI Helper

Usage: $0 <command> [arguments]

Commands:
    list                    List all supported models
    download <model-id>     Download a model
    load <model-id>         Load a model into memory
    unload <model-id>       Unload a model from memory
    infer <model-id> <prompt> Run inference with a model
    stats                   Show server statistics
    health                  Check server health

Available Models:
    - liquid-lfm2-2.6b      LiquidAI LFM2 2.6B (5.2 GB)
    - liquid-lfm2-1.2b      LiquidAI LFM2 1.2B (2.4 GB)
    - whisper-base          OpenAI Whisper Base (0.3 GB)
    - whisper-small         OpenAI Whisper Small (0.5 GB)
    - dolphin-gemma2-2b     Dolphin 2.9.4 Gemma 2 2B (1.5 GB)
    - openmath-nemotron-1.5b NVIDIA OpenMath Nemotron (3.0 GB)

Environment Variables:
    LLM_SERVER_URL          Server URL (default: http://localhost:9104)

Examples:
    $0 list
    $0 download liquid-lfm2-1.2b
    $0 load liquid-lfm2-1.2b
    $0 infer liquid-lfm2-1.2b "What is machine learning?"
    $0 unload liquid-lfm2-1.2b
EOF
}

function check_server() {
    if ! curl -sf "$BASE_URL/healthz" > /dev/null 2>&1; then
        echo "Error: LLM server is not running at $BASE_URL"
        echo "Start it with: systemctl --user start tool-llm.socket"
        exit 1
    fi
}

function list_models() {
    check_server
    echo "Fetching model list..."
    curl -s "$BASE_URL/models" | python3 -m json.tool
}

function download_model() {
    local model_id="$1"
    if [ -z "$model_id" ]; then
        echo "Error: model-id required"
        echo "Usage: $0 download <model-id>"
        exit 1
    fi

    check_server
    echo "Downloading model: $model_id"
    echo "This may take a while depending on model size..."

    curl -s -X POST "$BASE_URL/models/download" \
        -H "Content-Type: application/json" \
        -d "{\"model_id\": \"$model_id\"}" \
        | python3 -m json.tool
}

function load_model() {
    local model_id="$1"
    if [ -z "$model_id" ]; then
        echo "Error: model-id required"
        echo "Usage: $0 load <model-id>"
        exit 1
    fi

    check_server
    echo "Loading model: $model_id"

    curl -s -X POST "$BASE_URL/models/load" \
        -H "Content-Type: application/json" \
        -d "{\"model_id\": \"$model_id\"}" \
        | python3 -m json.tool
}

function unload_model() {
    local model_id="$1"
    if [ -z "$model_id" ]; then
        echo "Error: model-id required"
        echo "Usage: $0 unload <model-id>"
        exit 1
    fi

    check_server
    echo "Unloading model: $model_id"

    curl -s -X POST "$BASE_URL/models/unload?model_id=$model_id" \
        | python3 -m json.tool
}

function run_inference() {
    local model_id="$1"
    local prompt="$2"

    if [ -z "$model_id" ] || [ -z "$prompt" ]; then
        echo "Error: model-id and prompt required"
        echo "Usage: $0 infer <model-id> <prompt>"
        exit 1
    fi

    check_server
    echo "Running inference on model: $model_id"
    echo "Prompt: $prompt"
    echo ""

    curl -s -X POST "$BASE_URL/inference" \
        -H "Content-Type: application/json" \
        -d "{
            \"model_id\": \"$model_id\",
            \"prompt\": \"$prompt\",
            \"max_tokens\": 512,
            \"temperature\": 0.7
        }" \
        | python3 -m json.tool
}

function show_stats() {
    check_server
    echo "Fetching server statistics..."
    curl -s "$BASE_URL/stats" | python3 -m json.tool
}

function check_health() {
    echo "Checking server health at $BASE_URL..."
    if curl -sf "$BASE_URL/healthz" | python3 -m json.tool; then
        echo "✓ Server is healthy"
    else
        echo "✗ Server is not responding"
        exit 1
    fi
}

# Main command dispatcher
case "${1:-}" in
    list)
        list_models
        ;;
    download)
        download_model "$2"
        ;;
    load)
        load_model "$2"
        ;;
    unload)
        unload_model "$2"
        ;;
    infer)
        run_inference "$2" "$3"
        ;;
    stats)
        show_stats
        ;;
    health)
        check_health
        ;;
    help|--help|-h|"")
        show_help
        ;;
    *)
        echo "Error: Unknown command '$1'"
        echo ""
        show_help
        exit 1
        ;;
esac

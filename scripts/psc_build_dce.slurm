#!/bin/bash
#SBATCH --job-name=dce_build
#SBATCH --partition=RM-shared
#SBATCH --account=cis260009p
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=/ocean/projects/cis260009p/dpalagan/nl2sql-databao/logs/dce_build_%j.log
#SBATCH --error=/ocean/projects/cis260009p/dpalagan/nl2sql-databao/logs/dce_build_%j.err

# Build spider2-dce index (dce.duckdb) on PSC using a fake Ollama server
# that replaces Ollama with sentence-transformers for embeddings.
#
# This is a ONE-TIME job. After dce.duckdb is built it is reused by the
# benchmark. You only need to re-run if you change the YAML schema files.
#
# Dependencies:
#   - pip install sentence-transformers (done by this script if missing)
#   - vLLM endpoint (optional — only needed for DCE description generation,
#     not for embedding. If not available, generate calls return empty strings
#     which is fine since our YAMLs already have descriptions.)
#
# Usage:
#   sbatch scripts/psc_build_dce.slurm
#
# After completion:
#   ls -lh spider2-dce/output/dce.duckdb   # should be ~50-200 MB
#   sbatch scripts/psc_run_benchmark.slurm

set -e

WORK_DIR="/ocean/projects/cis260009p/dpalagan/nl2sql-databao"
VENV_PYTHON="$WORK_DIR/databao-agent/.venv/bin/python"
DCE_DIR="$WORK_DIR/spider2-dce"
FAKE_OLLAMA_PORT=11434

mkdir -p "$WORK_DIR/logs"
cd "$WORK_DIR"

echo "========================================"
echo "DCE Build — PSC Bridges-2"
echo "Node:   $(hostname)"
echo "Time:   $(date)"
echo "DCE:    $DCE_DIR"
echo "========================================"

# Install sentence-transformers if missing
if ! "$VENV_PYTHON" -c "import sentence_transformers" 2>/dev/null; then
    echo "Installing sentence-transformers..."
    "$VENV_PYTHON" -m pip install --quiet sentence-transformers
fi

# Verify databao-context-engine CLI is available
if ! "$VENV_PYTHON" -m databao_context_engine.cli.commands --help &>/dev/null; then
    # Try the dce CLI entry point
    DCE_CLI=$(dirname "$VENV_PYTHON")/dce
    if [ ! -f "$DCE_CLI" ]; then
        echo "ERROR: dce CLI not found. Check databao-context-engine install."
        exit 1
    fi
fi

# Pick up vLLM endpoint if available (for generate calls — optional)
VLLM_ARG=""
ENDPOINT_FILE="$WORK_DIR/logs/vllm_endpoint.txt"
if [ -f "$ENDPOINT_FILE" ]; then
    ENDPOINT=$(head -1 "$ENDPOINT_FILE")
    MODEL_NAME=$(grep "^Model:" "$ENDPOINT_FILE" | cut -d' ' -f2-)
    VLLM_ARG="--vllm-endpoint http://${ENDPOINT} --vllm-model ${MODEL_NAME}"
    echo "vLLM endpoint found: http://${ENDPOINT} (${MODEL_NAME})"
else
    echo "No vLLM endpoint found — generate calls disabled (OK, YAMLs already have descriptions)"
fi

# Start fake Ollama server in background
echo ""
echo "Starting fake Ollama server on port ${FAKE_OLLAMA_PORT}..."
"$VENV_PYTHON" "$WORK_DIR/scripts/fake_ollama_server.py" \
    --port "$FAKE_OLLAMA_PORT" \
    $VLLM_ARG \
    &
FAKE_OLLAMA_PID=$!
echo "Fake Ollama PID: $FAKE_OLLAMA_PID"

# Wait for server to be ready (embedding model download can take a few minutes)
echo "Waiting for fake Ollama to be ready..."
for i in $(seq 1 60); do
    if curl -sf --max-time 3 "http://localhost:${FAKE_OLLAMA_PORT}/api/tags" > /dev/null 2>&1; then
        echo "Fake Ollama ready (waited ~$((i * 5))s)"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "ERROR: Fake Ollama not ready after 5 minutes."
        kill $FAKE_OLLAMA_PID 2>/dev/null || true
        exit 1
    fi
    sleep 5
done

# Run dce build
echo ""
echo "Running dce build at $(date)..."
DCE_CLI=$(dirname "$VENV_PYTHON")/dce
if [ -f "$DCE_CLI" ]; then
    cd "$DCE_DIR"
    "$DCE_CLI" build
else
    # Fallback: run via python module
    cd "$DCE_DIR"
    "$VENV_PYTHON" -m databao_context_engine.cli.commands build
fi

echo ""
echo "========================================"
echo "DCE build complete at $(date)"
echo "========================================"

# Stop fake Ollama
kill $FAKE_OLLAMA_PID 2>/dev/null || true

# Show result
ls -lh "$DCE_DIR/output/dce.duckdb" 2>/dev/null && echo "dce.duckdb built successfully!" || echo "WARNING: dce.duckdb not found"

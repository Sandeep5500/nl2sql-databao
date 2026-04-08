#!/bin/bash
#SBATCH --job-name=dce_enrich
#SBATCH --partition=general
#SBATCH --gres=gpu:A6000:1
#SBATCH --mem=64G
#SBATCH --cpus-per-task=8
#SBATCH --time=03:00:00
#SBATCH --output=/data/user_data/sandeep3/personal/capstone/logs/dce_enrich_%j.out
#SBATCH --error=/data/user_data/sandeep3/personal/capstone/logs/dce_enrich_%j.err

# Self-contained DCE enrichment job.
# Starts vLLM (Qwen3-32B-AWQ) + fast_embed_server on the compute node,
# runs the enrichment script, then cleans up.
#
# Usage:
#   sbatch scripts/serve_enrich_vllm.slurm
#
# After the job finishes, the 29 YAML context files will have LLM descriptions
# and the DuckDB vector store will be re-indexed with enriched content.

set -euo pipefail

CAPSTONE_DIR="/data/user_data/sandeep3/personal/capstone"
HF_HOME="/data/user_data/sandeep3/.cache/huggingface"
ENRICH_VLLM_PORT=8766
EMBED_PORT=11434
MODEL="${MODEL:-Qwen/Qwen3-32B-AWQ}"

echo "========================================"
echo "DCE Enrichment Job Starting"
echo "Node:   $(hostname)"
echo "GPU:    $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'N/A')"
echo "Model:  $MODEL"
echo "Time:   $(date)"
echo "========================================"

module load cuda-12.1 2>/dev/null || true

# ── 1. Start fast_embed_server on this node ───────────────────────────────────
echo "[1/4] Starting fast_embed_server (port $EMBED_PORT)..."
cd "$CAPSTONE_DIR/databao-context-engine"
nohup env HF_HOME="$HF_HOME" \
    uv run python "$CAPSTONE_DIR/scripts/fast_embed_server.py" --port "$EMBED_PORT" \
    > /tmp/fast_embed_enrich.log 2>&1 &
EMBED_PID=$!
echo "  embed server PID: $EMBED_PID"

# ── 2. Start vLLM server in background ───────────────────────────────────────
echo "[2/4] Starting vLLM server ($MODEL on port $ENRICH_VLLM_PORT)..."
cd "$CAPSTONE_DIR/databao-agent"
if ! uv run python -c "import vllm" 2>/dev/null; then
    echo "  Installing vllm..."
    uv pip install vllm --quiet
fi

HF_HOME="$HF_HOME" uv run python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --port "$ENRICH_VLLM_PORT" \
    --host 0.0.0.0 \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.75 \
    --tensor-parallel-size 1 \
    --dtype auto \
    --trust-remote-code \
    > "$CAPSTONE_DIR/logs/vllm_enrich_server.log" 2>&1 &
VLLM_PID=$!
echo "  vLLM PID: $VLLM_PID"

# Write endpoint for reference/debugging
echo "$(hostname):${ENRICH_VLLM_PORT}" > "$CAPSTONE_DIR/logs/vllm_enrich_endpoint.txt"
echo "Model: $MODEL" >> "$CAPSTONE_DIR/logs/vllm_enrich_endpoint.txt"
echo "Started: $(date)" >> "$CAPSTONE_DIR/logs/vllm_enrich_endpoint.txt"

# ── 3. Wait for both servers to be ready ─────────────────────────────────────
echo "[3/4] Waiting for servers to be ready..."

# Wait for embed server (up to 60s)
EMBED_READY=0
for i in $(seq 1 60); do
    if curl -s http://localhost:${EMBED_PORT}/api/tags > /dev/null 2>&1; then
        echo "  Embed server ready (${i}s)"
        EMBED_READY=1
        break
    fi
    sleep 1
done
if [ "$EMBED_READY" -eq 0 ]; then
    echo "  WARNING: embed server did not respond after 60s, check /tmp/fast_embed_enrich.log"
fi

# Wait for vLLM (up to 20 min — first run downloads the model)
VLLM_READY=0
for i in $(seq 1 240); do
    if curl -s http://localhost:${ENRICH_VLLM_PORT}/v1/models > /dev/null 2>&1; then
        echo "  vLLM server ready (${i} x 5s = $((i*5))s)"
        VLLM_READY=1
        break
    fi
    sleep 5
done
if [ "$VLLM_READY" -eq 0 ]; then
    echo "ERROR: vLLM server did not become ready after 20 minutes."
    echo "Check $CAPSTONE_DIR/logs/vllm_enrich_server.log for details."
    kill "$EMBED_PID" "$VLLM_PID" 2>/dev/null || true
    exit 1
fi

echo "  Both servers ready. Starting enrichment..."

# ── 4. Run enrichment ─────────────────────────────────────────────────────────
echo "[4/4] Running DCE enrichment..."
cd "$CAPSTONE_DIR/databao-context-engine"
uv run python "$CAPSTONE_DIR/scripts/enrich_dce.py" \
    --vllm-host localhost \
    --vllm-port "$ENRICH_VLLM_PORT" \
    --vllm-model "$MODEL" \
    --embed-host localhost \
    --embed-port "$EMBED_PORT" \
    --dce-dir "$CAPSTONE_DIR/spider2-dce"

ENRICH_EXIT=$?

echo "========================================"
echo "Enrichment finished with exit code $ENRICH_EXIT"
echo "Time: $(date)"
echo "========================================"

# ── Cleanup ───────────────────────────────────────────────────────────────────
echo "Stopping servers..."
kill "$VLLM_PID" "$EMBED_PID" 2>/dev/null || true
wait "$VLLM_PID" 2>/dev/null || true

exit $ENRICH_EXIT

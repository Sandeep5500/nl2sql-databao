#!/bin/bash
#SBATCH --job-name=vllm_qwen35
#SBATCH --partition=general
#SBATCH --gres=gpu:L40S:1
#SBATCH --mem=64G
#SBATCH --cpus-per-task=8
#SBATCH --time=12:00:00
#SBATCH --output=/data/user_data/sandeep3/personal/nl2sql-databao/logs/vllm/vllm_%j.out
#SBATCH --error=/data/user_data/sandeep3/personal/nl2sql-databao/logs/vllm/vllm_%j.err

# Serve Qwen3.5-9B via vLLM for the nl2sql-v2 harness (Phase 0 baseline).
#
# Differences from serve_vllm.slurm (GLM):
#   - BF16, no AWQ (9B fits L40S 48GB with room for 60K-token KV cache)
#   - tool parser: qwen3_coder + reasoning parser qwen3 (per Qwen3.5 vLLM recipe);
#     if this vLLM version lacks qwen3_coder, fall back: TOOL_CALL_PARSER=hermes
#   - VLLM_MLA_DISABLE stays exported: no-op for Qwen, avoids surprises if MODEL
#     is overridden to GLM
#
# Usage:
#   sbatch scripts/serve_vllm_qwen35.slurm
#   MODEL=Qwen/Qwen3.5-9B MAX_MODEL_LEN=60000 sbatch scripts/serve_vllm_qwen35.slurm

set -e

CAPSTONE_DIR="/data/user_data/sandeep3/personal/nl2sql-databao"
VLLM_PORT="${VLLM_PORT:-8765}"
MODEL="${MODEL:-Qwen/Qwen3.5-9B}"
HF_HOME="/data/user_data/sandeep3/.cache/huggingface"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-60000}"
TP_SIZE="${TP_SIZE:-1}"
TOOL_CALL_PARSER="${TOOL_CALL_PARSER:-qwen3_coder}"

mkdir -p "$CAPSTONE_DIR/logs/vllm"

echo "========================================"
echo "vLLM serve job starting (Qwen3.5)"
echo "Node:   $(hostname)"
echo "GPU:    $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'N/A')"
echo "Model:  $MODEL"
echo "Parser: $TOOL_CALL_PARSER"
echo "Port:   $VLLM_PORT"
echo "MaxLen: $MAX_MODEL_LEN"
echo "Time:   $(date)"
echo "========================================"

echo "$(hostname):${VLLM_PORT}" > "$CAPSTONE_DIR/logs/vllm_endpoint.txt"
echo "Model: $MODEL" >> "$CAPSTONE_DIR/logs/vllm_endpoint.txt"
echo "Started: $(date)" >> "$CAPSTONE_DIR/logs/vllm_endpoint.txt"

module load cuda-12.1 2>/dev/null || true

cd "$CAPSTONE_DIR/databao-agent"
VENV_PYTHON="$CAPSTONE_DIR/.vllm-venv/bin/python"

if [ ! -f "$VENV_PYTHON" ] || ! "$VENV_PYTHON" -c "import torch.types" 2>/dev/null; then
    echo "Recreating venv (missing or broken torch)..."
    rm -rf "$CAPSTONE_DIR/.vllm-venv"
    python3.12 -m venv "$CAPSTONE_DIR/.vllm-venv"
fi

if ! "$VENV_PYTHON" -c "import vllm" 2>/dev/null; then
    echo "Installing vllm==0.18.1..."
    uv pip install --python "$VENV_PYTHON" "vllm==0.18.1" numpy --quiet
fi

echo "Installing transformers==5.5.3 + regex..."
uv pip install --python "$VENV_PYTHON" --quiet "transformers==5.5.3" "regex>=2025.10.22" --upgrade

echo "Starting vLLM server..."
export VLLM_MLA_DISABLE=1

HF_HOME="$HF_HOME" "$VENV_PYTHON" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --port "$VLLM_PORT" \
    --host 0.0.0.0 \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization 0.92 \
    --tensor-parallel-size "$TP_SIZE" \
    --dtype bfloat16 \
    --trust-remote-code \
    --enforce-eager \
    --enable-auto-tool-choice \
    --tool-call-parser "$TOOL_CALL_PARSER" \
    --reasoning-parser qwen3

echo "vLLM server exited"

#!/bin/bash
#SBATCH --job-name=vllm_qwen35
#SBATCH --partition=general
#SBATCH --gres=gpu:L40S:1
#SBATCH --mem=64G
#SBATCH --cpus-per-task=8
#SBATCH --time=12:00:00
#SBATCH --output=logs/vllm/vllm_%j.out
#SBATCH --error=logs/vllm/vllm_%j.err

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
#   Submit FROM THE REPO ROOT (the --output paths are relative to it):
#     mkdir -p logs/vllm
#     sbatch --partition=<yours> --qos=<yours> --gres=gpu:A6000:1 \
#            nl2sql-v2/slurm/serve_vllm_qwen35.slurm
#   A larger model across two GPUs, in its own venv (leaves the 9B setup alone):
#     MODEL=Qwen/Qwen3.6-27B TP_SIZE=2 VLLM_VERSION=0.19.0 \
#       VENV_DIR=$PWD/.vllm-venv-0.19 VLLM_PORT=8766 \
#       sbatch --partition=<yours> --qos=<yours> --gres=gpu:A6000:2 --mem=96G \
#              nl2sql-v2/slurm/serve_vllm_qwen35.slurm
#   Check what your account may use:
#     sacctmgr show assoc where user=$USER format=account,partition,qos%40

set -e

# Portable across users: override CAPSTONE_DIR to point elsewhere, otherwise
# resolve from this script's own location (slurm/ -> nl2sql-v2/ -> repo root).
CAPSTONE_DIR="${CAPSTONE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
VLLM_PORT="${VLLM_PORT:-8765}"
MODEL="${MODEL:-Qwen/Qwen3.5-9B}"
# Model weights are ~18GB — keep them off the home quota.
HF_HOME="${HF_HOME:-/data/user_data/$USER/.cache/huggingface}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-60000}"
TP_SIZE="${TP_SIZE:-1}"
# Larger or newer models may need a newer vLLM. Give each version its own venv
# so upgrading for one model never breaks the working 9B setup.
VLLM_VERSION="${VLLM_VERSION:-0.18.1}"
TRANSFORMERS_VERSION="${TRANSFORMERS_VERSION:-5.5.3}"
VENV_DIR="${VENV_DIR:-$CAPSTONE_DIR/.vllm-venv}"
TOOL_CALL_PARSER="${TOOL_CALL_PARSER:-qwen3_coder}"

mkdir -p "$CAPSTONE_DIR/logs/vllm" "$HF_HOME"
echo "Repo:   $CAPSTONE_DIR"
echo "HF_HOME:$HF_HOME"

echo "========================================"
echo "vLLM serve job starting (Qwen3.5)"
echo "Node:   $(hostname)"
echo "GPU:    $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'N/A')"
echo "Model:  $MODEL"
echo "Parser: $TOOL_CALL_PARSER"
echo "Port:   $VLLM_PORT"
echo "MaxLen: $MAX_MODEL_LEN"
echo "TP:     $TP_SIZE   vLLM: $VLLM_VERSION   venv: $VENV_DIR"
echo "Time:   $(date)"
echo "========================================"

echo "$(hostname):${VLLM_PORT}" > "$CAPSTONE_DIR/logs/vllm_endpoint.txt"
echo "Model: $MODEL" >> "$CAPSTONE_DIR/logs/vllm_endpoint.txt"
echo "Started: $(date)" >> "$CAPSTONE_DIR/logs/vllm_endpoint.txt"

module load cuda-12.1 2>/dev/null || true

cd "$CAPSTONE_DIR"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ ! -f "$VENV_PYTHON" ] || ! "$VENV_PYTHON" -c "import torch.types" 2>/dev/null; then
    echo "Recreating venv (missing or broken torch)..."
    rm -rf "$VENV_DIR"
    python3.12 -m venv "$VENV_DIR"
fi

if ! "$VENV_PYTHON" -c "import vllm, sys; sys.exit(vllm.__version__ != '$VLLM_VERSION')" 2>/dev/null; then
    echo "Installing vllm==$VLLM_VERSION into $VENV_DIR ..."
    uv pip install --python "$VENV_PYTHON" "vllm==$VLLM_VERSION" numpy --quiet
fi

echo "Installing transformers==$TRANSFORMERS_VERSION + regex..."
uv pip install --python "$VENV_PYTHON" --quiet "transformers==$TRANSFORMERS_VERSION" "regex>=2025.10.22" --upgrade

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

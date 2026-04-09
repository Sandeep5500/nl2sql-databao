#!/bin/bash
#SBATCH --job-name=vllm_nl2sql
#SBATCH --partition=GPU-shared
#SBATCH --account=cis260009p
#SBATCH --gres=gpu:h100-80:1
#SBATCH --mem=80G
#SBATCH --cpus-per-task=8
#SBATCH --time=08:00:00
#SBATCH --output=/jet/home/dpalagan/nl2sql-databao/logs/vllm_%j.out
#SBATCH --error=/jet/home/dpalagan/nl2sql-databao/logs/vllm_%j.err

# Serve GLM-4.7-Flash-AWQ via vLLM on PSC Bridges-2 for databao-agent benchmark.
#
# GPU: H100-80 (80 GB HBM3)
#   VRAM budget:
#     Total:          80 GB
#     gpu_mem_util:   × 0.90  →  72 GB usable
#     GLM-4.7-Flash-AWQ weights (INT4 AWQ):  ~17 GB
#     KV cache headroom:                     ~55 GB  →  comfortably fits 60K context
#
#   Why NOT L40S-48:
#     L40S has 48 GB — same as A6000. After weights, only ~26 GB for KV cache,
#     which caps usable context at ~28K tokens. The complex_oracle / log / f1
#     schemas exceed 38K tokens and would still hit HTTP 400 (context overflow).
#     H100-80 is the minimum GPU that eliminates all 14 A2 overflow failures.
#
#   Why NOT V100-32:
#     After weights only ~12 GB for KV cache — limits context to ~15–20K tokens.
#     Worse than our A6000 baseline.
#
# Model: QuantTrio/GLM-4.7-Flash-AWQ
#   MoE 30B-A3B, INT4 AWQ, ~17 GB VRAM
#   Best tool-call reliability for LangGraph agent loops
#   Scored 8/15 (53%) on 15-question re-run with all fixes applied
#
# First run: model will be downloaded to HF cache (~17 GB, ~5–10 min on PSC)
# Subsequent runs: loads from cache instantly
#
# Usage:
#   sbatch scripts/psc_serve_vllm.slurm
#   # Then submit benchmark once endpoint is ready:
#   sbatch scripts/psc_run_benchmark.slurm
#
# To use H100 fallback if queue is long — alternative: 2× L40S (TP=2):
#   Change to: --gres=gpu:l40s-48:2  --mem=96G
#   And set:   TP_SIZE=2 below

set -e

WORK_DIR="/jet/home/dpalagan/nl2sql-databao"
HF_HOME="/ocean/projects/cis260009p/dpalagan/huggingface_cache"
VLLM_PORT="${VLLM_PORT:-8765}"
MODEL="${MODEL:-QuantTrio/GLM-4.7-Flash-AWQ}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-60000}"
TP_SIZE="${TP_SIZE:-1}"

mkdir -p "$WORK_DIR/logs"

echo "========================================"
echo "vLLM serve — PSC Bridges-2"
echo "Node:   $(hostname)"
echo "GPU:    $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'N/A')"
echo "Model:  $MODEL"
echo "Port:   $VLLM_PORT"
echo "MaxLen: $MAX_MODEL_LEN"
echo "TP:     $TP_SIZE"
echo "Time:   $(date)"
echo "========================================"

# Write endpoint for benchmark script to discover
echo "$(hostname):${VLLM_PORT}" > "$WORK_DIR/logs/vllm_endpoint.txt"
echo "Model: $MODEL"            >> "$WORK_DIR/logs/vllm_endpoint.txt"
echo "Started: $(date)"         >> "$WORK_DIR/logs/vllm_endpoint.txt"

# Load CUDA
module load cuda/12.2.0 2>/dev/null || module load cuda 2>/dev/null || true

VENV_PYTHON="$WORK_DIR/databao-agent/.venv/bin/python"

# Install vLLM if missing
if ! "$VENV_PYTHON" -c "import vllm" 2>/dev/null; then
    echo "Installing vllm..."
    "$VENV_PYTHON" -m pip install vllm --quiet
fi

# GLM-4.7-Flash requires transformers from git main (glm4_moe_lite architecture)
echo "Installing transformers from git main (required for GLM-4.7-Flash)..."
"$VENV_PYTHON" -m pip install --quiet \
    "git+https://github.com/huggingface/transformers.git" --upgrade
# transformers git main needs regex >= 2025.10.22
"$VENV_PYTHON" -m pip install --quiet "regex>=2025.10.22" --no-deps

# VLLM_MLA_DISABLE=1: fall back from TRITON_MLA to standard FlashAttention.
# Avoids bus errors seen with GLM's MLA attention on some vLLM versions.
export VLLM_MLA_DISABLE=1
export HF_HOME="$HF_HOME"
export HUGGINGFACE_HUB_CACHE="$HF_HOME"

echo "Starting vLLM server..."
echo "(First run: model download ~17 GB, allow 5–10 min before benchmark starts)"

"$VENV_PYTHON" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --port "$VLLM_PORT" \
    --host 0.0.0.0 \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization 0.90 \
    --tensor-parallel-size "$TP_SIZE" \
    --dtype float16 \
    --quantization awq \
    --trust-remote-code \
    --enforce-eager \
    --enable-auto-tool-choice \
    --tool-call-parser glm47

echo "vLLM server exited at $(date)"

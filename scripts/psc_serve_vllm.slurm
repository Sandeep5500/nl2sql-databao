#!/bin/bash
#SBATCH --job-name=vllm_nl2sql
#SBATCH --partition=GPU-shared
#SBATCH --account=cis260009p
#SBATCH --gres=gpu:h100-80:1
#SBATCH --mem=80G
#SBATCH --cpus-per-task=8
#SBATCH --time=08:00:00
#SBATCH --output=/ocean/projects/cis260009p/dpalagan/nl2sql-databao/logs/vllm_%j.out
#SBATCH --error=/ocean/projects/cis260009p/dpalagan/nl2sql-databao/logs/vllm_%j.err

# Serve XiYanSQL-QwenCoder-32B-2504 via vLLM on PSC Bridges-2 for databao-agent benchmark.
#
# GPU: H100-80 (80 GB HBM3)
#   VRAM budget:
#     Total:          80 GB
#     gpu_mem_util:   × 0.92  →  73.6 GB usable
#     XiYanSQL-QwenCoder-32B (BF16, dense 32B):  ~64 GB weights
#     KV cache headroom:                          ~9.6 GB  →  ~32K context
#
#   Context window note:
#     32K covers the majority of Spider2 schemas. A few very large schemas
#     (complex_oracle, log, f1) may still exceed 32K and trigger HTTP 400.
#     If overflows persist, switch to 2× H100-80 with TP_SIZE=2 for 60K+.
#
#   Fallback — 2× H100-80 (full context, no overflows):
#     Change: --gres=gpu:h100-80:2  --mem=160G
#     And set: TP_SIZE=2 below
#
# Model: XGenerationLab/XiYanSQL-QwenCoder-32B-2504
#   SQL-specialist fine-tune of Qwen2.5-Coder-32B (BF16 dense)
#   Strong schema understanding and structured SQL generation
#   Tool calling via hermes parser (native vLLM support, no special hacks needed)
#
# First run: model downloaded to HF cache (~64 GB, ~15–20 min on PSC)
# Subsequent runs: loads from cache in ~2–3 min
#
# Usage:
#   sbatch scripts/psc_serve_vllm.slurm
#   # Then submit benchmark once endpoint is ready:
#   sbatch scripts/psc_run_benchmark.slurm

set -e

WORK_DIR="/ocean/projects/cis260009p/dpalagan/nl2sql-databao"
HF_HOME="/ocean/projects/cis260009p/dpalagan/huggingface_cache"
VLLM_PORT="${VLLM_PORT:-8765}"
MODEL="${MODEL:-XGenerationLab/XiYanSQL-QwenCoder-32B-2504}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-32000}"
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

export HF_HOME="$HF_HOME"
export HUGGINGFACE_HUB_CACHE="$HF_HOME"

echo "Starting vLLM server..."
echo "(First run: model download ~64 GB, allow 15–20 min before benchmark starts)"

"$VENV_PYTHON" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --port "$VLLM_PORT" \
    --host 0.0.0.0 \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization 0.92 \
    --tensor-parallel-size "$TP_SIZE" \
    --dtype bfloat16 \
    --trust-remote-code \
    --enable-auto-tool-choice \
    --tool-call-parser hermes

echo "vLLM server exited at $(date)"

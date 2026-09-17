#!/bin/bash
#SBATCH --job-name=vllm_databao
#SBATCH --partition=GPU-shared
#SBATCH --gres=gpu:h100-80:1
#SBATCH --mem=64G
#SBATCH --cpus-per-task=4
#SBATCH --time=12:00:00
#SBATCH --output=/ocean/projects/cis240137p/jpark46/capstone/logs/vllm_%j.out
#SBATCH --error=/ocean/projects/cis240137p/jpark46/capstone/logs/vllm_%j.err

# Serve a local LLM via vLLM with OpenAI-compatible API for databao-agent.
#
# Model configuration (set MODEL env var to override):
#   Default:  QuantTrio/GLM-4.7-Flash-AWQ  (MoE 30B-A3B, INT4 AWQ, ~17GB — best for coding/SQL)
#   Fallback: Qwen/Qwen3-32B-AWQ          (32B dense, INT4 AWQ, ~18GB)
#   Smaller:  Qwen/Qwen3-8B               (smaller, faster)
#
# Usage:
#   sbatch serve_vllm_psc.slurm                                   # GLM (default)
#   MODEL=Qwen/Qwen3-32B-AWQ sbatch serve_vllm_psc.slurm          # Qwen3-32B
#   MODEL=Qwen/Qwen3-8B sbatch serve_vllm_psc.slurm               # Qwen3-8B
#
# After the job starts, the benchmark script auto-discovers the endpoint from
#   logs/vllm_endpoint.txt  (written by this script on startup)

set -e

CAPSTONE_DIR="/ocean/projects/cis240137p/jpark46/capstone"
VLLM_PORT="${VLLM_PORT:-8765}"
MODEL="${MODEL:-QuantTrio/GLM-4.7-Flash-AWQ}"
HF_HOME="/ocean/projects/cis240137p/jpark46/.cache/huggingface"
VENV_DIR="$CAPSTONE_DIR/vllm-venv"

# H100-80GB has ~60 GiB free for KV cache after weights (~17 GiB for GLM).
# 60000 tokens fits comfortably without hitting memory limits.
MAX_MODEL_LEN="${MAX_MODEL_LEN:-60000}"

# Tool call parser depends on model family.
# GLM: glm45  |  Qwen3: hermes
if [[ "$MODEL" == *"GLM"* ]] || [[ "$MODEL" == *"glm"* ]]; then
    TOOL_CALL_PARSER="glm45"
else
    TOOL_CALL_PARSER="hermes"
fi

mkdir -p "$CAPSTONE_DIR/logs"

echo "========================================"
echo "vLLM serve job starting"
echo "Node:   $(hostname)"
echo "GPU:    $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'N/A')"
echo "Model:  $MODEL"
echo "Parser: $TOOL_CALL_PARSER"
echo "Port:   $VLLM_PORT"
echo "MaxLen: $MAX_MODEL_LEN"
echo "Time:   $(date)"
echo "========================================"

# Write node/port info for the benchmark script to discover
echo "$(hostname):${VLLM_PORT}" > "$CAPSTONE_DIR/logs/vllm_endpoint.txt"
echo "Model: $MODEL" >> "$CAPSTONE_DIR/logs/vllm_endpoint.txt"
echo "Started: $(date)" >> "$CAPSTONE_DIR/logs/vllm_endpoint.txt"

module load cuda 2>/dev/null || true

VENV_PYTHON="$VENV_DIR/bin/python"

# vllm-env already has vllm installed. Fix transformers version per run.
# GLM-4.7-Flash-AWQ requires transformers from git main (glm4_moe_lite architecture).
# Qwen3 works with stable transformers >=4.56 that vllm requires.
echo "Restoring stable transformers..."
"$VENV_DIR/bin/pip" install "transformers>=4.56,<5" --quiet --upgrade

if [[ "$MODEL" == *"GLM"* ]] || [[ "$MODEL" == *"glm"* ]]; then
    echo "GLM model: installing transformers from git main (required for glm4_moe_lite)..."
    "$VENV_DIR/bin/pip" install \
        "git+https://github.com/huggingface/transformers.git" \
        --quiet --upgrade
    # transformers git main requires regex>=2025.10.22
    echo "Force-upgrading regex..."
    "$VENV_DIR/bin/pip" install "regex==2026.4.4" --no-deps --quiet
fi

echo "Starting vLLM server..."

# VLLM_MLA_DISABLE=1: disables TRITON_MLA attention backend for GLM-4.7-Flash.
# Falls back to standard FlashAttention, avoiding bus errors.
# Safe to set for all models (no-op when MLA isn't used).
export VLLM_MLA_DISABLE=1

# Redirect HuggingFace cache to ocean storage (avoids home quota)
export HF_HOME="$HF_HOME"
export TRANSFORMERS_CACHE="$HF_HOME"

HF_HOME="$HF_HOME" "$VENV_PYTHON" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --port "$VLLM_PORT" \
    --host 0.0.0.0 \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization 0.92 \
    --tensor-parallel-size 1 \
    --dtype float16 \
    --quantization awq \
    --trust-remote-code \
    --enforce-eager \
    --enable-auto-tool-choice \
    --tool-call-parser "$TOOL_CALL_PARSER"

echo "vLLM server exited"

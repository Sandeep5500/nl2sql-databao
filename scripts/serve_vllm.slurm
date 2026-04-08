#!/bin/bash
#SBATCH --job-name=vllm_databao
#SBATCH --partition=general
#SBATCH --gres=gpu:A100_80GB:1
#SBATCH --mem=64G
#SBATCH --cpus-per-task=8
#SBATCH --time=12:00:00
#SBATCH --output=/data/user_data/sandeep3/personal/nl2sql-databao/logs/vllm_%j.out
#SBATCH --error=/data/user_data/sandeep3/personal/nl2sql-databao/logs/vllm_%j.err

# Serve a local LLM via vLLM with OpenAI-compatible API for databao-agent.
#
# Model configuration (set MODEL env var to override):
#   Default:  QuantTrio/GLM-4.7-Flash-AWQ  (MoE 30B-A3B, INT4 AWQ, ~17GB — best for coding/SQL)
#   Fallback: Qwen/Qwen3-32B-AWQ          (32B dense, INT4 AWQ, ~18GB — no MLA, more stable)
#   Smaller:  Qwen/Qwen3-8B               (already cached, smaller)
#
# GLM-4.7-Flash-AWQ uses TRITON_MLA attention. In vLLM >= 0.18.1 the old env var
# VLLM_ATTENTION_BACKEND was removed; the fix is now VLLM_MLA_DISABLE=1 which
# falls back to FlashAttention. This was needed to avoid bus errors on A6000 nodes;
# we keep it set on A100_80GB too because TRITON_MLA still has occasional issues.
#
# Usage:
#   sbatch serve_vllm.slurm                                   # GLM (default)
#   MODEL=Qwen/Qwen3-32B-AWQ sbatch serve_vllm.slurm          # Qwen3-32B
#   MODEL=Qwen/Qwen3-8B sbatch serve_vllm.slurm               # Qwen3-8B
#
# After the job starts, the benchmark script auto-discovers the endpoint from
#   logs/vllm_endpoint.txt  (written by this script on startup)

set -e

CAPSTONE_DIR="/data/user_data/sandeep3/personal/nl2sql-databao"
VLLM_PORT="${VLLM_PORT:-8765}"
MODEL="${MODEL:-QuantTrio/GLM-4.7-Flash-AWQ}"
HF_HOME="/data/user_data/sandeep3/.cache/huggingface"

# Context length: GLM-4.7-Flash-AWQ on A100_80GB has ~57 GiB free for KV cache after
# weights (~17 GiB), enough to comfortably fit 60K tokens of context. This removes the
# tight context-window constraint we had on A6000 (28K cap) and lets the agent run long
# multi-turn retrieval + reasoning loops without VLLMValidationError on input length.
MAX_MODEL_LEN="${MAX_MODEL_LEN:-60000}"

# Tool call parser depends on model family.
# GLM: glm47  |  Qwen3: hermes
if [[ "$MODEL" == *"GLM"* ]] || [[ "$MODEL" == *"glm"* ]]; then
    TOOL_CALL_PARSER="glm47"
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

module load cuda-12.1 2>/dev/null || true

cd "$CAPSTONE_DIR/databao-agent"
VENV_PYTHON="$CAPSTONE_DIR/databao-agent/.venv/bin/python"

if ! "$VENV_PYTHON" -c "import vllm" 2>/dev/null; then
    echo "Installing vllm..."
    uv pip install --python "$VENV_PYTHON" vllm --quiet
fi

# GLM-4.7-Flash requires transformers from git main (glm4_moe_lite architecture).
# Qwen3 works with stable PyPI transformers. We always restore stable first,
# then upgrade to git main only for GLM.
echo "Restoring stable transformers..."
uv pip install --python "$VENV_PYTHON" --quiet "transformers" --upgrade

if [[ "$MODEL" == *"GLM"* ]] || [[ "$MODEL" == *"glm"* ]]; then
    echo "GLM model: installing transformers from git main (required for glm4_moe_lite)..."
    uv pip install --python "$VENV_PYTHON" --quiet \
        "git+https://github.com/huggingface/transformers.git" \
        --upgrade
    # uv.lock pins regex==2025.9.18; transformers git main requires >=2025.10.22.
    echo "Force-upgrading regex (bypasses uv.lock pin)..."
    uv pip install --python "$VENV_PYTHON" --quiet "regex==2026.4.4" --no-deps
fi

echo "Starting vLLM server..."

# VLLM_MLA_DISABLE=1: disables TRITON_MLA attention backend for GLM-4.7-Flash.
# In vLLM >= 0.18.1 this replaces the removed VLLM_ATTENTION_BACKEND=FLASH_ATTN env var.
# With MLA disabled, vLLM falls back to standard FlashAttention, avoiding bus errors on A6000.
# Safe to set for all models (no-op when MLA isn't used, e.g. Qwen3).
export VLLM_MLA_DISABLE=1

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

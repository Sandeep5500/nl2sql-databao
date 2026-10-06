#!/bin/bash
#SBATCH --job-name=vllm_arctic
#SBATCH --partition=lilab
#SBATCH --qos=lilab_qos
#SBATCH --gres=gpu:A6000:1
#SBATCH --mem=48G
#SBATCH --cpus-per-task=8
#SBATCH --time=36:00:00
#SBATCH --output=/data/user_data/sandeep3/personal/nl2sql-databao/logs/vllm/arctic_%j.out
#SBATCH --error=/data/user_data/sandeep3/personal/nl2sql-databao/logs/vllm/arctic_%j.err

# Serve Arctic-Text2SQL-R1-7B (Qwen2.5-Coder base) for the single-shot lane and
# the draft_sql tool. Deliberately minimal flags: no tool parser (the model has
# no tool training) and no reasoning parser (we strip <think> client-side).

set -e
CAPSTONE_DIR="/data/user_data/sandeep3/personal/nl2sql-databao"
VLLM_PORT="${VLLM_PORT:-8766}"
MODEL="${MODEL:-Snowflake/Arctic-Text2SQL-R1-7B}"
HF_HOME="/data/user_data/sandeep3/.cache/huggingface"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"

mkdir -p "$CAPSTONE_DIR/logs/vllm"
echo "$(hostname):${VLLM_PORT}" > "$CAPSTONE_DIR/logs/vllm_endpoint_arctic.txt"
echo "Model: $MODEL" >> "$CAPSTONE_DIR/logs/vllm_endpoint_arctic.txt"

module load cuda-12.1 2>/dev/null || true
VENV_PYTHON="$CAPSTONE_DIR/.vllm-venv/bin/python"

echo "Ensuring transformers==5.5.3 + regex>=2025.10.22 (see CLAUDE.md)..."
uv pip install --python "$VENV_PYTHON" --quiet "transformers==5.5.3" "regex>=2025.10.22" --upgrade

echo "Node: $(hostname) | Model: $MODEL | Port: $VLLM_PORT"
# ENABLE_TOOLS=1 adds function-calling support (hermes parser, Qwen2.5 family)
# for experiments that run Arctic as the agent actor rather than a draft backend.
EXTRA_FLAGS=""
if [ "${ENABLE_TOOLS:-0}" = "1" ]; then
    EXTRA_FLAGS="--enable-auto-tool-choice --tool-call-parser hermes"
fi

HF_HOME="$HF_HOME" "$VENV_PYTHON" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --port "$VLLM_PORT" \
    --host 0.0.0.0 \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization 0.90 \
    --dtype bfloat16 \
    --enforce-eager \
    $EXTRA_FLAGS

echo "vLLM server exited"

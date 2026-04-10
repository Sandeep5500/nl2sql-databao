#!/bin/bash
#SBATCH --job-name=vllm_A100
#SBATCH --partition=general
#SBATCH --gres=gpu:A100_40GB:1
#SBATCH --mem=64G
#SBATCH --cpus-per-task=8
#SBATCH --time=12:00:00
#SBATCH --output=/data/user_data/sandeep3/personal/nl2sql-databao/logs/vllm/vllm_%j.out
#SBATCH --error=/data/user_data/sandeep3/personal/nl2sql-databao/logs/vllm/vllm_%j.err

CAPSTONE_DIR="/data/user_data/sandeep3/personal/nl2sql-databao"
VLLM_PORT=8765
MODEL="QuantTrio/GLM-4.7-Flash-AWQ"
HF_HOME="/data/user_data/sandeep3/.cache/huggingface"
MAX_MODEL_LEN=20000

mkdir -p "$CAPSTONE_DIR/logs"
echo "$(hostname):${VLLM_PORT}" > "$CAPSTONE_DIR/logs/vllm_endpoint.txt"
echo "Model: $MODEL" >> "$CAPSTONE_DIR/logs/vllm_endpoint.txt"
echo "Started: $(date)" >> "$CAPSTONE_DIR/logs/vllm_endpoint.txt"

echo "=== vLLM A100_40GB $(date) ===" && echo "Node: $(hostname)" && echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

module load cuda-12.1 2>/dev/null || true
cd "$CAPSTONE_DIR/databao-agent"
VENV_PYTHON="$CAPSTONE_DIR/databao-agent/.venv/bin/python"

rm -rf .venv && python3.12 -m venv .venv
uv pip install --python "$VENV_PYTHON" vllm --quiet
uv pip install --python "$VENV_PYTHON" --quiet "transformers" --upgrade
uv pip install --python "$VENV_PYTHON" --quiet "git+https://github.com/huggingface/transformers.git" --upgrade
uv pip install --python "$VENV_PYTHON" --quiet "regex==2026.4.4" --no-deps

export VLLM_MLA_DISABLE=1
HF_HOME="$HF_HOME" "$VENV_PYTHON" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" --port "$VLLM_PORT" --host 0.0.0.0 \
    --max-model-len "$MAX_MODEL_LEN" --gpu-memory-utilization 0.85 \
    --dtype float16 --quantization awq --trust-remote-code \
    --enable-auto-tool-choice --tool-call-parser glm47

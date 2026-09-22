#!/bin/bash
#SBATCH --job-name=validator
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=2:00:00
#SBATCH --output=logs/teacher/validator_%j.out
#SBATCH --error=logs/teacher/validator_%j.err

# Serve a model, run the validator over the frozen pass@4 candidates, stop.
# Submit FROM THE REPO ROOT:
#   MODEL=Qwen/Qwen3.5-9B TAG=9b PORT=8780 sbatch --gres=gpu:1 ... nl2sql-v2/slurm/validator_run.slurm
set -eo pipefail
REPO="${REPO:-$(pwd)}"; cd "$REPO"
MODEL="${MODEL:-Qwen/Qwen3.5-9B}"; TAG="${TAG:-9b}"; PORT="${PORT:-8780}"
TP="${TP:-1}"; WORKERS="${WORKERS:-8}"; EXTRA="${EXTRA:-}"
VENV="${VENV:-$REPO/.vllm-venv-0.19}"
export HF_HOME="${HF_HOME:-/data/user_data/$USER/.cache/huggingface}"
LOG="$REPO/logs/teacher"; mkdir -p "$LOG"
echo "node $(hostname) | $MODEL | TP=$TP | tag=$TAG | $(date)"

"$VENV/bin/python" -m vllm.entrypoints.openai.api_server --model "$MODEL" --port "$PORT" \
    --host 0.0.0.0 --max-model-len 60000 --gpu-memory-utilization 0.92 \
    --tensor-parallel-size "$TP" --dtype bfloat16 --trust-remote-code --enforce-eager \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
    > "$LOG/vllm_validator_${SLURM_JOB_ID}.log" 2>&1 &
VLLM_PID=$!
trap 'kill $VLLM_PID 2>/dev/null; wait $VLLM_PID 2>/dev/null' EXIT
for _ in $(seq 1 120); do
    curl -sf "localhost:$PORT/health" >/dev/null && break
    kill -0 $VLLM_PID 2>/dev/null || { echo "vLLM exited:"; tail -30 "$LOG/vllm_validator_${SLURM_JOB_ID}.log"; exit 1; }
    sleep 15
done
curl -sf "localhost:$PORT/health" >/dev/null || { echo "vLLM never became healthy"; exit 1; }
echo "server healthy $(date +%T)"

cd nl2sql-v2
uv run python scripts/validator_select.py --endpoint "http://localhost:$PORT/v1" --model "$MODEL" \
    --workers "$WORKERS" $EXTRA \
    --out "../results/validator_${TAG}.csv" --trace-dir "../logs/traces/validator_${TAG}"
echo "finished $(date)"

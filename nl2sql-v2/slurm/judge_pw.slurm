#!/bin/bash
#SBATCH --job-name=judge_pw
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=4:00:00
set -eo pipefail
REPO="${REPO:-$(pwd)}"; cd "$REPO"
MODEL="${MODEL:-QuantTrio/Qwen3.6-35B-A3B-AWQ}"
TAG="${TAG:-pwrg}"; PORT="${PORT:-8813}"; TP="${TP:-1}"; WORKERS="${WORKERS:-12}"
INPUTS="${INPUTS:-validator_inputs_rg.json}"; DTYPE="${DTYPE:-auto}"
VENV="${VENV:-$REPO/.vllm-venv-0.19}"
export HF_HOME="${HF_HOME:-/data/user_data/$USER/.cache/huggingface}"
LOG="$REPO/logs/teacher"; mkdir -p "$LOG"
echo "node $(hostname) | $MODEL | $(date)"
"$VENV/bin/python" -m vllm.entrypoints.openai.api_server --model "$MODEL" --port "$PORT" \
    --host 0.0.0.0 --max-model-len 32768 --gpu-memory-utilization 0.92 \
    --tensor-parallel-size "$TP" --dtype "$DTYPE" --trust-remote-code --enforce-eager \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
    > "$LOG/vllm_pw_${SLURM_JOB_ID}.log" 2>&1 &
VLLM_PID=$!
trap 'kill $VLLM_PID 2>/dev/null; wait 2>/dev/null' EXIT
for _ in $(seq 1 160); do
    curl -sf "localhost:$PORT/health" >/dev/null && break
    kill -0 $VLLM_PID 2>/dev/null || { echo "vLLM exited:"; tail -40 "$LOG/vllm_pw_${SLURM_JOB_ID}.log"; exit 1; }
    sleep 15
done
curl -sf "localhost:$PORT/health" >/dev/null || { echo "vLLM never healthy"; exit 1; }
echo "server healthy $(date +%T)"
cd nl2sql-v2
uv run python scripts/validator_pairwise.py --endpoint "http://localhost:$PORT/v1" \
    --model "$MODEL" --workers "$WORKERS" --inputs "$INPUTS" \
    --out "../results/validator_${TAG}.csv" --trace-dir "../logs/traces/validator_${TAG}"
echo "finished $(date)"

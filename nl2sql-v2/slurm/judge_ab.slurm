#!/bin/bash
#SBATCH --job-name=judge_ab
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=4:00:00

# Judge prompt A/B/C over a FROZEN candidate pool. Nothing is re-executed and the
# judge is near-deterministic (98% identical picks across sessions), so unlike the
# agent-side runs this comparison is reproducible: a difference here is real.
#
# Submit FROM THE REPO ROOT:
#   MODEL=QuantTrio/Qwen3.6-35B-A3B-AWQ INPUTS=validator_inputs_rg.json \
#     sbatch -p preempt --qos=preempt_qos --gres=gpu:1 --requeue nl2sql-v2/slurm/judge_ab.slurm

set -eo pipefail
REPO="${REPO:-$(pwd)}"; cd "$REPO"
MODEL="${MODEL:-QuantTrio/Qwen3.6-35B-A3B-AWQ}"
TAG="${TAG:-jrg}"; PORT="${PORT:-8811}"; TP="${TP:-1}"; WORKERS="${WORKERS:-8}"
INPUTS="${INPUTS:-validator_inputs_rg.json}"
PROMPTS="${PROMPTS:-base shape scorer}"
DTYPE="${DTYPE:-auto}"
VENV="${VENV:-$REPO/.vllm-venv-0.19}"
export HF_HOME="${HF_HOME:-/data/user_data/$USER/.cache/huggingface}"
LOG="$REPO/logs/teacher"; mkdir -p "$LOG"
echo "node $(hostname) | $MODEL | $(date)"

"$VENV/bin/python" -m vllm.entrypoints.openai.api_server --model "$MODEL" --port "$PORT" \
    --host 0.0.0.0 --max-model-len 32768 --gpu-memory-utilization 0.92 \
    --tensor-parallel-size "$TP" --dtype "$DTYPE" --trust-remote-code --enforce-eager \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
    > "$LOG/vllm_judge_${SLURM_JOB_ID}.log" 2>&1 &
VLLM_PID=$!
trap 'kill $VLLM_PID 2>/dev/null; wait 2>/dev/null' EXIT
for _ in $(seq 1 160); do
    curl -sf "localhost:$PORT/health" >/dev/null && break
    kill -0 $VLLM_PID 2>/dev/null || { echo "vLLM exited:"; tail -40 "$LOG/vllm_judge_${SLURM_JOB_ID}.log"; exit 1; }
    sleep 15
done
curl -sf "localhost:$PORT/health" >/dev/null || { echo "vLLM never healthy"; tail -40 "$LOG/vllm_judge_${SLURM_JOB_ID}.log"; exit 1; }
echo "server healthy $(date +%T)"

cd nl2sql-v2
for p in $PROMPTS; do
    echo "=== judge prompt=$p  $(date +%T)"
    uv run python scripts/validator_select.py --endpoint "http://localhost:$PORT/v1" \
        --model "$MODEL" --workers "$WORKERS" --inputs "$INPUTS" --prompt "$p" \
        --out "../results/validator_${TAG}_${p}.csv" \
        --trace-dir "../logs/traces/validator_${TAG}_${p}"
done
echo "finished $(date)"

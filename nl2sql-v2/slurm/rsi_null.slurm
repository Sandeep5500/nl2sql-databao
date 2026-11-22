#!/bin/bash
#SBATCH --job-name=synnull
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:A6000:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --requeue
#SBATCH --output=/home/juliep2/synnull_%j.out
# THE NOISE BAND ON THE ACTUAL EVOLVE POPULATION.
#
# --noise 0.03 was measured on the 135 LOCALS at temp 0.7. The loop will judge
# arms on SYNTH at temp 0.0. Run-to-run spread on a different population with a
# different temperature is a different number, and the accept/reject rule is
# only as good as that number. This re-runs held-out with the IDENTICAL config
# and a new tag, so synnull-vs-synbase is a true null: any delta is pure noise.
set -eo pipefail
REPO="${REPO:-/data/user_data/juliep2/nl2sql-databao}"; cd "$REPO"
ROOT=/data/user_data/juliep2/synthroot_full
MODEL="${MODEL:-QuantTrio/Qwen3.6-35B-A3B-AWQ}"
PORT="${PORT:-8861}"; LANES=5
VENV="${VENV:-$REPO/.vllm-venv-0.19}"
export HF_HOME="${HF_HOME:-/data/user_data/$USER/.cache/huggingface}"
LOG="$REPO/logs/synnull"; mkdir -p "$LOG"
echo "=== $(date) node=$(hostname) attempt=${SLURM_RESTART_COUNT:-0} ==="
HELDOUT=$(cat "$ROOT/splits/heldout.txt")

"$VENV/bin/python" -m vllm.entrypoints.openai.api_server --model "$MODEL" --port "$PORT" \
    --host 0.0.0.0 --max-model-len 60000 --gpu-memory-utilization 0.92 \
    --tensor-parallel-size 1 --dtype auto --trust-remote-code --enforce-eager \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
    > "$LOG/vllm_${SLURM_JOB_ID}.log" 2>&1 &
VLLM_PID=$!
trap 'kill $VLLM_PID 2>/dev/null; wait 2>/dev/null' EXIT
for _ in $(seq 1 160); do
    curl -sf "localhost:$PORT/health" >/dev/null && break
    kill -0 $VLLM_PID 2>/dev/null || { echo "vLLM exited:"; tail -40 "$LOG/vllm_${SLURM_JOB_ID}.log"; exit 1; }
    sleep 15
done
curl -sf "localhost:$PORT/health" >/dev/null || { echo "vLLM never healthy"; exit 1; }
EP="http://localhost:$PORT/v1"; echo "[serve] healthy $(date +%T)"
cd nl2sql-v2
COMMON="--endpoint $EP --model $MODEL --context-mode full --temperature 0.0 --max-steps 30 --resume"

echo "=== null replicate of heldout  $(date +%T)"
PIDS=""
for i in $(seq 0 $((LANES-1))); do
    NL2SQL_DATA_ROOT=$ROOT uv run python scripts/run_benchmark.py $COMMON \
        --instances "$HELDOUT" --shard "$i/$LANES" \
        --output "../results/synnull_heldout_${i}.csv" \
        --trace-dir "../logs/traces/synnull_heldout_${i}" \
        > "$LOG/heldout_${i}.log" 2>&1 &
    PIDS="$PIDS $!"
done
for p in $PIDS; do wait "$p" || echo "  shard $p nonzero"; done
echo "=== finished $(date)"

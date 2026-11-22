#!/bin/bash
#SBATCH --job-name=synbase
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --requeue
#SBATCH --output=/home/juliep2/synbase_%j.out
# The RSI baseline: split the synthetic root by database, then run the
# UNMODIFIED harness once over evolve and once over held-out. Every later arm
# is compared against these two numbers.
#
# --resume makes this safe under preemption: finished questions are skipped.
set -eo pipefail
REPO="${REPO:-/data/user_data/juliep2/nl2sql-databao}"; cd "$REPO"
ROOT=/data/user_data/juliep2/synthroot_full
MODEL="${MODEL:-QuantTrio/Qwen3.6-35B-A3B-AWQ}"
PORT="${PORT:-8857}"; LANES=5
VENV="${VENV:-$REPO/.vllm-venv-0.19}"
export HF_HOME="${HF_HOME:-/data/user_data/$USER/.cache/huggingface}"
LOG="$REPO/logs/synbase"; mkdir -p "$LOG"
echo "=== $(date) node=$(hostname) attempt=${SLURM_RESTART_COUNT:-0} ==="

# 1. splits (idempotent; same seed gives the same split every time)
python3 -u /home/juliep2/split_synth.py --root "$ROOT" --evolve 250 --heldout 250
EVOLVE=$(cat "$ROOT/splits/evolve.txt")
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

run_split () {
    TAG=$1; IDS=$2
    echo "=== $TAG  $(date +%T)"
    PIDS=""
    for i in $(seq 0 $((LANES-1))); do
        NL2SQL_DATA_ROOT=$ROOT uv run python scripts/run_benchmark.py $COMMON \
            --instances "$IDS" --shard "$i/$LANES" \
            --output "../results/synbase_${TAG}_${i}.csv" \
            --trace-dir "../logs/traces/synbase_${TAG}_${i}" \
            > "$LOG/${TAG}_${i}.log" 2>&1 &
        PIDS="$PIDS $!"
    done
    for p in $PIDS; do wait "$p" || echo "  $TAG shard $p nonzero"; done
    echo "=== $TAG done $(date +%T)"
}

run_split evolve  "$EVOLVE"
run_split heldout "$HELDOUT"
echo "=== finished $(date)"

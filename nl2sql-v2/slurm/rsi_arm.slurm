#!/bin/bash
#SBATCH --job-name=rsiarm
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:A6000:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --requeue
#SBATCH --output=/home/juliep2/rsiarm_%j.out
# One RSI arm. Identical to the baseline in every respect except the patch.
#
#   TAG    name for this arm's outputs, e.g. r1
#   SPLIT  evolve | heldout
#   PATCH  path to the proposer's diff
#
# Patch application is idempotent so a requeue after preemption does not apply
# it twice: if the reverse patch would apply, it is already in place.
set -eo pipefail
REPO="${REPO:-/data/user_data/juliep2/nl2sql-databao}"; cd "$REPO"
TAG="${TAG:?set TAG}"; SPLIT="${SPLIT:-evolve}"
PATCH="${PATCH:?set PATCH}"
ROOT=/data/user_data/juliep2/synthroot_full
MODEL="${MODEL:-QuantTrio/Qwen3.6-35B-A3B-AWQ}"
PORT="${PORT:-8869}"; LANES=5
VENV="${VENV:-$REPO/.vllm-venv-0.19}"
export HF_HOME="${HF_HOME:-/data/user_data/$USER/.cache/huggingface}"
LOG="$REPO/logs/rsiarm_${TAG}_${SPLIT}"; mkdir -p "$LOG"
echo "=== $(date) node=$(hostname) attempt=${SLURM_RESTART_COUNT:-0} ==="
echo "arm=$TAG split=$SPLIT patch=$PATCH"

cd "$REPO/nl2sql-v2"
if patch -p1 --dry-run --reverse --silent < "$PATCH" >/dev/null 2>&1; then
    echo "[patch] already applied"
else
    patch -p1 --forward < "$PATCH"
    echo "[patch] applied"
fi
echo "[patch] value now:"; grep -n "preview_rows_default" src/nl2sql/config.py
cd "$REPO"

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

IDS=$(cat "$ROOT/splits/${SPLIT}.txt")
cd nl2sql-v2
COMMON="--endpoint $EP --model $MODEL --context-mode full --temperature 0.0 --max-steps 30 --resume"
PIDS=""
for i in $(seq 0 $((LANES-1))); do
    NL2SQL_DATA_ROOT=$ROOT uv run python scripts/run_benchmark.py $COMMON \
        --instances "$IDS" --shard "$i/$LANES" \
        --output "../results/${TAG}_${SPLIT}_${i}.csv" \
        --trace-dir "../logs/traces/${TAG}_${SPLIT}_${i}" \
        > "$LOG/${SPLIT}_${i}.log" 2>&1 &
    PIDS="$PIDS $!"
done
for p in $PIDS; do wait "$p" || echo "  shard $p nonzero"; done
echo "=== finished $(date)"
tail -3 "$LOG"/${SPLIT}_*.log

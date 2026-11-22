#!/bin/bash
#SBATCH --job-name=synprof
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=06:00:00
#SBATCH --output=/home/juliep2/synprof_%j.out
# Is the synthetic set a valid evolve set? Compare its MECHANISM PROFILE
# (fallback rate, step-cap saturation, step distribution) with the locals.
#
# The synthetic databases have no DCE index, so synth cannot use --context-mode
# search. Running synth without search against the existing local numbers (which
# had search) would be confounded, so this job runs BOTH arms with the SAME
# config -- context-mode full, no rubric -- on one server.
set -eo pipefail
REPO="${REPO:-/data/user_data/juliep2/nl2sql-databao}"; cd "$REPO"
SYNROOT=/data/user_data/juliep2/synthroot
MODEL="${MODEL:-QuantTrio/Qwen3.6-35B-A3B-AWQ}"
PORT="${PORT:-8853}"; LANES=5
VENV="${VENV:-$REPO/.vllm-venv-0.19}"
export HF_HOME="${HF_HOME:-/data/user_data/$USER/.cache/huggingface}"
LOG="$REPO/logs/synprof"; mkdir -p "$LOG"
echo "=== $(date) node=$(hostname) attempt=${SLURM_RESTART_COUNT:-0} ==="
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

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

# identical flags for both arms; only the data root differs
COMMON="--endpoint $EP --model $MODEL --context-mode full --temperature 0.0 --max-steps 30 --resume"

echo "=== ARM synth (147 questions, no DCE index available) $(date +%T)"
PIDS=""
for i in $(seq 0 $((LANES-1))); do
    NL2SQL_DATA_ROOT=$SYNROOT uv run python scripts/run_benchmark.py $COMMON \
        --shard "$i/$LANES" \
        --output "../results/synprof_syn_${i}.csv" \
        --trace-dir "../logs/traces/synprof_syn_${i}" \
        > "$LOG/syn_${i}.log" 2>&1 &
    PIDS="$PIDS $!"
done
for p in $PIDS; do wait "$p" || echo "  synth shard $p nonzero"; done
echo "=== synth done $(date +%T)"

echo "=== ARM locals control (same config, 135 questions) $(date +%T)"
PIDS=""
for i in $(seq 0 $((LANES-1))); do
    uv run python scripts/run_benchmark.py $COMMON \
        --shard "$i/$LANES" \
        --output "../results/synprof_loc_${i}.csv" \
        --trace-dir "../logs/traces/synprof_loc_${i}" \
        > "$LOG/loc_${i}.log" 2>&1 &
    PIDS="$PIDS $!"
done
for p in $PIDS; do wait "$p" || echo "  local shard $p nonzero"; done
echo "=== finished $(date)"

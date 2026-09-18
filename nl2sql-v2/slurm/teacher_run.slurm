#!/bin/bash
#SBATCH --job-name=teacher_q36
#SBATCH --partition=lilab
#SBATCH --qos=lilab_qos
#SBATCH --gres=gpu:A6000:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=8:00:00
#SBATCH --output=logs/teacher/teacher_%j.out
#SBATCH --error=logs/teacher/teacher_%j.err

# One self-contained teacher pass: serve the model, smoke-test, run the lanes,
# harvest verified gold SQL, release the GPUs. No server left idling.
#
# Prerequisite: the model's own vLLM venv and weights already exist (build them
# on a CPU node first so GPUs never wait on pip or downloads).
#
# Submit FROM THE REPO ROOT:
#   mkdir -p logs/teacher && sbatch nl2sql-v2/slurm/teacher_run.slurm
# Second pass on what pass 1 missed, with the model's reasoning switched on:
#   TAG=teacher_p2 EXTRA="--thinking --temperature 0.7" \
#     INSTANCES=<ids pass 1 did not accept> sbatch nl2sql-v2/slurm/teacher_run.slurm

set -eo pipefail
REPO="${REPO:-$(pwd)}"
MODEL="${MODEL:-Qwen/Qwen3.6-27B}"
VENV="${VENV:-$REPO/.vllm-venv-0.19}"
PORT="${PORT:-8766}"
TP="${TP:-2}"
LANES="${LANES:-4}"
TAG="${TAG:-teacher_p1}"
MODE="${MODE:-sweep_contract}"
EXTRA="${EXTRA:-}"
export HF_HOME="${HF_HOME:-/data/user_data/$USER/.cache/huggingface}"
LOG="$REPO/logs/teacher"; mkdir -p "$LOG"
cd "$REPO"
echo "node $(hostname) | $MODEL | TP=$TP | lanes=$LANES | tag=$TAG | $(date)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

# 1. serve in the background; stop it on any exit so the GPUs are released
"$VENV/bin/python" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" --port "$PORT" --host 0.0.0.0 \
    --max-model-len 60000 --gpu-memory-utilization 0.92 \
    --tensor-parallel-size "$TP" --dtype bfloat16 --trust-remote-code \
    --enforce-eager --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
    > "$LOG/vllm_${SLURM_JOB_ID}.log" 2>&1 &
VLLM_PID=$!
trap 'kill $VLLM_PID 2>/dev/null; wait $VLLM_PID 2>/dev/null' EXIT

# 2. wait for health (up to 30 min), failing fast if the server dies
for _ in $(seq 1 120); do
    curl -sf "localhost:$PORT/health" >/dev/null && break
    kill -0 $VLLM_PID 2>/dev/null || { echo "vLLM exited during startup:"; tail -40 "$LOG/vllm_${SLURM_JOB_ID}.log"; exit 1; }
    sleep 15
done
curl -sf "localhost:$PORT/health" >/dev/null || { echo "vLLM not healthy after 30 min"; exit 1; }
echo "server healthy $(date +%T)"

cd nl2sql-v2
EP="http://localhost:$PORT/v1"
TARGETS="${INSTANCES:-$(uv run python scripts/analysis/teacher_targets.py --drop-scalars --require-sweep --quiet)}"
echo "targets ($(echo "$TARGETS" | tr ',' '\n' | wc -l)): $TARGETS"

# 3. smoke one question; abort before the full run if the harness errors
SMOKE="${TARGETS%%,*}"
uv run python scripts/run_benchmark.py --endpoint "$EP" --model "$MODEL" \
    --context-mode "$MODE" --instances "$SMOKE" $EXTRA \
    --output "../results/${TAG}_smoke.csv" > "$LOG/${TAG}_smoke.log" 2>&1
if grep -q ",error," "../results/${TAG}_smoke.csv"; then
    echo "smoke question errored; aborting before the full run:"; tail -20 "$LOG/${TAG}_smoke.log"; exit 1
fi
echo "smoke ok $(date +%T): $(tail -1 ../results/${TAG}_smoke.csv | cut -c1-120)"

# 4. lanes, round-robin sharded, one server serving them all
PIDS=()
for i in $(seq 0 $((LANES - 1))); do
    uv run python scripts/run_benchmark.py --endpoint "$EP" --model "$MODEL" \
        --context-mode "$MODE" --instances "$TARGETS" --shard "$i/$LANES" --resume $EXTRA \
        --output "../results/${TAG}_$i.csv" --trace-dir "../logs/traces/${TAG}_$i" \
        > "$LOG/${TAG}_lane$i.log" 2>&1 &
    PIDS+=($!)
done
for p in "${PIDS[@]}"; do wait "$p" || echo "a lane exited non-zero (resumable)"; done
echo "lanes done $(date +%T)"

# 5. harvest verified gold SQL
uv run python scripts/analysis/harvest_teacher.py --runs "${TAG}_*" \
    --out "teacher_context_${TAG}.json" | tee "$LOG/${TAG}_harvest.txt"
echo "finished $(date)"

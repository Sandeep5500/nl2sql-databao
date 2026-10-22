#!/bin/bash
#SBATCH --job-name=rub_enf
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=12:00:00

# One job: regenerate the rubrics with the fixed planner prompt (and KEEP them, so the
# gate's withheld 46% becomes analysable), then run lanes with the rubric ENFORCED at
# submit time instead of merely advised.
#
# Submit FROM THE REPO ROOT:
#   MODEL=QuantTrio/Qwen3.6-35B-A3B-AWQ sbatch -p preempt --qos=preempt_qos \
#     --gres=gpu:1 --requeue nl2sql-v2/slurm/rubric_enforce.slurm

set -eo pipefail
REPO="${REPO:-$(pwd)}"; cd "$REPO"
MODEL="${MODEL:-QuantTrio/Qwen3.6-35B-A3B-AWQ}"
TAG="${TAG:-q36re}"; PORT="${PORT:-8821}"; TP="${TP:-1}"
LANES="${LANES:-7}"; REPEATS="${REPEATS:-4}"; TEMP="${TEMP:-0.7}"
RUBRIC_DIR="${RUBRIC_DIR:-$REPO/logs/rubrics/r2}"
DTYPE="${DTYPE:-auto}"; VENV="${VENV:-$REPO/.vllm-venv-0.19}"
export HF_HOME="${HF_HOME:-/data/user_data/$USER/.cache/huggingface}"
LOG="$REPO/logs/teacher"; mkdir -p "$LOG" "$RUBRIC_DIR"
echo "node $(hostname) | $MODEL | $(date)"

OLLAMA_BIN="$HOME/.dce/ollama/bin/ollama"
OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=24h "$OLLAMA_BIN" serve \
    > "$LOG/ollama_${SLURM_JOB_ID}.log" 2>&1 &
OLLAMA_PID=$!
export DCE_OLLAMA_HOST=127.0.0.1

"$VENV/bin/python" -m vllm.entrypoints.openai.api_server --model "$MODEL" --port "$PORT" \
    --host 0.0.0.0 --max-model-len 60000 --gpu-memory-utilization 0.92 \
    --tensor-parallel-size "$TP" --dtype "$DTYPE" --trust-remote-code --enforce-eager \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
    > "$LOG/vllm_${SLURM_JOB_ID}.log" 2>&1 &
VLLM_PID=$!
trap 'kill $VLLM_PID $OLLAMA_PID 2>/dev/null; wait 2>/dev/null' EXIT
for _ in $(seq 1 160); do
    curl -sf "localhost:$PORT/health" >/dev/null && break
    kill -0 $VLLM_PID 2>/dev/null || { echo "vLLM exited:"; tail -40 "$LOG/vllm_${SLURM_JOB_ID}.log"; exit 1; }
    sleep 15
done
curl -sf "localhost:$PORT/health" >/dev/null || { echo "vLLM never healthy"; exit 1; }
curl -sf "localhost:11434/api/tags" >/dev/null || echo "WARNING: ollama down; search_context will fail"
EP="http://localhost:$PORT/v1"; echo "server healthy $(date +%T)"
cd nl2sql-v2

# 1. planner pass, 5 turns per question, sharded. Kept on disk this time.
if [ "$(ls -1 "$RUBRIC_DIR" 2>/dev/null | wc -l)" -lt 130 ]; then
    echo "=== rubrics -> $RUBRIC_DIR  $(date +%T)"
    pids=()
    for i in $(seq 0 $((LANES - 1))); do
        uv run python scripts/run_rubric.py --endpoint "$EP" --model "$MODEL" \
            --out-dir "$RUBRIC_DIR" --shard "$i/$LANES" --resume \
            > "$LOG/${TAG}_rub_${i}.log" 2>&1 &
        pids+=($!)
    done
    for p in "${pids[@]}"; do wait "$p" || echo "rubric shard $p nonzero"; done
fi
echo "rubrics on disk: $(ls -1 "$RUBRIC_DIR" | wc -l)  $(date +%T)"

# 2. lanes with the rubric ENFORCED (repeat 0 greedy, the rest sampled)
for r in $(seq 0 $((REPEATS - 1))); do
    T="${TAG}_k$((r + 1))"
    [ "$r" -ge 1 ] && TARG="--temperature $TEMP" || TARG="--temperature $TEMP"
    echo "=== lane $T  $(date +%T)"
    pids=()
    for i in $(seq 0 $((LANES - 1))); do
        uv run python scripts/run_benchmark.py --endpoint "$EP" --model "$MODEL" \
            --context-mode search --schema-overview $TARG \
            --rubric-dir "$RUBRIC_DIR" --rubric-confident-only --rubric-enforce \
            --shard "$i/$LANES" --resume \
            --output "../results/${T}_${i}.csv" \
            --trace-dir "../logs/traces/${T}_${i}" \
            > "$LOG/${T}_${i}.log" 2>&1 &
        pids+=($!)
    done
    for p in "${pids[@]}"; do wait "$p" || echo "lane shard $p nonzero"; done
    echo "lane $T done $(date +%T)"
done
echo "finished $(date)"

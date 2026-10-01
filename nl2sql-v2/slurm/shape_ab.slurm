#!/bin/bash
#SBATCH --job-name=shape_ab
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=10:00:00

# A/B the submit-time shape gate in ONE job, against ONE server: the same model
# runs all 135 questions twice, gate on then gate off, both GREEDY.
#
# Greedy on purpose. The four q36s lanes spanned 55-71 of 135, so a single
# sampled lane cannot be compared to anything; removing sampling makes the two
# arms differ only by the gate, and makes the run reproducible.
#
# Submit FROM THE REPO ROOT on the login node:
#   mkdir -p logs/teacher
#   MODEL=QuantTrio/Qwen3.6-35B-A3B-AWQ sbatch -p preempt --qos=preempt_qos \
#     --gres=gpu:1 --requeue nl2sql-v2/slurm/shape_ab.slurm

set -eo pipefail
REPO="${REPO:-$(pwd)}"; cd "$REPO"
MODEL="${MODEL:-QuantTrio/Qwen3.6-35B-A3B-AWQ}"
VENV="${VENV:-$REPO/.vllm-venv-0.19}"
PORT="${PORT:-8801}"; TP="${TP:-1}"; LANES="${LANES:-7}"
TAG="${TAG:-shape}"; MODE="${MODE:-search}"
EXTRA="${EXTRA:---schema-overview --temperature 0}"
DTYPE="${DTYPE:-auto}"          # AWQ carries its own dtype; never force bfloat16
export HF_HOME="${HF_HOME:-/data/user_data/$USER/.cache/huggingface}"
LOG="$REPO/logs/teacher"; mkdir -p "$LOG"
echo "node $(hostname) | $MODEL | TP=$TP | $(date)"

# embeddings for --context-mode search; without these search_context dies and the
# run is not comparable with q36s (the earlier q36 run lost all 457 calls this way)
OLLAMA_BIN="$HOME/.dce/ollama/bin/ollama"
OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=24h "$OLLAMA_BIN" serve \
    > "$LOG/ollama_${SLURM_JOB_ID}.log" 2>&1 &
OLLAMA_PID=$!
export DCE_OLLAMA_HOST=127.0.0.1

"$VENV/bin/python" -m vllm.entrypoints.openai.api_server --model "$MODEL" \
    --port "$PORT" --host 0.0.0.0 --max-model-len 60000 --gpu-memory-utilization 0.92 \
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
curl -sf "localhost:$PORT/health" >/dev/null || { echo "vLLM never healthy"; tail -40 "$LOG/vllm_${SLURM_JOB_ID}.log"; exit 1; }
curl -sf "localhost:11434/api/tags" >/dev/null || echo "WARNING: ollama not answering; search_context will fail"
EP="http://localhost:$PORT/v1"
echo "server healthy $(date +%T)"

cd nl2sql-v2
# smoke first: the gate changed submit_result's signature, so a model that cannot
# fill the new required args would silently fail every question
uv run python scripts/run_benchmark.py --endpoint "$EP" --model "$MODEL" \
    --context-mode "$MODE" --instances local039,local202,local004 $EXTRA \
    --output "../results/${TAG}_smoke.csv" \
    --trace-dir "../logs/traces/${TAG}_smoke" > "$LOG/${TAG}_smoke.log" 2>&1 || true
echo "=== smoke:"; cat "../results/${TAG}_smoke.csv" | cut -c1-140
grep -c shape_refusal ../logs/traces/${TAG}_smoke/*.json 2>/dev/null | sed 's/^/   refusals: /' || true
if grep -q ",error," "../results/${TAG}_smoke.csv"; then
    echo "smoke errored; aborting"; tail -30 "$LOG/${TAG}_smoke.log"; exit 1
fi

run_arm () {   # $1 = tag suffix, $2 = extra flags
    local t="${TAG}_$1"
    echo "=== arm $t  $(date +%T)"
    local pids=()
    for i in $(seq 0 $((LANES - 1))); do
        uv run python scripts/run_benchmark.py --endpoint "$EP" --model "$MODEL" \
            --context-mode "$MODE" $EXTRA $2 --shard "$i/$LANES" --resume \
            --output "../results/${t}_${i}.csv" \
            --trace-dir "../logs/traces/${t}_${i}" \
            > "$LOG/${t}_${i}.log" 2>&1 &
        pids+=($!)
    done
    for p in "${pids[@]}"; do wait "$p" || echo "lane $p exited nonzero"; done
    echo "arm $t done $(date +%T): $(cat ../results/${t}_*.csv | grep -c ',1,' || true) correct rows"
}

run_arm gate ""                    # gate on (the default)
run_arm ctrl "--no-shape-check"    # same everything, gate off

echo "=== gate report"
uv run python scripts/analysis/shape_gate_report.py --run "${TAG}_gate_*" \
    --control "${TAG}_ctrl_*" || true
echo "finished $(date)"

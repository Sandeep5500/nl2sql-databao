#!/bin/bash
#SBATCH --job-name=q36f
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=16:00:00

# Arm "q36f": the presentation-loss bundle. Everything here recovers answers the
# agent already computed correctly -- none of it is a capability change.
#
#   1. prompts.py      ISO dates; no rounding below 4dp; emit both identifiers
#   2. rubric.py       required booleans answer_is_single_row /
#                      include_zero_count_entities -- the planner can no longer
#                      name the right reading in open_points and then abstain
#   3. --rubric-enforce   the committed row count is checked at submit time
#                      (never passed in ANY run before this one)
#   4. --step-extension 15  an episode that runs out of budget without submitting
#                      gets one short extension instead of dying into the salvage
#                      path, whose candidates are correct 5% of the time vs 59%
#
# Same setup as the team's pass@4 runs: Qwen3.6-35B, temp 0.7, 4 repeats,
# --context-mode search --schema-overview, explored notes on (default).
#
# The rubrics MUST be regenerated -- the schema gained required fields, so r2 is
# not compatible. RUBRIC_DIR defaults to a NEW directory for that reason.
#
# Submit FROM THE REPO ROOT:
#   MODEL=QuantTrio/Qwen3.6-35B-A3B-AWQ sbatch -p preempt --qos=preempt_qos \
#     --gres=gpu:1 --requeue nl2sql-v2/slurm/presentation_arm.slurm

set -eo pipefail
REPO="${REPO:-$(pwd)}"; cd "$REPO"
MODEL="${MODEL:-QuantTrio/Qwen3.6-35B-A3B-AWQ}"
TAG="${TAG:-q36f}"; PORT="${PORT:-8823}"; TP="${TP:-1}"
LANES="${LANES:-7}"; REPEATS="${REPEATS:-4}"; TEMP="${TEMP:-0.7}"
RUBRIC_DIR="${RUBRIC_DIR:-$REPO/logs/rubrics/r3}"
STEP_EXT="${STEP_EXT:-15}"
DTYPE="${DTYPE:-auto}"; VENV="${VENV:-$REPO/.vllm-venv-0.19}"
export HF_HOME="${HF_HOME:-/data/user_data/$USER/.cache/huggingface}"
LOG="$REPO/logs/teacher"; mkdir -p "$LOG" "$RUBRIC_DIR"
echo "node $(hostname) | $MODEL | tag=$TAG | $(date)"

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

# 1. planner pass with the required booleans. New dir: r2 predates the schema.
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

# GATE: the schema change is the point of this arm. If the planner did not fill the
# required booleans, the run measures nothing -- stop rather than burn 9 hours.
python3 - "$RUBRIC_DIR" <<'PY'
import json, sys, pathlib
d = pathlib.Path(sys.argv[1]); n = ok = single = zero = 0
for f in sorted(d.glob("local*.json")):
    try: r = json.load(open(f))["rubric"]
    except Exception: continue
    n += 1
    has = ("answer_is_single_row" in r) and ("include_zero_count_entities" in r)
    ok += has
    single += r.get("answer_is_single_row") is True
    zero += r.get("include_zero_count_entities") is True
print(f"rubrics={n}  with both booleans={ok}  single_row={single}  include_zero={zero}")
if n < 130 or ok < 0.9 * n:
    sys.exit(f"ABORT: only {ok}/{n} rubrics carry the required booleans")
PY

# 2. lanes: rubric ENFORCED + step extension on budget exhaustion.
for r in $(seq 1 "$REPEATS"); do
    T="${TAG}_pass4_k${r}"
    echo "=== lane $T  $(date +%T)"
    pids=()
    for i in $(seq 0 $((LANES - 1))); do
        uv run python scripts/run_benchmark.py --endpoint "$EP" --model "$MODEL" \
            --context-mode search --schema-overview --temperature "$TEMP" \
            --rubric-dir "$RUBRIC_DIR" --rubric-confident-only --rubric-enforce \
            --step-extension "$STEP_EXT" \
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

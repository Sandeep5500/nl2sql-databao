#!/bin/bash
# diff_cmp on JEV-27B (Nov 2026 selection eval). One vLLM engine, tensor-parallel over 2 GPUs, serves
# autotrust/JEV-27B both ways: System 1 decisions through the jev-decision adapter, and System 2, which
# is Qwen3.8-27B bit-identical to the release, with thinking. rejudge_pools.py re-judges every contested
# and easy pool of the selection eval set (Spider2 both halves and BigQuery) in two stages:
#   1. System 1, one call per ordered pair: jev (judge_pools.py's state) and jev_cmp (the same state
#      plus the result comparison), into $OUT/calls_jev.jsonl, $OUT/calls_jev_cmp.jsonl
#   2. System 2 with thinking, 4 samples per ordered pair, as the 35B variant arms: base and diff_cmp,
#      into $OUT/calls_base.jsonl, $OUT/calls_diff_cmp.jsonl
# The GPUs are checked before the model loads, and both paths must pass a smoke test before any call.
# Every stage resumes, so a requeued job continues. STAGES picks the stages (default "1 2"). Stage 2 is
# bound by the KV cache (about 30 sequences on 2 x 48 GB), so it can be split over jobs by prompt: each
# variant has its own calls file, so jobs with different S2_VARIANTS share $OUT safely (give each its
# own PORT in case two land on one node):
#   sbatch --export=ALL,STAGES=2,S2_VARIANTS=base ... ; sbatch --export=ALL,STAGES=2,S2_VARIANTS=diff_cmp,PORT=8797 ...
# or by samples, since draws are independent: give each job its own OUT, LOG and PORT and its share in
# S2_SAMPLES, then renumber each job's samples before merging (selection_eval.py keys calls by sample).
# Rough rates (Nov 14): a diff_cmp call takes about 2x an old-prompt call, and an A6000 about 1.4x a 6000 Ada.
# EVALSET, COMPARISONS, BQ_POOLS, BQ_REF_PREFIX, BQ_BASE and BQ_QUESTIONS point the job at another eval set
# (the full BigQuery pass@4, Nov 17); REF_PREFIX at other Spider2 reference pools (q36e/q36x, Nov 18:
# groups/sp, from runset_pools.slurm).
#
#   sbatch ~/slurm/jev_variants.slurm                                                   (lilab)
#   sbatch --partition=preempt --qos=preempt_qos \
#       --constraint='A6000|6000Ada|L40S|A100_80GB|H100|H200' ~/slurm/jev_variants.slurm   (preempt)
#
#SBATCH --job-name=jev_var
#SBATCH --partition=lilab
#SBATCH --qos=lilab_qos
#SBATCH --gres=gpu:2
#SBATCH --exclude=babel-w9-28,babel-u9-20,babel-q5-32,babel-o5-20,babel-p5-16
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=2-00:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/jev_var_%j.out
set -u
U=/data/user_data/$USER
M=$U/nl2sql-databao                     # existing checkout: benchmark venv, Spider2 DBs
W=$U/nl2sql-sel
B=$U/bq_passk
V=$W/results/variants                   # eval set and comparisons of the 35B variant arms
OUT=${OUT:-$W/results/variants_jev27b}
JD=$U/models/JEV-27B
REPO=autotrust/JEV-27B
PORT=${PORT:-8796}
STAGES=(${STAGES:-1 2})
S2_VARIANTS=${S2_VARIANTS:-base,diff_cmp}
S2_SAMPLES=${S2_SAMPLES:-4}
LOG=${LOG:-$HOME/joblogs/jev_var}      # readable from the login node, so progress can be watched there
VPY=$U/.vllm031-venv/bin/python         # JEV's qwen3_5_text config needs vLLM 0.31 (see run_jev.slurm)
PY=$M/nl2sql-v2/.venv/bin/python
export HF_HOME=$U/.cache/huggingface NL2SQL_DATA_ROOT=$M
mkdir -p "$LOG"
echo "node=$(hostname) job=$SLURM_JOB_ID restarts=${SLURM_RESTART_COUNT:-0} start=$(date -Is) stages=${STAGES[*]}"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
"$VPY" -c "import sys; sys.path.insert(0, '$HOME/judge-code-staging/nl2sql-v2/scripts')
from gpu_preflight import gpu_preflight; gpu_preflight()" || exit 1
module load cuda-12.1 2>/dev/null || true

serve() {  # $@: extra flags
    "$VPY" -m vllm.entrypoints.openai.api_server --model "$JD" --served-model-name "$REPO" \
        --port "$PORT" --host 0.0.0.0 --max-model-len 49152 --gpu-memory-utilization 0.90 \
        --tensor-parallel-size 2 --dtype bfloat16 --enforce-eager --trust-remote-code \
        --enable-lora --max-lora-rank 32 --lora-modules jev-decision="$JD/adapter_vllm" \
        --logprobs-mode processed_logprobs --reasoning-parser qwen3 "$@" \
        >> "$LOG/vllm_$SLURM_JOB_ID.log" 2>&1 &
    VLLM_PID=$!
    for _ in $(seq 1 240); do
        curl -sf "localhost:$PORT/v1/models" >/dev/null && return 0
        kill -0 $VLLM_PID 2>/dev/null || return 1
        sleep 10
    done
    return 1
}
trap 'kill $VLLM_PID 2>/dev/null' EXIT
# prefix caching (the model card's flags) shares the schema prefix across a pool's pairs; without it if it fails
if ! serve --enable-prefix-caching --mamba-cache-mode align; then
    echo "vLLM with prefix caching did not come up; retrying without"; tail -20 "$LOG/vllm_$SLURM_JOB_ID.log"
    kill $VLLM_PID 2>/dev/null; sleep 30
    serve || { echo "vLLM not up"; tail -40 "$LOG/vllm_$SLURM_JOB_ID.log"; exit 1; }
fi
echo "JEV up $(date -Is)"

cd "$U/judge-code/nl2sql-v2"
# smoke: System 1 must pick the obvious answer confidently and the same twice; System 2 must think, then reply
"$PY" - "$PORT" "$JD" "$REPO" <<'EOF' || { echo "smoke failed"; exit 1; }
import json, sys
sys.path.insert(0, "scripts")
import openai
from judge_pairs import JevJudge
port, jd, repo = sys.argv[1:]
state = ("Database question: How many customers placed more than 5 orders?\n\nCandidate A SQL:\nSELECT COUNT(*) "
         "FROM (SELECT customer_id FROM orders GROUP BY customer_id HAVING COUNT(*) > 5)\nCandidate A execution "
         "result:\ncount\n12\n\nCandidate B SQL:\nSELECT COUNT(*) FROM orders\nCandidate B execution result:\ncount\n4000")
j = JevJudge(f"http://localhost:{port}/v1", jd, 40000)
p = [j.decide("choice", state, "Which candidate SQL query correctly answers the database question?",
              ["Candidate A", "Candidate B"]) for _ in range(2)]
print("smoke System 1 P(A), P(B):", p, flush=True)
assert p[0][0] > 0.8 and abs(p[0][0] - p[1][0]) < 1e-3, "System 1 smoke failed"  # batched bf16 differs ~1e-5
c = openai.OpenAI(base_url=f"http://localhost:{port}/v1", api_key="EMPTY", timeout=600)
r = c.chat.completions.create(model=repo, temperature=0.6, max_tokens=4096,
    messages=[{"role": "user", "content": state.replace("Database question", "You are judging two candidate SQL "
               "answers to a database question.\n\nQuestion") + '\n\nWhich candidate correctly answers the question? '
               'Reply with JSON only: {"winner": "A" or "B", "reason": "<one sentence>"}'}],
    extra_body={"chat_template_kwargs": {"enable_thinking": True}})
m = r.choices[0].message.model_dump()
reasoning = m.get("reasoning") or m.get("reasoning_content") or ""
print(f"smoke System 2: {len(reasoning)} reasoning chars, {r.usage.completion_tokens} tokens, reply {m['content']!r}",
      flush=True)
assert reasoning and json.loads(m["content"][m["content"].index("{"):m["content"].rindex("}") + 1])["winner"] == "A", \
    "System 2 smoke failed"
EOF

ARGS=(--evalset "${EVALSET:-$V/selection_evalset.json}" --pools "$W/results/pools"
      --ref-prefix "${REF_PREFIX:-think35/qwen36-35b-think}" --bq-pools "${BQ_POOLS:-$B/pools}" --bq-ref-prefix "${BQ_REF_PREFIX:-think35_bq}"
      --bq-base "${BQ_BASE:-$B/bigquery_passk_nov2026}" --bq-questions "${BQ_QUESTIONS:-$B/bq_questions.jsonl}"
      --comparisons "${COMPARISONS:-$V/compare_cache.jsonl}" --judge-endpoint "http://localhost:$PORT/v1" --out-dir "$OUT" --resume)
run() {  # $1: stage name, then rejudge_pools.py arguments; repeated while server failures leave calls
    local name=$1; shift
    for pass in 1 2 3; do
        echo "$name: pass $pass $(date -Is)"
        "$PY" scripts/rejudge_pools.py "${ARGS[@]}" "$@" >> "$LOG/$name.log" 2>&1
        left=$("$PY" scripts/rejudge_pools.py "${ARGS[@]}" "$@" --count-only 2>/dev/null)
        echo "$name: exit, calls left: ${left:-?} $(date -Is)"
        [ "${left:-1}" = 0 ] && return 0
        kill -0 $VLLM_PID 2>/dev/null || { echo "vLLM died"; tail -30 "$LOG/vllm_$SLURM_JOB_ID.log"; exit 1; }
    done
}
for st in "${STAGES[@]}"; do
    case $st in
        1) run system1 --variants jev,jev_cmp --jev-dir "$JD" --judge-model jev-decision ;;
        2) run "system2_${S2_VARIANTS//,/_}" --variants "$S2_VARIANTS" --samples "$S2_SAMPLES" \
               --judge-model "$REPO" --workers 128 ;;
    esac
done
echo "exit 0 end=$(date -Is)"

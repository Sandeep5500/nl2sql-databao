#!/bin/bash
# Other model families as the judge (Nov 2026 selection eval), at the size of a Qwen judge we already ran:
#   FAMILY=glm      GLM-4.7-Flash, MoE with 31B total / 3B active (next to Qwen3.6-35B-A3B)
#   FAMILY=mistral  Magistral-Small-2509, 24B dense, reasoning (next to Qwen3.8-27B)
# One vLLM engine, tensor-parallel over 2 GPUs. rejudge_pools.py re-judges every contested and easy pool
# of the selection eval set (Spider2 both halves and BigQuery) with thinking on, as the Qwen arms were:
# variants S2_VARIANTS (default diff_cmp), S2_SAMPLES per ordered pair, temperature 0.6, 8192 tokens,
# into $OUT/calls_<variant>.jsonl. Each family turns thinking on its own way: GLM through enable_thinking,
# Magistral through its reasoning system prompt (SYSTEM_PROMPT.txt).
# The first job of a family downloads the weights into $U/models/<name> (under a lock, so jobs that start
# together download once; a finished download is only checked), and the job installs the staged
# rejudge_pools.py if the deployed one lacks --system-prompt-file. The GPUs are checked before the model
# loads, and a smoke test sent as rejudge_pools.py sends calls must pass before any call. The stage
# resumes, so a requeued job continues. Split by samples as in jev_variants.slurm: each job its own OUT,
# LOG and PORT, then renumber each job's samples before merging. The calls files are copied to
# ~/judge-tmp/fam/<job name>/ every 15 minutes and at exit.
# One arm may be queued twice under one job name (preempt, and lilab when it has room); the first copy to
# start cancels the queued one, and of two copies running at once the lower job id stays.
#
#   sbatch --partition=preempt --qos=preempt_qos --constraint='A6000|6000Ada|L40S|A100_80GB|H100|H200' \
#       --export=ALL,FAMILY=glm,S2_SAMPLES=2,OUT=$W/results/variants_glm,PORT=8811 ~/slurm/family_judge.slurm
#
#SBATCH --job-name=fam_judge
#SBATCH --partition=lilab
#SBATCH --qos=lilab_qos
#SBATCH --gres=gpu:2
#SBATCH --exclude=babel-w9-28,babel-u9-20,babel-q5-32,babel-o5-20
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/fam_judge_%j.out
set -u
for c in $(squeue -u "$USER" -h -n "$SLURM_JOB_NAME" -o "%i:%T"); do  # other copies of this arm
    id=${c%%:*}; st=${c#*:}
    [ "$id" = "$SLURM_JOB_ID" ] && continue
    case $st in
        PENDING|REQUEUED*) scancel "$id" && echo "cancelled queued copy $id" ;;
        *) if [ "$id" -lt "$SLURM_JOB_ID" ]; then echo "copy $id is $st; exiting"; exit 0; fi
           scancel "$id" && echo "cancelled running copy $id" ;;
    esac
done
U=/data/user_data/$USER
M=$U/nl2sql-databao                     # existing checkout: benchmark venv, Spider2 DBs
W=$U/nl2sql-sel
B=$U/bq_passk
V=$W/results/variants                   # eval set and comparisons of the 35B variant arms
FAMILY=${FAMILY:?set FAMILY=glm or FAMILY=mistral}
PORT=${PORT:-8810}
S2_VARIANTS=${S2_VARIANTS:-diff_cmp}
S2_SAMPLES=${S2_SAMPLES:-1}
case $FAMILY in
    glm) NAME=GLM-4.7-Flash; REPO=zai-org/GLM-4.7-Flash; CTK='{"enable_thinking": true}'; SYSFILE=
         FILES="*.json,*.safetensors,*.jinja,README.md"
         FLAGS=(--reasoning-parser glm45 --trust-remote-code) ;;
    mistral) NAME=Magistral-Small-2509; REPO=mistralai/Magistral-Small-2509; CTK='{}'
         SYSFILE=$U/models/$NAME/SYSTEM_PROMPT.txt
         FILES="consolidated.safetensors,params.json,tekken.json,SYSTEM_PROMPT.txt,config.json,generation_config.json,README.md"
         FLAGS=(--reasoning-parser mistral --tokenizer-mode mistral --config-format mistral --load-format mistral
                --limit-mm-per-prompt '{"image": 0}') ;;
    *) echo "unknown FAMILY $FAMILY"; exit 1 ;;
esac
MD=$U/models/$NAME
OUT=${OUT:-$W/results/variants_$FAMILY}
LOG=${LOG:-$HOME/joblogs/fam_$FAMILY}  # readable from the login node, so progress can be watched there
VPY=$U/.vllm031-venv/bin/python
PY=$M/nl2sql-v2/.venv/bin/python
export HF_HOME=$U/.cache/huggingface NL2SQL_DATA_ROOT=$M
# FlashInfer compiles its top-p sampler on first use, and nothing in this venv has ever compiled (Magistral,
# whose defaults set top_p, died on its first request, Nov 16). vLLM's own sampler draws from the same
# top-k/top-p distribution. The venv's bin (ninja) goes on PATH for any other compile.
export VLLM_USE_FLASHINFER_SAMPLER=0 PATH=$U/.vllm031-venv/bin:$PATH
mkdir -p "$LOG"
echo "node=$(hostname) job=$SLURM_JOB_ID restarts=${SLURM_RESTART_COUNT:-0} start=$(date -Is) family=$FAMILY samples=$S2_SAMPLES"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
"$VPY" -c "import sys; sys.path.insert(0, '$HOME/judge-code-staging/nl2sql-v2/scripts')
from gpu_preflight import gpu_preflight; gpu_preflight()" || exit 1
module load cuda-12.1 2>/dev/null || true

C=$U/judge-code/nl2sql-v2/scripts
if ! grep -q -- --system-prompt-file "$C/rejudge_pools.py"; then
    cp "$HOME/judge-code-staging/rejudge_pools.py.new" "$C/rejudge_pools.py.tmp.$SLURM_JOB_ID" \
        && mv -f "$C/rejudge_pools.py.tmp.$SLURM_JOB_ID" "$C/rejudge_pools.py" && echo "installed rejudge_pools.py"
fi
mkdir -p "$U/models"
flock "$U/models/.$NAME.lock" "$VPY" - "$REPO" "$MD" "$FILES" <<'EOF' || { echo "download failed"; exit 1; }
import sys
from huggingface_hub import snapshot_download
repo, md, files = sys.argv[1:]
snapshot_download(repo, local_dir=md, allow_patterns=files.split(","), max_workers=8)
print("weights ready:", md, flush=True)
EOF

"$VPY" -m vllm.entrypoints.openai.api_server --model "$MD" --served-model-name "$REPO" \
    --port "$PORT" --host 0.0.0.0 --max-model-len 49152 --gpu-memory-utilization 0.90 \
    --tensor-parallel-size 2 --dtype bfloat16 --enforce-eager "${FLAGS[@]}" \
    >> "$LOG/vllm_$SLURM_JOB_ID.log" 2>&1 &
VLLM_PID=$!
trap 'kill $VLLM_PID 2>/dev/null' EXIT
for _ in $(seq 1 240); do
    curl -sf "localhost:$PORT/v1/models" >/dev/null && break
    kill -0 $VLLM_PID 2>/dev/null || { echo "vLLM died"; tail -40 "$LOG/vllm_$SLURM_JOB_ID.log"; exit 1; }
    sleep 10
done
curl -sf "localhost:$PORT/v1/models" >/dev/null || { echo "vLLM not up"; tail -40 "$LOG/vllm_$SLURM_JOB_ID.log"; exit 1; }
echo "$NAME up $(date -Is)"

cd "$U/judge-code/nl2sql-v2"
# smoke: sent as rejudge_pools.py sends calls, the judge must think, then pick the obvious answer in JSON
"$PY" - "$PORT" "$REPO" "$CTK" "$SYSFILE" <<'EOF' || { echo "smoke failed"; exit 1; }
import json, sys
import openai
port, repo, ctk, sysfile = sys.argv[1:]
ctk = json.loads(ctk)
system = [{"role": "system", "content": open(sysfile).read()}] if sysfile else []
prompt = ("You are judging two candidate SQL answers to a database question.\n\nQuestion: How many customers "
          "placed more than 5 orders?\n\nCandidate A SQL:\nSELECT COUNT(*) FROM (SELECT customer_id FROM orders "
          "GROUP BY customer_id HAVING COUNT(*) > 5)\nCandidate A execution result:\ncount\n12\n\nCandidate B SQL:\n"
          "SELECT COUNT(*) FROM orders\nCandidate B execution result:\ncount\n4000\n\nWhich candidate correctly "
          'answers the question? Reply with JSON only: {"winner": "A" or "B", "reason": "<one sentence>"}')
c = openai.OpenAI(base_url=f"http://localhost:{port}/v1", api_key="EMPTY", timeout=600)
r = c.chat.completions.create(model=repo, temperature=0.6, max_tokens=4096, logprobs=True, top_logprobs=5,
                              messages=system + [{"role": "user", "content": prompt}],
                              extra_body={"chat_template_kwargs": ctk} if ctk else None)
m = r.choices[0].message.model_dump()
reasoning = m.get("reasoning") or m.get("reasoning_content") or ""
content = m["content"] or ""
print(f"smoke: {len(reasoning)} reasoning chars, {r.usage.completion_tokens} tokens, finish {r.choices[0].finish_reason}, "
      f"reply {content[-200:]!r}", flush=True)
assert reasoning, "no reasoning: thinking is off or the reasoning parser did not split it"
# read as rejudge_pools.py reads it: JSON, or else the last plain "winner" field
import re
block = content[content.index("{"):content.rindex("}") + 1]
try:
    winner = json.loads(block)["winner"]
except ValueError:
    winner = re.findall(r'"winner"\s*:\s*"?([ABab])"?\s*[,}]', block)[-1]
assert winner.upper() == "A", "wrong or unparsable verdict"
EOF

# copies of the calls files every 15 min and at exit, readable from the login node (/data is not)
H=$HOME/judge-tmp/fam/$SLURM_JOB_NAME
mkdir -p "$H" "$OUT"
(while sleep 900; do cp -f "$OUT"/calls_*.jsonl "$H"/ 2>/dev/null; done) &
COPIER=$!
trap 'kill $VLLM_PID $COPIER 2>/dev/null; cp -f "$OUT"/calls_*.jsonl "$H"/ 2>/dev/null' EXIT
ARGS=(--evalset "$V/selection_evalset.json" --pools "$W/results/pools" --bq-pools "$B/pools"
      --bq-base "$B/bigquery_passk_nov2026" --bq-questions "$B/bq_questions.jsonl"
      --comparisons "$V/compare_cache.jsonl" --judge-endpoint "http://localhost:$PORT/v1" --out-dir "$OUT" --resume
      --judge-model "$REPO" --chat-template-kwargs "$CTK" ${SYSFILE:+--system-prompt-file "$SYSFILE"})
name="system2_${S2_VARIANTS//,/_}"
for pass in 1 2 3; do  # repeated while server failures leave calls
    echo "$name: pass $pass $(date -Is)"
    "$PY" scripts/rejudge_pools.py "${ARGS[@]}" --variants "$S2_VARIANTS" --samples "$S2_SAMPLES" --workers 128 \
        >> "$LOG/$name.log" 2>&1
    left=$("$PY" scripts/rejudge_pools.py "${ARGS[@]}" --variants "$S2_VARIANTS" --samples "$S2_SAMPLES" \
           --count-only 2>/dev/null)
    echo "$name: exit, calls left: ${left:-?} $(date -Is)"
    [ "${left:-1}" = 0 ] && break
    kill -0 $VLLM_PID 2>/dev/null || { echo "vLLM died"; tail -30 "$LOG/vllm_$SLURM_JOB_ID.log"; exit 1; }
done
echo "exit 0 end=$(date -Is)"

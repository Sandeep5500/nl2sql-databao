#!/bin/bash
# Stage B step 1 of documents/head_probe_prereg.md, GPU half: the untuned 35B judge, one server per GPU
# with judge_variants.slurm's flags, judges every diff_cmp practice prompt (practice_dc_prompts.slurm)
# 4 times with thinking (scripts/practice_dc.py judge) into $R/practice_dc/<dir>/verdicts_<tag>.jsonl.
# Every file resumes, so a requeued job continues; a file is skipped once its .done marker exists.
# FILES picks the files (default all 7), PORT0 the first server port (two jobs on one node need
# different ones). train_v1 holds half of the pairs, so two 1-GPU jobs split the work evenly:
#
#   sbatch --gres=gpu:1 --export=ALL,FILES=judge_train/train_v1 ~/judge-code-staging/nl2sql-v2/slurm/practice_dc_judge.slurm
#   sbatch --gres=gpu:1 --export=ALL,PORT0=8775,FILES="judge_cplx/cplx_v1 judge_cplx/cplx_v2 judge_claude/claude_v3 \
#       judge_claude/claude_h1 judge_claude/claude_h2 judge_beaver/beaver_p1" ~/judge-code-staging/nl2sql-v2/slurm/practice_dc_judge.slurm
#   (LIMIT=5 for a smoke run)
#
#SBATCH --job-name=practice_dc_judge
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:2
#SBATCH --constraint=A6000|6000Ada|L40S|A100_80GB
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=12:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/practice_dc_judge_%j.out
set -u
U=/data/user_data/$USER
M=$U/nl2sql-databao
R=$U/judge-data/results
P=${P:-$R/practice_dc}
MODEL=QuantTrio/Qwen3.6-35B-A3B-AWQ
LOG=$P/logs
PORT0=${PORT0:-8765}
ALL="judge_train/train_v1 judge_cplx/cplx_v1 judge_cplx/cplx_v2 judge_claude/claude_v3 judge_claude/claude_h1"
ALL="$ALL judge_claude/claude_h2 judge_beaver/beaver_p1"
FILES=(${FILES:-$ALL})
export HF_HOME=$U/.cache/huggingface VLLM_MLA_DISABLE=1 NL2SQL_DATA_ROOT=$M
mkdir -p "$LOG"
echo "node=$(hostname) job=$SLURM_JOB_ID restarts=${SLURM_RESTART_COUNT:-0} start=$(date -Is) files=${FILES[*]}"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
for rel in "${FILES[@]}"; do
    [ -e "$P/${rel%/*}/prompts_${rel##*/}.jsonl.done" ] || { echo "no prompts for $rel: run practice_dc_prompts.slurm first"; exit 1; }
done
GPUS=(${CUDA_VISIBLE_DEVICES//,/ })
PIDS=()
EPS=()
for i in "${!GPUS[@]}"; do
    CUDA_VISIBLE_DEVICES=${GPUS[$i]} "$M/.vllm-venv/bin/python" -m vllm.entrypoints.openai.api_server \
        --model "$MODEL" --port $((PORT0 + i)) --host 0.0.0.0 --max-model-len 60000 \
        --gpu-memory-utilization 0.92 --dtype bfloat16 --enforce-eager --trust-remote-code \
        --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
        --enable-prefix-caching --mamba-cache-mode align \
        > "$LOG/vllm_${SLURM_JOB_ID}_$i.log" 2>&1 &
    PIDS+=($!)
    EPS+=("http://localhost:$((PORT0 + i))/v1")
done
trap 'kill ${PIDS[*]} 2>/dev/null' EXIT
up() { local e; for e in "${EPS[@]}"; do curl -sf "$e/models" >/dev/null || return 1; done; }
for _ in $(seq 1 240); do
    up && break
    for p in "${PIDS[@]}"; do kill -0 "$p" 2>/dev/null || { echo "a vLLM server died"; tail -30 "$LOG"/vllm_${SLURM_JOB_ID}_*.log; exit 1; }; done
    sleep 10
done
up || { echo "vLLM not up after 40 min"; exit 1; }
echo "${#EPS[@]} servers up $(date -Is)"
cd ~/judge-code-staging/nl2sql-v2
PY=$M/nl2sql-v2/.venv/bin/python
EXTRA=()
[ -n "${LIMIT:-}" ] && EXTRA=(--limit "$LIMIT")
for rel in "${FILES[@]}"; do
    dir=${rel%/*}; tag=${rel##*/}
    in=$P/$dir/prompts_$tag.jsonl; out=$P/$dir/verdicts_$tag.jsonl
    [ -e "$out.done" ] && continue
    echo "judging $rel $(date -Is)"
    "$PY" scripts/practice_dc.py judge --prompts "$in" --output "$out" --resume --judge-model "$MODEL" \
        --workers $((48 * ${#EPS[@]})) --judge-endpoint "$(IFS=,; echo "${EPS[*]}")" "${EXTRA[@]}" >> "$LOG/judge_$tag.log" 2>&1
    rc=$?
    tail -2 "$LOG/judge_$tag.log"
    [ $rc = 0 ] && [ -z "${LIMIT:-}" ] && [ "$(wc -l < "$out")" = "$(wc -l < "$in")" ] && touch "$out.done"
done
echo "exit 0 end=$(date -Is)"

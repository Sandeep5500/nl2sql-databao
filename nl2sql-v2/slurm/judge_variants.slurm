#!/bin/bash
# Judge prompt-variant session (Nov 2026 selection eval): serves the untuned 35B judge on both GPUs
# (ports 8765, 8766; the judge_gpu_session flags) and runs the arms queued in $Q, oldest first:
# each $Q/<n>_<name>.args file holds rejudge_pools.py arguments (variants, --select, --samples,
# --out-dir). An arm is marked .done when it finishes with no failed calls left; failed calls are
# retried on the next pass. With every arm done the session waits for new arm files and exits
# when $Q/STOP exists. All arms resume, so a requeued or restarted session just continues.
#
#   sbatch ~/slurm/judge_variants.slurm                                                (lilab)
#   sbatch --partition=preempt --qos=preempt_qos --constraint='A6000|6000Ada|L40S|A100_80GB' \
#       ~/slurm/judge_variants.slurm                                                   (preempt)
# A preempt copy that starts while a lilab copy runs exits at once; a lilab copy cancels the
# preempt copies once its servers answer, before it writes anything.
#
#SBATCH --job-name=judge_var
#SBATCH --partition=lilab
#SBATCH --qos=lilab_qos
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=2-00:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/judge_var_%j.out

set -u
U=/data/user_data/$USER
M=$U/nl2sql-databao                     # existing checkout: vLLM venv, Spider2 DBs, benchmark venv
W=$U/nl2sql-sel                         # pools and results
B=$U/bq_passk
Q=$W/results/variants/queue
LOG=$W/logs/variants
MODEL=QuantTrio/Qwen3.6-35B-A3B-AWQ
export HF_HOME=$U/.cache/huggingface VLLM_MLA_DISABLE=1 NL2SQL_DATA_ROOT=$M
mkdir -p "$Q" "$LOG"
log() { echo "[$(date -Is)] $*"; }
log "node=$(hostname) job=$SLURM_JOB_ID partition=$SLURM_JOB_PARTITION gpus=${CUDA_VISIBLE_DEVICES:-}"
if [ "$SLURM_JOB_PARTITION" != lilab ] && \
        [ -n "$(squeue -h -u "$USER" -n judge_var -p lilab -t RUNNING -o %i)" ]; then
    log "a lilab session is running; exiting"; exit 0
fi
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
module load cuda-12.1 2>/dev/null || true
GPUS=(${CUDA_VISIBLE_DEVICES//,/ })
PIDS=()
for i in 0 1; do
    CUDA_VISIBLE_DEVICES=${GPUS[$i]} "$M/.vllm-venv/bin/python" -m vllm.entrypoints.openai.api_server \
        --model "$MODEL" --port $((8765 + i)) --host 0.0.0.0 --max-model-len 60000 \
        --gpu-memory-utilization 0.92 --dtype bfloat16 --enforce-eager --trust-remote-code \
        --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
        --enable-prefix-caching --mamba-cache-mode align \
        > "$LOG/vllm_${SLURM_JOB_ID}_$i.log" 2>&1 &
    PIDS+=($!)
done
trap 'kill ${PIDS[*]} 2>/dev/null' EXIT
for _ in $(seq 1 240); do
    curl -sf localhost:8765/v1/models >/dev/null && curl -sf localhost:8766/v1/models >/dev/null && break
    for p in "${PIDS[@]}"; do kill -0 "$p" 2>/dev/null || { log "a vLLM server died"; tail -30 "$LOG"/vllm_${SLURM_JOB_ID}_*.log; exit 1; }; done
    sleep 10
done
curl -sf localhost:8765/v1/models >/dev/null && curl -sf localhost:8766/v1/models >/dev/null || { log "vLLM not up after 40 min"; exit 1; }
log "both servers up"
if [ "$SLURM_JOB_PARTITION" = lilab ]; then
    scancel -u "$USER" -n judge_var -p preempt && log "cancelled any preempt session"
    sleep 30
fi
printf 'job=%s\nnode=%s\nendpoints=http://%s:8765/v1,http://%s:8766/v1\nstarted=%s\n' \
    "$SLURM_JOB_ID" "$(hostname)" "$(hostname)" "$(hostname)" "$(date -Is)" > "$HOME/joblogs/judge_var_session.txt"

cd "$U/judge-code/nl2sql-v2"
PY=$M/nl2sql-v2/.venv/bin/python
while true; do
    pending=0
    for f in $(ls "$Q"/*.args 2>/dev/null | sort); do
        [ -e "$f.done" ] && continue
        pending=1
        name=$(basename "$f" .args)
        log "arm $name: start"
        # shellcheck disable=SC2046
        "$PY" scripts/rejudge_pools.py $(cat "$f") --evalset "$W/results/variants/selection_evalset.json" \
            --pools "$W/results/pools" --bq-pools "$B/pools" --bq-base "$B/bigquery_passk_nov2026" \
            --bq-questions "$B/bq_questions.jsonl" --judge-model "$MODEL" \
            --judge-endpoint http://localhost:8765/v1,http://localhost:8766/v1 --resume \
            >> "$LOG/$name.log" 2>&1
        rc=$?
        left=$("$PY" scripts/rejudge_pools.py $(cat "$f") --evalset "$W/results/variants/selection_evalset.json" \
            --pools "$W/results/pools" --bq-pools "$B/pools" --bq-base "$B/bigquery_passk_nov2026" \
            --bq-questions "$B/bq_questions.jsonl" --judge-model "$MODEL" \
            --judge-endpoint http://localhost:8765/v1 --resume --count-only 2>/dev/null)
        log "arm $name: exit $rc, calls left: ${left:-?}"
        [ "$rc" = 0 ] && [ "${left:-1}" = 0 ] && touch "$f.done"
        # calls that keep failing on every server (retry records): give up after two passes without progress
        if [ -n "$left" ] && [ "$left" != 0 ] && [ "$left" = "$(cat "$f.left" 2>/dev/null)" ]; then
            n=$(( $(cat "$f.stuck" 2>/dev/null || echo 0) + 1 )); echo $n > "$f.stuck"
            [ $n -ge 2 ] && { log "arm $name: $left calls keep failing; marking done"; touch "$f.done"; }
        fi
        echo "${left:-}" > "$f.left"
        break   # re-scan the queue: a newer arm file may sort first
    done
    if [ $pending = 0 ]; then
        if [ -e "$Q/STOP" ]; then
            log "queue empty and STOP set; exiting"
            scancel -u "$USER" -n judge_var -t PENDING   # copies still queued on the other partition
            exit 0
        fi
        sleep 300
    fi
done

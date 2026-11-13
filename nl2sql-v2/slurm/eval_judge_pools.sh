#!/bin/bash
# Spider2 selection eval for the tuned judge, run inside the judge GPU session:
#   setsid nohup srun --jobid=<session> --overlap -n1 --cpus-per-task=16 \
#       bash ~/slurm/eval_judge_pools.sh >> ~/joblogs/eval_judge_pools.log 2>&1 < /dev/null &
# Same pools, code (the nl2sql-sel worktree) and judge settings as the Oct 24 baseline
# (pairwise, thinking, 8192 tokens, every ordered pair, 12 shards per run set; a question's pairs
# are judged concurrently, which changes no judgment):
#   - tuned judge (merged AWQ) on a second vLLM, GPU the session's server is not on, port 8766
#   - untuned judge again on the session's server (8765): how much two runs of one judge differ
# Every shard resumes, so after a preemption just relaunch it in the new session.
set -u
U=/data/user_data/$USER; M=$U/nl2sql-databao; W=$U/nl2sql-sel
TUNED=${TUNED:-$U/judge-data/results/judge_train/model/judge_awq}
NAME=${NAME:-judge-tuned-v1}
POOLS=$W/results/pools; SEL=$W/results/sel; LOG=$W/logs/sel
PY=$M/nl2sql-v2/.venv/bin/python
export HF_HOME=$U/.cache/huggingface VLLM_MLA_DISABLE=1
log() { echo "[$(date -Is)] $*"; }

if ! curl -sf localhost:8766/v1/models >/dev/null && ! pgrep -f -- "--port 8766" >/dev/null; then
    g=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | sort -t, -k2 -n | head -1 | cut -d, -f1)
    log "serving $NAME on GPU $g, port 8766"
    CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=$g "$M/.vllm-venv/bin/python" -m vllm.entrypoints.openai.api_server \
        --model "$TUNED" --served-model-name "$NAME" --port 8766 --host 0.0.0.0 --max-model-len 32768 \
        --gpu-memory-utilization 0.85 --dtype bfloat16 --enforce-eager --trust-remote-code \
        --reasoning-parser qwen3 >> "$LOG/${NAME}_vllm.log" 2>&1 < /dev/null &
fi
for _ in $(seq 1 120); do
    curl -sf localhost:8766/v1/models >/dev/null && curl -sf localhost:8765/v1/models >/dev/null && break
    sleep 10
done
curl -sf localhost:8766/v1/models >/dev/null || { log "tuned vLLM not up"; tail -30 "$LOG/${NAME}_vllm.log"; exit 1; }
curl -sf localhost:8765/v1/models >/dev/null || { log "session vLLM not up"; exit 1; }
log "both servers up"

cd "$W/nl2sql-v2"
PIDS=()
run() {  # port model outdir prefix
    mkdir -p "$POOLS/$3"
    for pool in q36rg q36s q36 v2; do for k in $(seq 0 11); do
        "$PY" scripts/judge_pools.py \
            --runs "$SEL/${pool}_pass4_k1.csv,$SEL/${pool}_pass4_k2.csv,$SEL/${pool}_pass4_k3.csv,$SEL/${pool}_pass4_k4.csv" \
            --judge pairwise --judge-endpoint "http://localhost:$1/v1" --judge-model "$2" \
            --thinking --max-tokens 8192 --save-reasoning --pair-workers "${PAIR_WORKERS:-4}" \
            --shard "$k/12" --resume \
            --output "$POOLS/$3/$4_${pool}_n12_s$k.jsonl" > "$LOG/$4_${pool}_s$k.log" 2>&1 &
        PIDS+=($!)
    done; done
}
run 8766 "$NAME" "$NAME" "$NAME"
run 8765 QuantTrio/Qwen3.6-35B-A3B-AWQ think35_rerun qwen36-35b-think-rerun
log "started ${#PIDS[@]} shards"
fail=0
for p in "${PIDS[@]}"; do wait "$p" || fail=$((fail+1)); done
log "shards finished, $fail failed"
[ $fail = 0 ] && log "done"

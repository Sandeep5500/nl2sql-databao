#!/bin/bash
# Unattended chain from agent runs to judge training, inside the judge GPU session. Each
# stage leaves its output under $J (or the agent results) and is skipped when done, so a
# rerun after preemption picks up where it stopped:
#   a. once the bf16 base is downloaded: a training smoke test (train_judge.slurm, SMOKE=1)
#   b. once the agent run train_v1 is done: rerun the episodes that hit DuckDB conversion
#      errors before the db.py fallback was widened, then run the questions added since
#   c. judge verdicts on every right-vs-wrong pair (sample_judge_verdicts.py --resume)
#   d. SFT and DPO files (make_judge_sft_dpo.py)
#   e. if the smoke test finished cleanly: submit the training job (SFT -> DPO -> merge)
# The session serves the model on one GPU; this chain runs a second vLLM on the other, and
# the agent runs and the judge sampling spread over both (restarted here when found dead,
# and started again by a chain relaunched after preemption).
#
#   setsid nohup srun --jobid=<session> --overlap -n1 --cpus-per-task=12 \
#       bash ~/slurm/judge_overnight.sh > ~/joblogs/judge_overnight.log 2>&1 < /dev/null &
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
U=/data/user_data/$USER
C=$U/judge-code
M=$U/nl2sql-databao
D=$U/judge-data
R=$D/results
A=$R/agent/train_v1
J=$R/judge_train
NODE=$(hostname)
RESTARTED=2026-11-01T01:12:00   # train_v1 restarted with the widened fallback
P2=8766                         # the second vLLM
log() { echo "[$(date -Is)] $*"; }
second_server() {               # start it on the emptier GPU unless it answers or is loading
    curl -sf "localhost:$P2/v1/models" >/dev/null && return
    pgrep -f -- "--port $P2" >/dev/null && return
    local g
    g=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | sort -t, -k2 -n | head -1 | cut -d, -f1)
    log "starting a second vLLM on GPU $g, port $P2"
    CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=$g HF_HOME=$U/.cache/huggingface VLLM_MLA_DISABLE=1 \
        "$M/.vllm-venv/bin/python" -m vllm.entrypoints.openai.api_server \
        --model QuantTrio/Qwen3.6-35B-A3B-AWQ --port $P2 --host 0.0.0.0 --max-model-len 60000 \
        --gpu-memory-utilization 0.85 --dtype bfloat16 --enforce-eager --trust-remote-code \
        --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
        >> "$D/logs/vllm2_${SLURM_JOB_ID:-x}.log" 2>&1 < /dev/null &
}
wait_second_server() {          # up to 15 min, then go on with the servers that answer
    for _ in $(seq 1 90); do
        curl -sf "localhost:$P2/v1/models" >/dev/null && { log "second vLLM up"; return; }
        sleep 10
    done
    log "second vLLM not up after 15 min; going on without it"
}
mkdir -p "$J"
log "start on $NODE"
second_server
# keep it up while the stages below block (their clients wait for a server that comes back)
( while sleep 300; do second_server; done ) &

# a. smoke test of the training job, once the base model is downloaded
if [ ! -s "$J/smoke_jobid" ]; then
    until grep -q "^downloaded" ~/joblogs/base_download.log; do
        if ! pgrep -f "snapshot_download" >/dev/null; then  # died: resume the download here
            log "base download not running; resuming it"
            HF_HOME=$U/.cache/huggingface "$C/.venv-train/bin/python" -c \
                "from huggingface_hub import snapshot_download; print('downloaded', snapshot_download('Qwen/Qwen3.6-35B-A3B', max_workers=8))" \
                >> ~/joblogs/base_download.log 2>&1
        fi
        sleep 120
    done
    log "base model downloaded"
    sbatch --parsable --export=ALL,SMOKE=1,DATA=$J/smoke_data,OUT=$J/smoke_model \
        ~/slurm/train_judge.slurm > "$J/smoke_jobid" && log "smoke test submitted: job $(cat "$J/smoke_jobid")"
fi

# b. agent runs
wait_second_server
until grep -q "^done " ~/joblogs/agent_train_v1.log; do
    if ! pgrep -f "run_benchmark.py" >/dev/null; then
        log "agent run not running and not done; restarting it (resume)"
        bash ~/slurm/run_judge_agent.sh train_v1 ~/judge-tmp/train_ids_v1.txt 4 6 >> ~/joblogs/agent_train_v1.log 2>&1
    fi
    sleep 300
done
if [ ! -e "$A/.conversion_reruns_done" ]; then
    python3 - "$A" "$RESTARTED" <<'EOF'
import csv, datetime, glob, os, sys
A, cut = sys.argv[1], datetime.datetime.fromisoformat(sys.argv[2]).timestamp()
redo = set()
for l in range(1, 5):
    for f in glob.glob(f"{A}/traces_lane{l}/*.json"):
        if os.path.getmtime(f) < cut and "Conversion Error" in open(f, errors="replace").read():
            redo.add((l, os.path.basename(f)[:-5]))
for l, iid in sorted(redo):
    for f in glob.glob(f"{A}/lane{l}_s*.csv"):
        rows = list(csv.reader(open(f)))
        keep = [r for r in rows if r[0] != iid]
        if len(keep) < len(rows):
            csv.writer(open(f, "w", newline="")).writerows(keep)
print(f"removed {len(redo)} episodes for rerun: {sorted(redo)}")
EOF
    touch "$A/.conversion_reruns_done"
fi
log "agent top-up: rerun episodes and the questions added since"
wait_second_server
bash ~/slurm/run_judge_agent.sh train_v1 ~/judge-tmp/train_ids_v2.txt 4 6 >> ~/joblogs/agent_train_v1.log 2>&1
log "agent runs done: $(for l in 1 2 3 4; do echo -n "$(($(wc -l < "$A/lane$l.csv") - 1)) "; done)rows per lane"

# c. judge verdicts
cd "$C/nl2sql-v2" || exit 1
export NL2SQL_DATASET_DIR=$D/bird_plat DCE_OLLAMA_HOST=$NODE
if [ ! -e "$J/.verdicts_done" ]; then
    wait_second_server
    log "sampling judge verdicts"
    uv run --project "$M/nl2sql-v2" python scripts/sample_judge_verdicts.py \
        --runs "$A/lane1.csv,$A/lane2.csv,$A/lane3.csv,$A/lane4.csv" \
        --judge-endpoint "http://$NODE:8765/v1,http://$NODE:$P2/v1" --judge-model QuantTrio/Qwen3.6-35B-A3B-AWQ \
        --samples 4 --workers 96 --output "$J/verdicts_train_v1.jsonl" --resume >> "$J/sample.log" 2>&1 \
        && touch "$J/.verdicts_done" || { log "sampling failed; see $J/sample.log"; exit 1; }
fi
log "verdicts: $(wc -l < "$J/verdicts_train_v1.jsonl") questions"

# d. training files
if [ ! -s "$J/data/sft.jsonl" ]; then
    uv run --project "$M/nl2sql-v2" python scripts/make_judge_sft_dpo.py \
        --verdicts "$J/verdicts_train_v1.jsonl" --out-dir "$J/data" > "$J/data_build.log" 2>&1 \
        || { log "building SFT/DPO files failed; see $J/data_build.log"; exit 1; }
fi
log "training files: $(wc -l < "$J/data/sft.jsonl") SFT, $(wc -l < "$J/data/dpo.jsonl") DPO rows"

# e. training, only after a clean smoke test
SMOKE_ID=$(cat "$J/smoke_jobid" 2>/dev/null)
while squeue -h -j "$SMOKE_ID" 2>/dev/null | grep -q .; do sleep 120; done
if [ ! -s "$J/smoke_model/judge_awq/merged_adapter.json" ]; then
    log "smoke test (job $SMOKE_ID) did not finish cleanly; NOT submitting training. See ~/joblogs/judge_train_$SMOKE_ID.out"
    exit 1
fi
if [ ! -s "$J/train_jobid" ]; then
    sbatch --parsable ~/slurm/train_judge.slurm > "$J/train_jobid" \
        && log "training submitted: job $(cat "$J/train_jobid")"
fi
log "done"

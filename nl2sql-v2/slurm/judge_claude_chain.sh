#!/bin/bash
# Candidate pairs for the Claude-written questions of one batch (question_waves.py), run inside the
# judge GPU session (port 8765 serves the untuned model; a second copy is started on 8766):
#   TAG=v3 IDS=~/judge-tmp/claude_ids_v3.txt setsid nohup srun --jobid=<session> --overlap -n1 \
#       --cpus-per-task=8 bash ~/slurm/judge_claude_chain.sh >> ~/joblogs/judge_claude_chain_v3.log 2>&1 < /dev/null &
# Every stage resumes:
#   1. agent runs, 4 lanes at temperature 0.7 (run_judge_agent.sh)
#   2. untuned judge verdicts on every right-vs-wrong pair, 4 samples (sample_judge_verdicts.py);
#      the pairs' prompts and correct letters there are what make_judge_sft_dpo.py trains on
#   3. label check (check_pair_labels.py), as for the complex batches
# Another question set: DS=<dataset dir> SET=<name> (outputs results/judge_<name>, agent/<name>_<TAG>);
# a set with no context index first gets profiles, keys and enrichment (enrich_judge_dce.sh), e.g.
#   DS=$D/beaver SET=beaver TAG=p1 IDS=~/judge-tmp/beaver_ids_p1.txt ...
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
U=/data/user_data/$USER; M=$U/nl2sql-databao; C=$U/judge-code; D=$U/judge-data
TAG=${TAG:?}; IDS=${IDS:?}
DS=${DS:-$D/bird_plat}; SET=${SET:-claude}; R=$D/results/judge_$SET; A=$D/results/agent/${SET}_$TAG
BASE=QuantTrio/Qwen3.6-35B-A3B-AWQ
NODE=$(hostname)
mkdir -p $R
log() { echo "[$(date -Is)] $*"; }
die() { log "STOPPED: $*"; exit 1; }
rsync -a ~/judge-code-staging/ $C/ && cd $C/nl2sql-v2 || die "no code"
export NL2SQL_DATA_ROOT=$M NL2SQL_DATASET_DIR=$DS DCE_OLLAMA_HOST=$NODE
RUN="uv run --project $M/nl2sql-v2 python"

second_server() {  # the untuned model on 8766, on the emptiest GPU
    curl -sf localhost:8766/v1/models | grep -q "\"$BASE\"" && return
    pgrep -f -- "--port 8766" >/dev/null && return  # loading
    local g
    g=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | sort -t, -k2 -n | head -1 | cut -d, -f1)
    log "starting the untuned model on GPU $g, port 8766"
    CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=$g HF_HOME=$U/.cache/huggingface VLLM_MLA_DISABLE=1 \
        "$M/.vllm-venv/bin/python" -m vllm.entrypoints.openai.api_server \
        --model $BASE --port 8766 --host 0.0.0.0 --max-model-len 60000 \
        --gpu-memory-utilization 0.85 --dtype bfloat16 --enforce-eager --trust-remote-code \
        --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
        --enable-prefix-caching --mamba-cache-mode align \
        >> "$R/vllm2_${SLURM_JOB_ID:-x}.log" 2>&1 < /dev/null &
}
ports() {  # the ports serving the untuned model now
    local p out=""
    for p in 8765 8766; do curl -sf localhost:$p/v1/models | grep -q "\"$BASE\"" && out="$out $p"; done
    echo $out
}
second_server
for _ in $(seq 1 60); do  # wait for the second server, as each stage fixes its ports at start
    curl -sf localhost:8766/v1/models >/dev/null && break
    pgrep -f -- "--port 8766" >/dev/null || break
    sleep 15
done
n=$(wc -l < $IDS)
log "start on $NODE; $n questions; untuned servers: $(ports)"

# 0. context index for a new question set: data-only profiles and keys, then enrichment
if [ ! -s $DS/dce/output/dce.duckdb ]; then
    PY=$M/nl2sql-v2/.venv/bin/python
    [ -n "$(ls $DS/dce/output/profile 2>/dev/null)" ] || { log "profiles"; $PY $C/scripts/compute_profile.py \
        --out-dir $DS/dce/output/profile > $R/profile_$SET.log 2>&1 || die "profiles failed; see $R/profile_$SET.log"; }
    [ -n "$(ls $DS/dce/output/keys 2>/dev/null)" ] || { log "keys"; $PY $C/scripts/compute_keys.py \
        --out-dir $DS/dce/output/keys --budget-s 60 > $R/keys_$SET.log 2>&1 || die "keys failed; see $R/keys_$SET.log"; }
    log "enrichment"
    DS=$DS DCE_W=$D/dce_workers_$SET K=3 bash ~/slurm/enrich_judge_dce.sh >> $R/enrich_$SET.log 2>&1 \
        || die "enrichment failed; see $R/enrich_$SET.log"
    cd $C/nl2sql-v2 || die "no code"
fi

# 1. agent runs
lanes_done() {
    local l
    for l in 1 2 3 4; do
        [ -s $A/lane$l.csv ] || return 1
        [ "$(cut -d, -f1 $A/lane$l.csv | grep -cxFf $IDS)" -ge "$n" ] || return 1
    done
}
until lanes_done; do
    P=($(ports)); [ ${#P[@]} -gt 0 ] || { log "no untuned server; waiting"; sleep 120; continue; }
    log "agent runs on $n questions, servers ${P[*]}"
    DS=$DS PORTS="${P[*]}" bash ~/slurm/run_judge_agent.sh ${SET}_$TAG $IDS 4 12 >> $R/agent_$TAG.log 2>&1
    lanes_done || { log "agent lanes incomplete; rerunning (resume)"; sleep 60; }
done
log "agent runs done: $(for l in 1 2 3 4; do echo -n "$(($(wc -l < $A/lane$l.csv) - 1)) "; done)rows per lane"

# 2. untuned judge verdicts
V=$R/verdicts_${SET}_$TAG.jsonl
if [ ! -e $V.done ]; then
    P=($(ports)); [ ${#P[@]} -gt 0 ] || die "no untuned server"
    EP=$(for p in ${P[*]}; do echo -n "http://$NODE:$p/v1,"; done); EP=${EP%,}
    log "sampling judge verdicts on $EP"
    $RUN scripts/sample_judge_verdicts.py --runs $A/lane1.csv,$A/lane2.csv,$A/lane3.csv,$A/lane4.csv \
        --judge-endpoint "$EP" --judge-model $BASE --samples 4 --workers 96 \
        --output $V --resume >> $R/sample_$TAG.log 2>&1 \
        && touch $V.done || die "sampling failed; see $R/sample_$TAG.log"
fi
log "verdicts: $(wc -l < $V) questions"

# 3. label check
L=$R/pair_labels_$TAG.jsonl
if [ ! -e $L.done ]; then
    P=($(ports)); [ ${#P[@]} -gt 0 ] || die "no untuned server"
    EP=$(for p in ${P[*]}; do echo -n "http://$NODE:$p/v1,"; done); EP=${EP%,}
    log "checking pair labels on $EP"
    $RUN scripts/check_pair_labels.py --verdicts $V --endpoint "$EP" --model $BASE --thinking \
        --samples 5 --output $L --resume > $R/pair_labels_$TAG.log 2>&1 \
        && touch $L.done || die "label check failed; see $R/pair_labels_$TAG.log"
fi
log "labels: $(tail -6 $R/pair_labels_$TAG.log | tr '\n' ' ')"
log "done"

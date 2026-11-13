#!/bin/bash
# Complex-question pilot for the judge data, run inside the judge GPU session (port 8765 serves
# the untuned model; it writes, solves and judges here, as the agent and judge are the same model):
#   setsid nohup srun --jobid=<session> --overlap -n1 --cpus-per-task=8 \
#       bash ~/slurm/judge_cplx_chain.sh >> ~/joblogs/judge_cplx_chain.log 2>&1 < /dev/null &
# Why: Spider2's right-vs-wrong pairs have a median of 4 CTEs and 3 joins against 0 and 1 in the
# BIRD-based training pairs, and the v2a judge gained on BIRD-like pairs but not on Spider2.
# Every stage resumes (keep_cplx_chain_alive.sh relaunches it):
#   1. generate_trap_items.py --style complex until TARGET questions are admitted (or
#      MAX_ATTEMPTS attempts), appended to bird_plat as cplx_* (questions.jsonl backed up first)
#   2. agent runs, 4 lanes (run_judge_agent.sh)
#   3. untuned judge verdicts on every right-vs-wrong pair (sample_judge_verdicts.py)
#   4. summary: how often pools are mixed, and how the pairs compare with Spider2's
#   5. label check: is each pair's wrong side really wrong, or another reading of the question
#      (check_pair_labels.py; on the pilot, about half the never-right pairs were the latter)
# Port 8766 belongs to judge_v2_chain.sh while it has a merged judge to gate or evaluate; otherwise
# (a training still queued, the chain done, or not running) a second untuned server is started there
# and used too. When the v2 chain takes the port back, the attempts cut off are not logged and rerun.
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
U=/data/user_data/$USER; M=$U/nl2sql-databao; C=$U/judge-code; D=$U/judge-data
# TAG names one batch of questions: its agent runs, verdicts and label checks are kept apart
# (v1 = the 80-question pilot); TARGET and MAX_ATTEMPTS count all complex questions so far
TAG=${TAG:-v1}
DS=$D/bird_plat; R=$D/results/judge_cplx; A=$D/results/agent/cplx_$TAG
TARGET=${TARGET:-80}; MAX_ATTEMPTS=${MAX_ATTEMPTS:-600}
BASE=QuantTrio/Qwen3.6-35B-A3B-AWQ
NODE=$(hostname)
mkdir -p $R ~/judge-tmp
log() { echo "[$(date -Is)] $*"; }
die() { log "STOPPED: $*"; exit 1; }
rsync -a ~/judge-code-staging/ $C/ && cd $C/nl2sql-v2 || die "no code"
export NL2SQL_DATA_ROOT=$M NL2SQL_DATASET_DIR=$DS DCE_OLLAMA_HOST=$NODE
RUN="uv run --project $M/nl2sql-v2 python"

v2_busy() {  # judge_v2_chain.sh owns port 8766: a merged judge it still has to gate or evaluate
    local T=$D/results/judge_train_v2 m n
    if ! pgrep -f "judge_v2_chain.sh" >/dev/null; then
        tail -1 ~/joblogs/judge_v2_chain.log 2>/dev/null | grep -qE "\] done$|STOPPED:" && return 1
        # not running in this session; it owns 8766 only if a tuned judge is served there
        curl -sf localhost:8766/v1/models | grep -q "judge-tuned"; return
    fi
    for m in $T/model_*/judge_awq/merged_adapter.json; do  # while a training is queued, 8766 is free
        [ -s "$m" ] || continue
        n=${m#$T/model_}; n=${n%%/*}
        [ -e $T/model_$n.failed ] && continue
        [ -s $T/gate_$n.txt ] || return 0
        grep -q "GATE PASS" $T/gate_$n.txt && [ ! -s $T/spider2_$n.txt ] && return 0
    done
    return 1
}
second_server() {  # the untuned model on 8766, once judge_v2_chain.sh is done with it
    v2_busy && return
    curl -sf localhost:8766/v1/models | grep -q "\"$BASE\"" && return
    if curl -sf localhost:8766/v1/models >/dev/null; then pkill -f -- "--port 8766"; sleep 20; fi
    pgrep -f -- "--port 8766" >/dev/null && return  # loading
    local g
    g=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | sort -t, -k2 -n | head -1 | cut -d, -f1)
    log "starting the untuned model on GPU $g, port 8766"
    CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=$g HF_HOME=$U/.cache/huggingface VLLM_MLA_DISABLE=1 \
        "$M/.vllm-venv/bin/python" -m vllm.entrypoints.openai.api_server \
        --model $BASE --port 8766 --host 0.0.0.0 --max-model-len 60000 \
        --gpu-memory-utilization 0.85 --dtype bfloat16 --enforce-eager --trust-remote-code \
        --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
        >> "$R/vllm2_${SLURM_JOB_ID:-x}.log" 2>&1 < /dev/null &
}
ports() {  # the ports serving the untuned model now
    local p out=""
    for p in 8765 8766; do curl -sf localhost:$p/v1/models | grep -q "\"$BASE\"" && out="$out $p"; done
    echo $out
}
( while sleep 300; do second_server; done ) &
second_server
for _ in $(seq 1 60); do  # a second server still loading: wait for it, as each stage fixes its ports
    pgrep -f -- "--model $BASE --port 8766" >/dev/null && ! curl -sf localhost:8766/v1/models >/dev/null || break
    sleep 15
done
log "start on $NODE; untuned servers: $(ports)"

# 1. questions
[ -e $R/questions.jsonl.before_cplx ] || { cp $DS/questions.jsonl $R/questions.jsonl.before_cplx; cp $DS/gold/eval.jsonl $R/eval.jsonl.before_cplx; }
have() { grep -c '"instance_id": "cplx_' $DS/questions.jsonl; }
attempts() { [ -s $DS/traps/attempts.jsonl ] && grep -c '"source": "complex"' $DS/traps/attempts.jsonl || echo 0; }
eps() { local p e=""; for p in "$@"; do e="$e,http://localhost:$p/v1"; done; echo ${e#,}; }
while [ "$(have)" -lt $TARGET ] && [ "$(attempts)" -lt $MAX_ATTEMPTS ]; do
    P=($(ports)); [ ${#P[@]} -gt 0 ] || { log "no untuned server; waiting"; sleep 120; continue; }
    E=$(eps ${P[*]})  # every role spreads its calls over all servers
    log "generating: $(have) admitted, $(attempts) attempts; servers ${P[*]}"
    $RUN scripts/generate_trap_items.py --style complex --thinking --max-tokens 24000 --writer-retries 2 --exclude-dbs language_corpus \
        --n-items $((TARGET - $(have))) --max-attempts 200 --workers $((64 * ${#P[@]})) \
        --writer-endpoint $E --writer-model $BASE --solver-endpoint $E --solver-model $BASE \
        --question-endpoint $E --question-model $BASE \
        --adjudicator-endpoint $E --adjudicator-model $BASE >> $R/generate.log 2>&1 \
        || log "generator exited $? (see generate.log); retrying"
done
log "questions: $(have) admitted in $(attempts) attempts"
[ "$(have)" -gt 0 ] || die "no complex question admitted"

# 2. agent runs on this batch's questions: those no other batch has (run_judge_agent.sh shards
# by line number, so a batch's id list never changes once its runs start)
IDS=~/judge-tmp/cplx_ids_$TAG.txt
if [ ! -s $IDS ]; then
    grep -o '"instance_id": "cplx_[^"]*"' $DS/questions.jsonl | cut -d'"' -f4 \
        | grep -vxFf <(cat /dev/null $(ls ~/judge-tmp/cplx_ids_*.txt 2>/dev/null)) > $IDS.tmp && mv $IDS.tmp $IDS
fi
n=$(wc -l < $IDS)
[ "$n" -gt 0 ] || die "no new questions for batch $TAG"
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
    PORTS="${P[*]}" bash ~/slurm/run_judge_agent.sh cplx_$TAG $IDS 4 12 >> $R/agent_$TAG.log 2>&1
    lanes_done || { log "agent lanes incomplete; rerunning (resume)"; sleep 60; }
done
log "agent runs done: $(for l in 1 2 3 4; do echo -n "$(($(wc -l < $A/lane$l.csv) - 1)) "; done)rows per lane"

# 3. untuned judge verdicts
V=$R/verdicts_cplx_$TAG.jsonl
if [ ! -e $V.done ]; then
    until P=($(ports)); [ ${#P[@]} -gt 0 ]; do sleep 120; done
    EP=$(for p in ${P[*]}; do echo -n "http://$NODE:$p/v1,"; done); EP=${EP%,}
    log "sampling judge verdicts on $EP"
    $RUN scripts/sample_judge_verdicts.py --runs $A/lane1.csv,$A/lane2.csv,$A/lane3.csv,$A/lane4.csv \
        --judge-endpoint "$EP" --judge-model $BASE --samples 4 --workers 96 \
        --output $V --resume >> $R/sample_$TAG.log 2>&1 \
        && touch $V.done || die "sampling failed; see $R/sample_$TAG.log"
fi
log "verdicts: $(wc -l < $V) questions"

# 4. summary
$RUN scripts/summarize_cplx_pilot.py --verdicts $V \
    --spider-features $U/analysis/gap_v2a.jsonl > $R/summary_$TAG.txt 2>&1 || die "summary failed"
log "summary: $(head -3 $R/summary_$TAG.txt | tr '\n' ' ')"

# 5. label check
L=$R/pair_labels_$TAG.jsonl
if [ ! -e $L.done ]; then
    until P=($(ports)); [ ${#P[@]} -gt 0 ]; do sleep 120; done
    EP=$(for p in ${P[*]}; do echo -n "http://$NODE:$p/v1,"; done); EP=${EP%,}
    log "checking pair labels on $EP"
    $RUN scripts/check_pair_labels.py --verdicts $V --endpoint "$EP" --model $BASE --thinking \
        --samples 5 --output $L --resume > $R/pair_labels_$TAG.log 2>&1 \
        && touch $L.done || die "label check failed; see $R/pair_labels_$TAG.log"
fi
log "labels: $(tail -6 $R/pair_labels_$TAG.log | tr '\n' ' ')"
log "done"

#!/bin/bash
# Judge retrain v3: v2a's recipe (DPO from the base, lr 5e-5, 2 epochs) on v2's data plus the
# Qwen-written complex questions (judge_cplx_chain.sh batches), whose SQL is Spider2-sized.
# Run inside the judge GPU session (port 8765 serves the untuned judge):
#   setsid nohup srun --jobid=<session> --overlap -n1 --cpus-per-task=8 \
#       bash ~/slurm/judge_v3_chain.sh >> ~/joblogs/judge_v3_chain.log 2>&1 < /dev/null &
# keep_v3_chain_alive.sh starts it once the last complex batch is done and relaunches it after a
# preemption; every stage is skipped when its output exists:
#   1. untuned judge, 8 more samples per complex pair (both ports): training rows for pairs the
#      4 stored samples left never- or always-right, and the complex gate's baseline
#   2. data: v2's sources plus the complex verdicts, v2's held-out databases, pairs that
#      check_pair_labels.py labelled other_reading dropped, complex rows repeated twice
#   3. training c, as a separate sbatch job
#   4. gates on port 8766: v2's BIRD pairs (comparable with v2a) and all complex pairs
#   5. if either gate passes: the Spider2 pool eval and compare_judges.py against base and v2a
set -u
U=/data/user_data/$USER; M=$U/nl2sql-databao; C=$U/judge-code; D=$U/judge-data
PY=$M/nl2sql-v2/.venv/bin/python
BASE=QuantTrio/Qwen3.6-35B-A3B-AWQ
V1=$D/results/judge_train/verdicts_train_v1.jsonl; RJ=$U/nl2sql-sel/results/rejudge
T2=$D/results/judge_train_v2; RC=$D/results/judge_cplx
CPLX_TAGS=${CPLX_TAGS:-"v1 v2"}
R=$D/results/judge_train_v3; mkdir -p $R
NAME=c; LR=5e-5; N=judge-tuned-v3$NAME; O=$R/model_$NAME
TRAIN_SBATCH=${TRAIN_SBATCH:-"--time=16:00:00 --exclude=babel-w9-28 --gres=gpu:4 --constraint=A6000|L40S|6000Ada|A100_80GB|A100_80G"}
log() { echo "[$(date -Is)] $*"; }
die() { log "STOPPED: $*"; exit 1; }  # the keeper does not relaunch after this
alive() {  # see judge_v2_chain.sh: gone only when sacct reports a final state twice
    local s
    s=$(sacct -j "$1" -X -n -o State%30 2>/dev/null | head -1 | tr -d ' ')
    case "$s" in
        ""|PENDING|RUNNING|REQUEUED|REQUEUE_*|CONFIGURING|COMPLETING|SUSPENDED|PREEMPTED|RESIZING) return 0 ;;
    esac
    return 1
}
gone() { ! alive "$1" && sleep 60 && ! alive "$1"; }

rsync -a ~/judge-code-staging/ $C/ && cd $C/nl2sql-v2 || die "no code"
CV=""; CL=""
for t in $CPLX_TAGS; do
    [ -e $RC/pair_labels_$t.jsonl.done ] || die "complex batch $t has no label check yet"
    CV="$CV,$RC/verdicts_cplx_$t.jsonl"; CL="$CL,$RC/pair_labels_$t.jsonl"
done
CV=${CV#,}; CL=${CL#,}
for _ in $(seq 1 90); do curl -sf localhost:8765/v1/models >/dev/null && break; sleep 20; done  # a new session loading
curl -sf localhost:8765/v1/models >/dev/null || die "the session's server on 8765 is not up"

serve() {  # serve() <model> <name>: that model on port 8766, on the GPU 8765 is not using
    if curl -sf localhost:8766/v1/models | grep -q "\"$2\""; then return 0; fi
    pkill -f -- "--port 8766"; sleep 20
    local g
    g=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | sort -t, -k2 -n | head -1 | cut -d, -f1)
    log "serving $2 on GPU $g"
    HF_HOME=$U/.cache/huggingface VLLM_MLA_DISABLE=1 CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=$g \
        "$M/.vllm-venv/bin/python" -m vllm.entrypoints.openai.api_server --model "$1" --served-model-name "$2" \
        --port 8766 --host 0.0.0.0 --max-model-len 32768 --gpu-memory-utilization 0.85 --dtype bfloat16 \
        --enforce-eager --trust-remote-code --reasoning-parser qwen3 >> $R/vllm_${2##*/}.log 2>&1 < /dev/null &
    for _ in $(seq 1 90); do
        curl -sf localhost:8766/v1/models | grep -q "\"$2\"" && { log "$2 up"; return 0; }
        sleep 10
    done
    tail -20 $R/vllm_${2##*/}.log; log "$2 did not come up"; return 1
}
rejudge() {  # rejudge <out> <endpoints> <model> <samples>: every complex pair; a second pass redoes errors
    local i
    for i in 1 2; do
        $PY scripts/rejudge_pairs.py --verdicts $CV --select never,mixed,always --judge-endpoint "$2" \
            --judge-model "$3" --samples "$4" --workers 128 --output "$1" --resume >> "${1%.jsonl}.log" 2>&1
    done
    $PY - "$1" <<'PY'
import json, sys
rs = [json.loads(l) for l in open(sys.argv[1])]
ok = {(r["id"], r["sample"]) for r in rs if not r["error"]}
ids = {r["id"] for r in rs}
print(f"{len(ok)} ok samples over {len(ids)} pairs")
sys.exit(0 if len(ok) >= 0.97 * len({(r['id'], r['sample']) for r in rs}) else 1)
PY
}

# 1. untuned resample of the complex pairs
CU=$R/cplx_untuned.jsonl
if [ ! -e $CU.done ]; then
    serve $BASE $BASE || die "untuned server on 8766"
    log "untuned resample of complex pairs"
    rejudge $CU http://localhost:8765/v1,http://localhost:8766/v1 $BASE 8 && touch $CU.done || die "untuned resample incomplete"
fi
log "untuned complex samples: $(wc -l < $CU)"

# 2. data
if [ ! -s $R/data/stats.json ]; then
    log "building data"
    $PY scripts/make_judge_sft_dpo.py --verdicts $V1,$CV --out-dir $R/data --dpo-per-pair 4 \
        --extra-samples $RJ/train_untuned.jsonl,$RJ/train_tuned.jsonl,$CU --holdout-file $T2/data/holdout.json \
        --drop-pairs $CL --source-weight complex=2 > $R/data_build.log 2>&1 || { tail $R/data_build.log; die "data build failed"; }
fi
log "data: $(tr -d '\n ' < $R/data/stats.json)"

# 3. training
if [ ! -s $O/judge_awq/merged_adapter.json ]; then
    [ -e $O.failed ] && die "training $NAME failed earlier"
    J=$(cat $O.jobid 2>/dev/null)
    if [ -z "$J" ]; then
        J=$(sbatch --parsable $TRAIN_SBATCH \
            --export=ALL,STAGES="dpo merge",DPO_ARGS="--lr $LR --epochs 2",DATA=$R/data,OUT=$O ~/slurm/train_judge.slurm)
        echo "$J" > $O.jobid; log "submitted training $NAME (lr $LR) as $J"
    fi
    while [ ! -s $O/judge_awq/merged_adapter.json ]; do
        if gone "$J"; then
            [ -s $O/judge_awq/merged_adapter.json ] && break
            touch $O.failed; die "training $NAME ($J) ended without a merge"
        fi
        sleep 300
    done
fi
log "training $NAME merged"

# 4. gates
if [ ! -s $R/gate_bird.txt ]; then
    serve $O/judge_awq $N || die "server for $N"
    log "BIRD gate"
    $PY scripts/rejudge_pairs.py --verdicts $V1 --select never,mixed,always:100 \
        --judge-endpoint http://localhost:8766/v1 --judge-model $N --samples 4 --workers 128 \
        --output $R/gate_bird.jsonl --resume > $R/gate_bird.log 2>&1
    n=$(wc -l < $R/gate_bird.jsonl)
    [ "$n" -ge 2300 ] || die "BIRD gate incomplete ($n samples)"
    $PY scripts/judge_gate.py --baseline $RJ/train_untuned.jsonl --tuned $R/gate_bird.jsonl \
        --data $R/data --verdicts $V1 > $R/gate_bird.txt.tmp 2>&1 && mv $R/gate_bird.txt.tmp $R/gate_bird.txt
    log "BIRD gate: $(tail -1 $R/gate_bird.txt)"
fi
if [ ! -s $R/gate_cplx.txt ]; then
    serve $O/judge_awq $N || die "server for $N"
    log "complex gate"
    rejudge $R/gate_cplx.jsonl http://localhost:8766/v1 $N 4 || die "complex gate incomplete"
    $PY scripts/judge_gate.py --baseline $CU --tuned $R/gate_cplx.jsonl \
        --data $R/data --verdicts $CV > $R/gate_cplx.txt.tmp 2>&1 && mv $R/gate_cplx.txt.tmp $R/gate_cplx.txt
    log "complex gate: $(tail -1 $R/gate_cplx.txt)"
fi
grep -q "GATE PASS" $R/gate_bird.txt $R/gate_cplx.txt || die "both gates failed; no Spider2 eval"

# 5. Spider2
if [ ! -s $R/spider2_$NAME.txt ]; then
    serve $O/judge_awq $N || die "server for $N"
    log "Spider2 eval"
    TUNED=$O/judge_awq NAME=$N bash ~/slurm/eval_judge_pools.sh >> $R/spider2_eval_$NAME.log 2>&1
    tail -1 $R/spider2_eval_$NAME.log | grep -q "\] done$" || die "Spider2 eval did not finish"
    $PY scripts/compare_judges.py --pools-dir $U/nl2sql-sel/results/pools \
        --judge base=think35/qwen36-35b-think --judge base_rerun=think35_rerun/qwen36-35b-think-rerun \
        --judge v2a=judge-tuned-v2a/judge-tuned-v2a --judge v3$NAME=$N/$N --show > $R/spider2_$NAME.txt.tmp 2>&1 \
        && mv $R/spider2_$NAME.txt.tmp $R/spider2_$NAME.txt
    log "Spider2: $(grep -E '^v[23]' $R/spider2_$NAME.txt | head -3 | tr '\n' ' ')"
fi
log "done"

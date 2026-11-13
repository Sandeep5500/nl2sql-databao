#!/bin/bash
# Judge retrain v2, run inside the judge GPU session (port 8765 serves the untuned judge):
#   setsid nohup srun --jobid=<session> --overlap -n1 --cpus-per-task=8 \
#       bash ~/slurm/judge_v2_chain.sh >> ~/joblogs/judge_v2_chain.log 2>&1 < /dev/null &
# Every stage is skipped when its output exists, so after a preemption or a cancelled step
# it is just relaunched (keep_v2_chain_alive.sh does that):
#   1. DPO data: v1 verdicts plus the later samples (rejudge_pairs.py), 20% of databases held out
#   2. training smoke test (DPO from the base, then the merge) must have merged
#   3. full DPO trainings, one per learning rate in VARIANTS, as separate sbatch jobs
#   4. each trained judge served on 8766 and checked on its training pairs (judge_gate.py)
#   5. each judge that passes: the Spider2 pool eval (eval_judge_pools.sh) and compare_judges.py
set -u
U=/data/user_data/$USER; M=$U/nl2sql-databao; C=$U/judge-code; D=$U/judge-data
PY=$M/nl2sql-v2/.venv/bin/python
V1=$D/results/judge_train/verdicts_train_v1.jsonl; RJ=$U/nl2sql-sel/results/rejudge
R=$D/results/judge_train_v2; mkdir -p $R
VARIANTS=${VARIANTS:-"a:5e-5 b:1.5e-4"}
# trainings: four GPUs of 48GB or more (the bf16 base is ~70GB; 80GB A100s are rarely free);
# babel-w9-28 has no /home or /data mounted and kills jobs at start
TRAIN_SBATCH=${TRAIN_SBATCH:-"--time=16:00:00 --exclude=babel-w9-28 --gres=gpu:4 --constraint=A6000|L40S|6000Ada|A100_80GB|A100_80G"}
log() { echo "[$(date -Is)] $*"; }
die() { log "STOPPED: $*"; exit 1; }  # the keeper does not relaunch after this
# a job counts as gone only when sacct reports a final state, twice a minute apart: during
# Babel's Nov 2 maintenance squeue answered nothing and a running training was marked failed
alive() {
    local s
    s=$(sacct -j "$1" -X -n -o State%30 2>/dev/null | head -1 | tr -d ' ')
    case "$s" in
        ""|PENDING|RUNNING|REQUEUED|REQUEUE_*|CONFIGURING|COMPLETING|SUSPENDED|PREEMPTED|RESIZING) return 0 ;;
    esac
    return 1
}
gone() { ! alive "$1" && sleep 60 && ! alive "$1"; }

rsync -a ~/judge-code-staging/ $C/ && cd $C/nl2sql-v2 || die "no code"

# 1. data
if [ ! -s $R/data/stats.json ]; then
    log "building data"
    $PY scripts/make_judge_sft_dpo.py --verdicts $V1 --out-dir $R/data --dpo-per-pair 4 \
        --extra-samples $RJ/train_untuned.jsonl,$RJ/train_tuned.jsonl --holdout-frac 0.2 \
        > $R/data_build.log 2>&1 || { tail $R/data_build.log; die "data build failed"; }
fi
log "data: $(grep -E '"dpo_examples"' $R/data/stats.json)"

# 2. smoke test (submitted by hand or here); wait for its merge
SM=$R/smoke_train/judge_awq/merged_adapter.json
if [ ! -s $SM ]; then
    J=$(cat $R/smoke.jobid 2>/dev/null)
    if [ -z "$J" ] || ! alive "$J"; then
        J=$(sbatch --parsable --constraint="A100_80GB|A100_80G" \
            --export=ALL,SMOKE=1,STAGES="dpo merge",DATA=$R/data,OUT=$R/smoke_train ~/slurm/train_judge.slurm)
        echo "$J" > $R/smoke.jobid; log "submitted smoke test $J"
    fi
    while [ ! -s $SM ]; do
        gone "$J" && { [ -s $SM ] || die "smoke test $J ended without a merge"; }
        sleep 60
    done
fi
log "smoke test merged"

# 3. full trainings
for v in $VARIANTS; do
    name=${v%%:*}; lr=${v#*:}; O=$R/model_$name
    [ -s $O/judge_awq/merged_adapter.json ] && continue
    [ -e $R/model_$name.failed ] && continue
    J=$(cat $R/model_$name.jobid 2>/dev/null)
    if [ -z "$J" ] || gone "$J"; then
        if [ -n "$J" ]; then log "training $name ($J) ended without a merge: failed"; touch $R/model_$name.failed; continue; fi
        J=$(sbatch --parsable $TRAIN_SBATCH \
            --export=ALL,STAGES="dpo merge",DPO_ARGS="--lr $lr --epochs 2",DATA=$R/data,OUT=$O ~/slurm/train_judge.slurm)
        echo "$J" > $R/model_$name.jobid; log "submitted training $name (lr $lr) as $J"
    fi
done

serve() {  # serve() <model dir> <name>: that judge on port 8766, on the GPU 8765 is not using
    if curl -sf localhost:8766/v1/models | grep -q "\"$2\""; then return 0; fi
    pkill -f -- "--port 8766"; sleep 20
    local g
    g=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | sort -t, -k2 -n | head -1 | cut -d, -f1)
    log "serving $2 on GPU $g"
    HF_HOME=$U/.cache/huggingface VLLM_MLA_DISABLE=1 CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=$g \
        "$M/.vllm-venv/bin/python" -m vllm.entrypoints.openai.api_server --model "$1" --served-model-name "$2" \
        --port 8766 --host 0.0.0.0 --max-model-len 32768 --gpu-memory-utilization 0.85 --dtype bfloat16 \
        --enforce-eager --trust-remote-code --reasoning-parser qwen3 >> $R/vllm_$2.log 2>&1 < /dev/null &
    for _ in $(seq 1 90); do
        curl -sf localhost:8766/v1/models | grep -q "\"$2\"" && { log "$2 up"; return 0; }
        sleep 10
    done
    tail -20 $R/vllm_$2.log; log "$2 did not come up"; return 1
}

# 4-5. as each training finishes: gate, then Spider2 for the ones that pass
pending=1
while [ $pending = 1 ]; do
    pending=0
    for v in $VARIANTS; do
        name=${v%%:*}; O=$R/model_$name; N=judge-tuned-v2$name
        [ -e $R/model_$name.failed ] && continue
        if [ ! -s $O/judge_awq/merged_adapter.json ]; then
            J=$(cat $R/model_$name.jobid 2>/dev/null)
            if [ -n "$J" ] && gone "$J"; then
                [ -s $O/judge_awq/merged_adapter.json ] || { log "training $name ($J) ended without a merge: failed"; touch $R/model_$name.failed; continue; }
            else
                pending=1; continue
            fi
        fi
        if [ ! -s $R/gate_$name.txt ]; then
            serve $O/judge_awq $N || die "server for $N"
            log "gate $name"
            $PY scripts/rejudge_pairs.py --verdicts $V1 --select never,mixed,always:100 \
                --judge-endpoint http://localhost:8766/v1 --judge-model $N --samples 4 --workers 128 \
                --output $R/gate_$name.jsonl --resume > $R/gate_$name.log 2>&1
            n=$(wc -l < $R/gate_$name.jsonl)
            [ "$n" -ge 2300 ] || die "gate $name incomplete ($n samples)"
            $PY scripts/judge_gate.py --baseline $RJ/train_untuned.jsonl --tuned $R/gate_$name.jsonl \
                --data $R/data --verdicts $V1 > $R/gate_$name.txt.tmp 2>&1 && mv $R/gate_$name.txt.tmp $R/gate_$name.txt
            log "gate $name: $(tail -1 $R/gate_$name.txt)"
        fi
        if grep -q "GATE PASS" $R/gate_$name.txt && [ ! -s $R/spider2_$name.txt ]; then
            serve $O/judge_awq $N || die "server for $N"
            log "Spider2 eval $name"
            TUNED=$O/judge_awq NAME=$N bash ~/slurm/eval_judge_pools.sh >> $R/spider2_eval_$name.log 2>&1
            tail -1 $R/spider2_eval_$name.log | grep -q "\] done$" || die "Spider2 eval $name did not finish"
            $PY scripts/compare_judges.py --pools-dir $U/nl2sql-sel/results/pools \
                --judge base=think35/qwen36-35b-think --judge base_rerun=think35_rerun/qwen36-35b-think-rerun \
                --judge v1=judge-tuned-v1/judge-tuned-v1 --judge v2$name=$N/$N --show > $R/spider2_$name.txt.tmp 2>&1 \
                && mv $R/spider2_$name.txt.tmp $R/spider2_$name.txt
            log "Spider2 $name: $(grep -E '^v2' $R/spider2_$name.txt | head -2 | tr '\n' ' ')"
        fi
    done
    [ $pending = 1 ] && sleep 300
done
log "done"

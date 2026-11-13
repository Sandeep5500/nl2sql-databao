#!/bin/bash
# Login-node keeper for the verdict-only judge (judge_train_v4): submits the training job
# (train_judge.slurm, STAGES="choice merge"), then judge_choice_eval.slurm once training has
# merged; resubmits either job (both resume) when it ends without finishing, up to 3 times
# each. Progress goes to ~/joblogs/keep_choice_chain.log; the eval job writes
# ~/joblogs/judge_choice_summary.txt at the end.
#   setsid nohup bash ~/slurm/keep_choice_chain.sh >> ~/joblogs/keep_choice_chain.log 2>&1 < /dev/null &
# Variant: V=_e1 CHOICE_ARGS="--epochs 1" (model$V, jobids/summary tagged $V; log to keep_choice_chain$V.log);
# DATA=<dir> trains on another build (default $D/data), e.g. V=_v5c DATA=$D/data_v5c
D=/data/user_data/$USER/judge-data/results/judge_train_v4
TRAIN_SBATCH=(--time=16:00:00 --exclude=babel-w9-28 --gres=gpu:4 "--constraint=A6000|L40S|6000Ada|A100_80GB|A100_80G")
V=${V:-}; CHOICE_ARGS=${CHOICE_ARGS:-}; DATA=${DATA:-$D/data}
TJ=~/joblogs/choice_train$V.jobids; EJ=~/joblogs/choice_eval$V.jobids
log() { echo "[$(date -Is)] $*"; }
alive() {
    case "$(sacct -j "$1" -X -n -o State%30 2>/dev/null | head -1 | tr -d ' ')" in
        ""|PENDING|RUNNING|REQUEUED|REQUEUE_*|CONFIGURING|COMPLETING|SUSPENDED|PREEMPTED|RESIZING) return 0 ;;
    esac
    return 1
}
gone() { ! alive "$1" && sleep 60 && ! alive "$1"; }
last() { tail -1 "$1" 2>/dev/null; }
tries() { wc -l < "$1" 2>/dev/null || echo 0; }

stage=train
while true; do
    if [ $stage = train ]; then
        J=$(last $TJ)
        if [ -z "$J" ]; then
            J=$(sbatch --parsable "${TRAIN_SBATCH[@]}" --job-name=judge_choice$V \
                --export=ALL,STAGES="choice merge",DATA=$DATA,OUT=$D/model$V,CHOICE_ARGS="$CHOICE_ARGS" ~/slurm/train_judge.slurm)
            echo "$J" >> $TJ; log "submitted training $J"
        elif gone "$J"; then
            if grep -q "^done " ~/joblogs/judge_train_$J.out; then
                log "training $J finished: $(grep -m1 'peak GiB' ~/joblogs/judge_train_$J.out)"
                stage=eval; continue
            fi
            if [ "$(tries $TJ)" -ge 3 ]; then log "STOPPED: training failed 3 times; see ~/joblogs/judge_train_$J.out"; exit 1; fi
            log "training $J ended unfinished ($(sacct -j $J -X -n -o State | head -1 | tr -d ' ')); resubmitting"
            J=$(sbatch --parsable "${TRAIN_SBATCH[@]}" --job-name=judge_choice$V \
                --export=ALL,STAGES="choice merge",DATA=$DATA,OUT=$D/model$V,CHOICE_ARGS="$CHOICE_ARGS" ~/slurm/train_judge.slurm)
            echo "$J" >> $TJ; log "submitted training $J"
        fi
    else
        J=$(last $EJ)
        if [ -z "$J" ]; then
            J=$(sbatch --parsable --export=ALL,V=$V,DATA=$DATA ~/slurm/judge_choice_eval.slurm); echo "$J" >> $EJ; log "submitted eval $J"
        elif gone "$J"; then
            if grep -q "\] done$" ~/joblogs/judge_choice_eval_$J.out; then
                log "eval $J finished; summary in ~/joblogs/judge_choice_summary$V.txt"; log "ALL DONE"; exit 0
            fi
            if [ "$(tries $EJ)" -ge 3 ]; then log "STOPPED: eval failed 3 times; see ~/joblogs/judge_choice_eval_$J.out"; exit 1; fi
            log "eval $J ended unfinished ($(sacct -j $J -X -n -o State | head -1 | tr -d ' ')): $(tail -2 ~/joblogs/judge_choice_eval_$J.out | tr '\n' ' ')"
            J=$(sbatch --parsable --export=ALL,V=$V,DATA=$DATA ~/slurm/judge_choice_eval.slurm); echo "$J" >> $EJ; log "resubmitted eval $J"
        fi
    fi
    sleep 300
done

#!/bin/bash
# Evaluation of the verdict-only judge (train_judge_lora.py choice stage, judge_train_v4), with
# thinking off, against the untuned judge with thinking off (the same format, so the difference is
# the training) on the same items as v3's evaluation:
#   1. pair gates: v3's BIRD gate pairs and all complex pairs (rejudge_pairs.py --no-thinking),
#      reported by judge_gate.py against the untuned judge without and with thinking
#   2. Spider2 round-robin pools (judge_pools.py, 4 run sets, 12 shards each)
#   3. Rohini's BigQuery pools (bq_judge_pools.py, 107 questions, agent schema)
# Serves the untuned AWQ build on the first GPU and the merged judge on the second (own ports,
# so it can share a node with the judge session). Every step resumes; a requeue picks up.
#   sbatch ~/slurm/judge_choice_eval.slurm
#   sbatch --export=ALL,V=_e1 ~/slurm/judge_choice_eval.slurm   (variant: judge from model$V, outputs tagged $V;
#       the untuned baselines are shared and resume as done)
#   DATA=<dir>: the training data of that judge (default $R/data), for the gates' trained/held-out split
#   e.g. v6: V=_v6 DATA=$R/data_v6 (v5c + the Nov 9 Claude batches h1/h2 + BEAVER p1)
#SBATCH --job-name=judge_choice_eval
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:2
#SBATCH --constraint=A6000|6000Ada|L40S|A100_80GB
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=12:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/judge_choice_eval_%j.out
set -u
U=/data/user_data/$USER; M=$U/nl2sql-databao; C=$U/judge-code; D=$U/judge-data; W=$U/nl2sql-sel
PY=$M/nl2sql-v2/.venv/bin/python
BASE=QuantTrio/Qwen3.6-35B-A3B-AWQ
V=${V:-}
R=$D/results/judge_train_v4; TUNED=$R/model$V/judge_awq; N=judge-choice-v4$V
V1=$D/results/judge_train/verdicts_train_v1.jsonl; RJ=$U/nl2sql-sel/results/rejudge
RC=$D/results/judge_cplx; CV=$RC/verdicts_cplx_v1.jsonl,$RC/verdicts_cplx_v2.jsonl
R3=$D/results/judge_train_v3
CC=$D/results/judge_claude/verdicts_claude_v3.jsonl   # the Nov 7 Claude-written batch
CN=$D/results/judge_claude/verdicts_claude_h1.jsonl,$D/results/judge_claude/verdicts_claude_h2.jsonl  # the Nov 9 harder batches
CB=$D/results/judge_beaver/verdicts_beaver_p1.jsonl   # BEAVER pilot (neutron = held-out database)
DATA=${DATA:-$R/data}
POOLS=$W/results/pools; SEL=$W/results/sel; BQ=$U/bq_passk
PB=8775; PT=8776   # untuned, tuned
export HF_HOME=$U/.cache/huggingface VLLM_MLA_DISABLE=1
log() { echo "[$(date -Is)] $*"; }
log "node=$(hostname) job=$SLURM_JOB_ID restarts=${SLURM_RESTART_COUNT:-0}"
[ -s $TUNED/merged_adapter.json ] || { log "no merged judge at $TUNED"; exit 1; }
rsync -a ~/judge-code-staging/ $C/ || exit 1
mkdir -p $R/logs
GPUS=(${CUDA_VISIBLE_DEVICES//,/ })
module load cuda-12.1 2>/dev/null || true
serve() {  # serve <gpu> <port> <model> <name>
    CUDA_VISIBLE_DEVICES=$1 "$M/.vllm-venv/bin/python" -m vllm.entrypoints.openai.api_server \
        --model "$3" --served-model-name "$4" --port "$2" --host 0.0.0.0 --max-model-len 32768 \
        --gpu-memory-utilization 0.90 --dtype bfloat16 --enforce-eager --trust-remote-code \
        --reasoning-parser qwen3 >> $R/logs/vllm_${4##*/}_$SLURM_JOB_ID.log 2>&1 < /dev/null &
}
serve ${GPUS[0]} $PB $BASE $BASE; P1=$!
serve ${GPUS[1]} $PT $TUNED $N; P2=$!
trap 'kill $P1 $P2 2>/dev/null' EXIT
for _ in $(seq 1 180); do
    curl -sf localhost:$PB/v1/models >/dev/null && curl -sf localhost:$PT/v1/models >/dev/null && break
    kill -0 $P1 2>/dev/null && kill -0 $P2 2>/dev/null || { log "a server died"; tail -20 $R/logs/vllm_*_$SLURM_JOB_ID.log; exit 1; }
    sleep 10
done
curl -sf localhost:$PB/v1/models >/dev/null && curl -sf localhost:$PT/v1/models >/dev/null || { log "servers not up"; exit 1; }
log "both servers up"

# 1. pair gates
cd $C/nl2sql-v2
gate() {  # gate <out> <verdicts> <select> <port> <model>: two passes, the second redoes errors
    local i
    for i in 1 2; do
        $PY scripts/rejudge_pairs.py --no-thinking --verdicts "$2" --select "$3" \
            --judge-endpoint "http://localhost:$4/v1" --judge-model "$5" --samples 1 --max-tokens 2048 \
            --workers 48 --output "$1" --resume >> "${1%.jsonl}.log" 2>&1
    done
}
GP=()  # wait on these only: a bare wait also waits on the servers
gate $R/gate_bird_untuned_nothink.jsonl $V1 never,mixed,always:100 $PB $BASE & GP+=($!)
gate $R/gate_bird_choice$V.jsonl $V1 never,mixed,always:100 $PT $N & GP+=($!)
gate $R/gate_cplx_untuned_nothink.jsonl $CV never,mixed,always $PB $BASE & GP+=($!)
gate $R/gate_cplx_choice$V.jsonl $CV never,mixed,always $PT $N & GP+=($!)
gate $R/gate_claude_untuned_nothink.jsonl $CC never,mixed,always $PB $BASE & GP+=($!)
gate $R/gate_claude_choice$V.jsonl $CC never,mixed,always $PT $N & GP+=($!)
gate $R/gate_claude2_untuned_nothink.jsonl $CN never,mixed,always $PB $BASE & GP+=($!)
gate $R/gate_claude2_choice$V.jsonl $CN never,mixed,always $PT $N & GP+=($!)
gate $R/gate_beaver_untuned_nothink.jsonl $CB never,mixed,always $PB $BASE & GP+=($!)
gate $R/gate_beaver_choice$V.jsonl $CB never,mixed,always $PT $N & GP+=($!)
wait "${GP[@]}"
G="--data $DATA --trained-file choice.jsonl"
$PY scripts/judge_gate.py --baseline $R/gate_bird_untuned_nothink.jsonl --tuned $R/gate_bird_choice$V.jsonl $G --verdicts $V1 > $R/gate_bird$V.txt 2>&1
$PY scripts/judge_gate.py --baseline $RJ/train_untuned.jsonl --tuned $R/gate_bird_choice$V.jsonl $G --verdicts $V1 > $R/gate_bird_vs_thinking$V.txt 2>&1
$PY scripts/judge_gate.py --baseline $R/gate_cplx_untuned_nothink.jsonl --tuned $R/gate_cplx_choice$V.jsonl $G --verdicts $CV > $R/gate_cplx$V.txt 2>&1
$PY scripts/judge_gate.py --baseline $R3/cplx_untuned.jsonl --tuned $R/gate_cplx_choice$V.jsonl $G --verdicts $CV > $R/gate_cplx_vs_thinking$V.txt 2>&1
$PY scripts/judge_gate.py --baseline $R/gate_claude_untuned_nothink.jsonl --tuned $R/gate_claude_choice$V.jsonl $G --verdicts $CC > $R/gate_claude$V.txt 2>&1
$PY scripts/judge_gate.py --baseline $R/gate_claude2_untuned_nothink.jsonl --tuned $R/gate_claude2_choice$V.jsonl $G --verdicts $CN > $R/gate_claude2$V.txt 2>&1
$PY scripts/judge_gate.py --baseline $R/gate_beaver_untuned_nothink.jsonl --tuned $R/gate_beaver_choice$V.jsonl $G --verdicts $CB > $R/gate_beaver$V.txt 2>&1
log "gates: $(tail -1 $R/gate_bird$V.txt) | $(tail -1 $R/gate_cplx$V.txt)"

# 2. Spider2 pools and 3. BigQuery pools, both judges, concurrently
PIDS=()
cd $W/nl2sql-v2
spider2() {  # spider2 <port> <model> <dir> <prefix>
    mkdir -p "$POOLS/$3"
    for pool in q36rg q36s q36 v2; do for k in $(seq 0 11); do
        $PY scripts/judge_pools.py \
            --runs "$SEL/${pool}_pass4_k1.csv,$SEL/${pool}_pass4_k2.csv,$SEL/${pool}_pass4_k3.csv,$SEL/${pool}_pass4_k4.csv" \
            --judge pairwise --judge-endpoint "http://localhost:$1/v1" --judge-model "$2" --max-tokens 2048 \
            --pair-workers 4 --shard "$k/12" --resume \
            --output "$POOLS/$3/$4_${pool}_n12_s$k.jsonl" > "$R/logs/$4_${pool}_s$k.log" 2>&1 &
        PIDS+=($!)
    done; done
}
spider2 $PT $N $N $N
spider2 $PB $BASE nothink35 qwen36-35b-nothink
cd $C/nl2sql-v2
for k in 0 1 2 3; do
    $PY scripts/bq_judge_pools.py --base $BQ/bigquery_passk_nov2026 --questions $BQ/bq_questions.jsonl \
        --judge pairwise --judge-endpoint http://localhost:$PT/v1 --judge-model $N --max-tokens 2048 \
        --pair-workers 4 --shard $k/4 --resume --output $BQ/pools/choice4${V}_bq_n4_s$k.jsonl > $R/logs/bq_choice${V}_s$k.log 2>&1 &
    PIDS+=($!)
    $PY scripts/bq_judge_pools.py --base $BQ/bigquery_passk_nov2026 --questions $BQ/bq_questions.jsonl \
        --judge pairwise --judge-endpoint http://localhost:$PB/v1 --judge-model $BASE --max-tokens 2048 \
        --pair-workers 4 --shard $k/4 --resume --output $BQ/pools/nothink35_bq_n4_s$k.jsonl > $R/logs/bq_nothink_s$k.log 2>&1 &
    PIDS+=($!)
done
log "started ${#PIDS[@]} pool shards"
fail=0
for p in "${PIDS[@]}"; do wait "$p" || fail=$((fail+1)); done
log "pool shards finished, $fail failed"
n1=$(cat $POOLS/$N/${N}_*_n12_s*.jsonl | wc -l); n2=$(cat $POOLS/nothink35/qwen36-35b-nothink_*_n12_s*.jsonl | wc -l)
n3=$(cat $BQ/pools/choice4${V}_bq_n4_s*.jsonl | wc -l); n4=$(cat $BQ/pools/nothink35_bq_n4_s*.jsonl | wc -l)
log "pool questions: spider2 tuned $n1, untuned $n2 (of 540); bigquery tuned $n3, untuned $n4 (of 107)"
[ $fail = 0 ] && [ $n1 -ge 540 ] && [ $n2 -ge 540 ] && [ $n3 -ge 107 ] && [ $n4 -ge 107 ] || { log "pools incomplete"; exit 1; }

# 4. summary, also copied to the home directory (readable from the login node)
{
    echo "== pair gates, verdict-only judge vs untuned judge (both thinking off)"; cat $R/gate_bird$V.txt; echo; cat $R/gate_cplx$V.txt
    echo; echo "== pair gates, verdict-only judge (thinking off) vs untuned judge with thinking"; cat $R/gate_bird_vs_thinking$V.txt; echo; cat $R/gate_cplx_vs_thinking$V.txt
    echo; echo "== pair gate on the Nov 7 Claude-written batch, verdict-only judge vs untuned judge (both thinking off)"; cat $R/gate_claude$V.txt
    echo; echo "== pair gate on the Nov 9 harder Claude batches (h1, h2), same comparison"; cat $R/gate_claude2$V.txt
    echo; echo "== pair gate on the BEAVER pilot (p1), same comparison"; cat $R/gate_beaver$V.txt
    echo; echo "== Spider2 round-robin, reference = untuned judge thinking off"
    $PY $C/nl2sql-v2/scripts/compare_judges.py --pools-dir $POOLS --judge nothink=nothink35/qwen36-35b-nothink \
        --judge choice=$N/$N --judge think=think35/qwen36-35b-think --show
    echo; echo "== Spider2 round-robin, reference = untuned judge with thinking (production)"
    $PY $C/nl2sql-v2/scripts/compare_judges.py --pools-dir $POOLS --judge think=think35/qwen36-35b-think \
        --judge choice=$N/$N --judge think_rerun=think35_rerun/qwen36-35b-think-rerun --judge v3c=judge-tuned-v3c/judge-tuned-v3c --show
    echo; echo "== BigQuery (107 questions the greedy run got wrong), reference = untuned judge thinking off"
    $PY $BQ/bq_compare.py nothink=nothink35_bq_n4 choice=choice4${V}_bq_n4 think=think35_bq_n16 jev=jev27b_bq_n4
} > $R/summary$V.txt 2>&1
cp $R/summary$V.txt ~/joblogs/judge_choice_summary$V.txt
log "done"

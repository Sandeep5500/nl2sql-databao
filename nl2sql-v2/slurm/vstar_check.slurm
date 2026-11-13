#!/bin/bash
# Step 2 of documents/head_probe_prereg.md: log-likelihood of the held-out practice judges' stored
# reasoning under the base judge and the DPO-trained judges v2a and v3c (scripts/vstar_scores.py),
# so their implicit reward (log pi_dpo - log pi_base) can be scored as a trace verifier on CPU.
# Also a smoke test of the production judge path: select_answer.py --mode pairwise --thinking with
# the adopted --judge-prompt diff_cmp, on 3 Spider2 questions (run files built from stored pools).
# GPU 0 serves the base AWQ judge, GPU 1 serves v2a and then v3c; the scorers append and skip done
# traces, so a requeued job resumes.
#
#   sbatch ~/slurm/vstar_check.slurm
#
#SBATCH --job-name=judge_vstar
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:2
#SBATCH --constraint=A6000|6000Ada|L40S|A100_80GB
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=12:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/judge_vstar_%j.out
set -uo pipefail
U=/data/user_data/$USER
M=$U/nl2sql-databao
R=$U/judge-data/results
OUT=$R/head_probe/vstar
VPY=$M/.vllm-venv/bin/python
TPY=$U/judge-code/.venv-train-fla/bin/python
BPY=$M/nl2sql-v2/.venv/bin/python
export HF_HOME=$U/.cache/huggingface
mkdir -p "$OUT"
echo "node=$(hostname) job=$SLURM_JOB_ID restarts=${SLURM_RESTART_COUNT:-0} start=$(date -Is)"
GPUS=(${CUDA_VISIBLE_DEVICES//,/ })
VERDICTS=("$R/judge_train/verdicts_train_v1.jsonl" "$R/judge_cplx/verdicts_cplx_v1.jsonl"
          "$R/judge_cplx/verdicts_cplx_v2.jsonl" "$R/judge_claude/verdicts_claude_v3.jsonl"
          "$R/judge_claude/verdicts_claude_h1.jsonl" "$R/judge_claude/verdicts_claude_h2.jsonl"
          "$R/judge_beaver/verdicts_beaver_p1.jsonl")
HOLD=$R/judge_train_v4/data_v6/holdout.json
FLAGS=(--host 127.0.0.1 --max-model-len 32768 --gpu-memory-utilization 0.92 --dtype bfloat16
       --enforce-eager --trust-remote-code --max-num-seqs 4)
up() { for _ in $(seq 1 240); do curl -sf "localhost:$1/v1/models" >/dev/null && return 0; sleep 10; done; return 1; }
score() { "$TPY" ~/judge-tmp/vstar_scores.py --endpoint "http://127.0.0.1:$1/v1" --model "$2" \
            --verdicts "${VERDICTS[@]}" --holdout "$HOLD" --out "$OUT/scores_$2.jsonl"; }

CUDA_VISIBLE_DEVICES=${GPUS[0]} "$VPY" -m vllm.entrypoints.openai.api_server --model QuantTrio/Qwen3.6-35B-A3B-AWQ \
    --served-model-name qwen36-base --port 8765 "${FLAGS[@]}" > "$OUT/vllm_base_$SLURM_JOB_ID.log" 2>&1 &
P0=$!
CUDA_VISIBLE_DEVICES=${GPUS[1]} "$VPY" -m vllm.entrypoints.openai.api_server --model "$R/judge_train_v2/model_a/judge_awq" \
    --served-model-name judge-v2a --port 8766 "${FLAGS[@]}" > "$OUT/vllm_v2a_$SLURM_JOB_ID.log" 2>&1 &
P1=$!
trap 'kill $P0 $P1 ${P2:-} 2>/dev/null' EXIT
up 8765 && up 8766 || { echo "servers not up"; tail -20 "$OUT"/vllm_*_"$SLURM_JOB_ID".log; exit 1; }
echo "servers up $(date -Is)"

# production smoke test: select_answer.py from a temporary copy of the judge code (shared code untouched)
T=$OUT/prodtest
rm -rf "$T/nl2sql-v2" && mkdir -p "$T/nl2sql-v2"
cp -r "$U/judge-code/nl2sql-v2/scripts" "$T/nl2sql-v2/scripts" && cp ~/judge-tmp/select_answer.py "$T/nl2sql-v2/scripts/"
ln -s "$U/judge-code/nl2sql-v2/src" "$T/nl2sql-v2/src"
( cd "$T/nl2sql-v2" && NL2SQL_DATA_ROOT=$M "$BPY" scripts/select_answer.py \
    --runs ~/judge-tmp/prodtest/runs_k1.csv,~/judge-tmp/prodtest/runs_k2.csv,~/judge-tmp/prodtest/runs_k3.csv,~/judge-tmp/prodtest/runs_k4.csv \
    --judge-endpoint http://127.0.0.1:8765/v1 --judge-model qwen36-base --mode pairwise --thinking \
    --output "$T/selected.csv" > "$T/select.log" 2>&1; echo "select_answer exit $?" >> "$T/select.log" ) &
SMOKE=$!

score 8765 qwen36-base &
S0=$!
score 8766 judge-v2a
wait $S0
kill $P1; sleep 30
CUDA_VISIBLE_DEVICES=${GPUS[1]} "$VPY" -m vllm.entrypoints.openai.api_server --model "$R/judge_train_v3/model_c/judge_awq" \
    --served-model-name judge-v3c --port 8766 "${FLAGS[@]}" > "$OUT/vllm_v3c_$SLURM_JOB_ID.log" 2>&1 &
P2=$!
up 8766 || { echo "v3c server not up"; tail -20 "$OUT/vllm_v3c_$SLURM_JOB_ID.log"; exit 1; }
score 8766 judge-v3c
wait $SMOKE
echo "done $(date -Is)"

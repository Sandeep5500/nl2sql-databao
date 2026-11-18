#!/bin/bash
# Held-out practice traces scored by a two-loss judge or the untrained base (scripts/c2_scores.py):
# both letters' log-probabilities after each stored reasoning sample, and the vector head's score when
# the adapter has one. Appends and skips scored traces, so a preempted job requeues and resumes.
#
#   sbatch --export=ALL,NAME=base ~/slurm/c2_scores.slurm
#   sbatch --export=ALL,NAME=c2_vec,ADAPTER=$R/judge_train_v4/model_c2_vec/choice_reason/final ~/slurm/c2_scores.slurm
#
#SBATCH --job-name=judge_c2score
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:2
#SBATCH --constraint=A6000|6000Ada|L40S|A100_80GB
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=1-00:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/judge_c2score_%j.out
set -uo pipefail
U=/data/user_data/$USER
R=$U/judge-data/results
OUT=$R/head_probe/c2
# no expandable_segments (judge_results.md section 7)
export HF_HOME=$U/.cache/huggingface
unset PYTORCH_CUDA_ALLOC_CONF
mkdir -p "$OUT"
echo "node=$(hostname) job=$SLURM_JOB_ID restarts=${SLURM_RESTART_COUNT:-0} start=$(date -Is) name=$NAME"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
A=()
[ -n "${ADAPTER:-}" ] && A=(--adapter "$ADAPTER")
"$U/judge-code/.venv-train-fla/bin/python" ~/judge-code-staging/nl2sql-v2/scripts/c2_scores.py "${A[@]}" \
    --verdicts "$R/judge_train/verdicts_train_v1.jsonl" "$R/judge_cplx/verdicts_cplx_v1.jsonl" \
        "$R/judge_cplx/verdicts_cplx_v2.jsonl" "$R/judge_claude/verdicts_claude_v3.jsonl" \
        "$R/judge_claude/verdicts_claude_h1.jsonl" "$R/judge_claude/verdicts_claude_h2.jsonl" \
        "$R/judge_beaver/verdicts_beaver_p1.jsonl" \
    --holdout "$R/judge_train_v4/data_v6/holdout.json" --out "$OUT/scores_$NAME.jsonl"
echo "exit $? end=$(date -Is)"

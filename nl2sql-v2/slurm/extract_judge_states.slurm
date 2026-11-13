#!/bin/bash
# Stage A of documents/head_probe_prereg.md: hidden states of the untuned bf16 judge after its own
# stored reasoning, for every usable practice judgment (scripts/extract_judge_states.py). Shards are
# written whole and skipped when present, so a preempted job requeues and resumes; WORKER/WORKERS
# split the shards between jobs.
#
#   sbatch --export=ALL,WORKER=0,WORKERS=2 ~/slurm/extract_judge_states.slurm
#   sbatch --export=ALL,WORKER=1,WORKERS=2 ~/slurm/extract_judge_states.slurm
#   (LIMIT=40 OUT=<dir> for a smoke run)
#
#SBATCH --job-name=judge_states
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:2
#SBATCH --constraint=A6000|6000Ada|L40S|A100_80GB
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=1-00:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/judge_states_%j.out
set -uo pipefail
U=/data/user_data/$USER
R=$U/judge-data/results
PY=${PY:-$U/judge-code/.venv-train-fla/bin/python}
OUT=${OUT:-$R/head_probe/states_base}
export HF_HOME=$U/.cache/huggingface PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
echo "node=$(hostname) job=$SLURM_JOB_ID restarts=${SLURM_RESTART_COUNT:-0} start=$(date -Is)"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
EXTRA=()
[ -n "${LIMIT:-}" ] && EXTRA=(--limit "$LIMIT")
"$PY" ~/judge-tmp/extract_judge_states.py --out-dir "$OUT" --worker "${WORKER:-0}" --workers "${WORKERS:-1}" \
    --verdicts "$R/judge_train/verdicts_train_v1.jsonl" "$R/judge_cplx/verdicts_cplx_v1.jsonl" \
        "$R/judge_cplx/verdicts_cplx_v2.jsonl" "$R/judge_claude/verdicts_claude_v3.jsonl" \
        "$R/judge_claude/verdicts_claude_h1.jsonl" "$R/judge_claude/verdicts_claude_h2.jsonl" \
        "$R/judge_beaver/verdicts_beaver_p1.jsonl" "${EXTRA[@]}"
echo "exit $? end=$(date -Is)"

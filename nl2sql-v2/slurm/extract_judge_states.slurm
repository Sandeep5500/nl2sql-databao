#!/bin/bash
# Stage A of documents/head_probe_prereg.md: hidden states of the untuned bf16 judge after its own
# stored reasoning, for every usable practice judgment (scripts/extract_judge_states.py). Shards are
# written whole and skipped when present, so a preempted job requeues and resumes; WORKER/WORKERS
# split the shards between jobs.
#
#   sbatch --export=ALL,WORKER=0,WORKERS=2 ~/slurm/extract_judge_states.slurm
#   sbatch --export=ALL,WORKER=1,WORKERS=2 ~/slurm/extract_judge_states.slurm
#   (LIMIT=40 OUT=<dir> for a smoke run)
#   Stage B (diff_cmp judgments, scripts/practice_dc.py; same file layout under another directory):
#   sbatch --export=ALL,PRACTICE=$R/practice_dc,OUT=$R/head_probe/states_dc,WORKER=0,WORKERS=2 ...
#   Any other record files (scripts/calls_to_records.py): VERDICTS="<file> <file>" (MAXTOK= raises the
#   16384-token limit, e.g. for BigQuery's long schema sections)
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
V=${PRACTICE:-$R}
# no expandable_segments: with it, both earlier runs failed the identity check (53 and 57 of 100) on
# L40S; without it the same forward passed with every layer finite (Nov 13)
export HF_HOME=$U/.cache/huggingface
unset PYTORCH_CUDA_ALLOC_CONF
echo "node=$(hostname) job=$SLURM_JOB_ID restarts=${SLURM_RESTART_COUNT:-0} start=$(date -Is)"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
EXTRA=()
[ -n "${LIMIT:-}" ] && EXTRA+=(--limit "$LIMIT")
[ -n "${MAXTOK:-}" ] && EXTRA+=(--max-tokens "$MAXTOK")
if [ -n "${VERDICTS:-}" ]; then
    FILES=($VERDICTS)
else
    FILES=("$V/judge_train/verdicts_train_v1.jsonl" "$V/judge_cplx/verdicts_cplx_v1.jsonl"
           "$V/judge_cplx/verdicts_cplx_v2.jsonl" "$V/judge_claude/verdicts_claude_v3.jsonl"
           "$V/judge_claude/verdicts_claude_h1.jsonl" "$V/judge_claude/verdicts_claude_h2.jsonl"
           "$V/judge_beaver/verdicts_beaver_p1.jsonl")
fi
md5sum "${FILES[@]}"
"$PY" ~/judge-tmp/extract_judge_states.py --out-dir "$OUT" --worker "${WORKER:-0}" --workers "${WORKERS:-1}" \
    --verdicts "${FILES[@]}" "${EXTRA[@]}"
echo "exit $? end=$(date -Is)"

#!/bin/bash
# Diagnose the bf16 HF forward of the judge model (scripts/diag_hf_forward.py); see that script.
#SBATCH --job-name=judge_diag
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:2
#SBATCH --constraint=A6000|6000Ada|L40S|A100_80GB
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=02:00:00
#SBATCH --output=/home/%u/joblogs/judge_diag_%j.out
set -uo pipefail
U=/data/user_data/$USER
export HF_HOME=$U/.cache/huggingface PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
echo "node=$(hostname) job=$SLURM_JOB_ID start=$(date -Is)"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
"$U/judge-code/.venv-train-fla/bin/python" ~/judge-tmp/diag_hf_forward3.py
echo "exit $? end=$(date -Is)"

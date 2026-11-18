#!/bin/bash
# Smoke test of train_judge_lora.py's choice-type stages (scripts/smoke_two_loss.py) on a tiny random
# model of the deployed architecture; any one GPU, a few minutes once running.
#SBATCH --job-name=judge_smoke
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=00:40:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/judge_smoke_%j.out
U=/data/user_data/$USER
export HF_HOME=$U/.cache/huggingface HF_HUB_OFFLINE=1
echo "node=$(hostname) job=$SLURM_JOB_ID start=$(date -Is)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
"$U/judge-code/.venv-train-fla/bin/python" ~/judge-code-staging/nl2sql-v2/scripts/smoke_two_loss.py \
    "$U/judge-data/results/smoke_two_loss" "$U/judge-data/results/judge_train_v4/data"
echo "exit $? end=$(date -Is)"

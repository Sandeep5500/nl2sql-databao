#!/bin/bash
# One MoE block at real dimensions: grouped_mm vs eager vs batched_mm experts (scripts/diag_moe_experts.py).
#SBATCH --job-name=judge_moe
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:1
#SBATCH --constraint=A6000|6000Ada|L40S|A100_80GB
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/judge_moe_%j.out
U=/data/user_data/$USER
export HF_HOME=$U/.cache/huggingface PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
echo "node=$(hostname) job=$SLURM_JOB_ID start=$(date -Is)"
"$U/judge-code/.venv-train-fla/bin/python" ~/judge-tmp/diag_moe_experts.py
echo "exit $? end=$(date -Is)"

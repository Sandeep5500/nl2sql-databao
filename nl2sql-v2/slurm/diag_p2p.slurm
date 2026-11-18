#!/bin/bash
# GPU-to-GPU copy integrity on a 2-GPU node (scripts/diag_p2p.py); seconds once running.
#SBATCH --job-name=judge_p2p
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:2
#SBATCH --constraint=A6000|6000Ada|L40S|A100_80GB
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:10:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/judge_p2p_%j.out
U=/data/user_data/$USER
echo "node=$(hostname) job=$SLURM_JOB_ID start=$(date -Is)"
"$U/judge-code/.venv-train-fla/bin/python" ~/judge-tmp/diag_p2p.py
echo "exit $? end=$(date -Is)"

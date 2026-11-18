#!/bin/bash
# Out-of-bounds check of the deployed architecture's kernels (scripts/diag_memcheck.py) under
# compute-sanitizer memcheck: first a plain run (seconds), then the sanitized one.
#SBATCH --job-name=judge_memcheck
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:1
#SBATCH --constraint=L40S|A6000|6000Ada
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/judge_memcheck_%j.out
U=/data/user_data/$USER
PY=$U/judge-code/.venv-train-fla/bin/python
export HF_HOME=$U/.cache/huggingface HF_HUB_OFFLINE=1
unset PYTORCH_CUDA_ALLOC_CONF
echo "node=$(hostname) job=$SLURM_JOB_ID start=$(date -Is)"
nvidia-smi --query-gpu=name,pci.bus_id --format=csv,noheader
"$PY" ~/judge-tmp/diag_memcheck.py 1016 2580
echo "plain run exit $? $(date -Is)"
PYTORCH_NO_CUDA_MEMORY_CACHING=1 /usr/local/cuda-13.3/bin/compute-sanitizer --tool memcheck --print-limit 30 \
    "$PY" ~/judge-tmp/diag_memcheck.py 1016 2580 8191 12001
echo "memcheck exit $? end=$(date -Is)"

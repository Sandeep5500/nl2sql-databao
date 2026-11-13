#!/bin/bash
# Judge adapter training: LoRA SFT, then DPO on top, then the adapter merged into the AWQ
# serving checkpoint (scripts/train_judge_lora.py, scripts/merge_judge_adapter.py). Every
# stage writes under $OUT and is skipped when its output exists; training checkpoints every
# 5 steps (80 rows; about 20-60 min at the smoke test's speed) and resumes from the latest, so
# a preempted job requeues and loses at most that. The bf16 base (Qwen/Qwen3.6-35B-A3B, ~70GB)
# is spread over the two 80GB GPUs.
#
#   sbatch ~/slurm/train_judge.slurm                       data from $D/results/judge_train/data
#   sbatch --export=ALL,SMOKE=1,DATA=<dir>,OUT=<dir> ~/slurm/train_judge.slurm
#       (SMOKE: a few steps of each stage on a small subset, to check size and speed)
#   STAGES="choice merge" (verdict-only stage on $DATA/choice.jsonl, instead of SFT/DPO)
#   STAGES="dpo merge" (DPO from the base, no SFT); SFT_ARGS / DPO_ARGS: extra
#   train_judge_lora.py flags, e.g. DPO_ARGS="--lr 5e-5 --epochs 2"
#
#SBATCH --job-name=judge_train
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:2
#SBATCH --constraint=A100_80GB
#SBATCH --cpus-per-task=16
#SBATCH --mem=200G
#SBATCH --time=2-00:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/judge_train_%j.out
set -uo pipefail
U=/data/user_data/$USER
C=$U/judge-code
D=$U/judge-data
DATA=${DATA:-$D/results/judge_train/data}
OUT=${OUT:-$D/results/judge_train/model}
# .venv-train plus fla-core (flash-linear-attention kernels for the gated-delta layers; the
# torch fallback made DPO ~3.4x slower in the smoke test)
PY=${PY:-$C/.venv-train-fla/bin/python}
export HF_HOME=$U/.cache/huggingface PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
echo "node=$(hostname) job=$SLURM_JOB_ID restarts=${SLURM_RESTART_COUNT:-0} start=$(date -Is)"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
rsync -a ~/judge-code-staging/ "$C/" || exit 1
cd "$C/nl2sql-v2" || exit 1
EXTRA=()
[ -n "${SMOKE:-}" ] && EXTRA=(--max-steps 3 --save-steps 2 --limit 8 --accum 2)
STAGES=${STAGES:-sft dpo merge}
echo "stages: $STAGES; sft args: ${SFT_ARGS:-}; dpo args: ${DPO_ARGS:-}"
mkdir -p "$OUT"
if [[ " $STAGES " == *" sft "* ]]; then
    [ -s "$OUT/sft/final/adapter_model.safetensors" ] || \
        "$PY" scripts/train_judge_lora.py sft --data "$DATA/sft.jsonl" --out "$OUT/sft" ${SFT_ARGS:-} "${EXTRA[@]}" || exit 1
    echo "sft done $(date -Is)"
    INIT=(--init "$OUT/sft/final")
else
    INIT=()
fi
if [[ " $STAGES " == *" choice "* ]]; then
    # verdict-only training (no reasoning) on choice.jsonl; CHOICE_ARGS: extra flags
    [ -s "$OUT/choice/final/adapter_model.safetensors" ] || \
        "$PY" scripts/train_judge_lora.py choice --data "$DATA/choice.jsonl" --out "$OUT/choice" \
            ${CHOICE_ARGS:-} "${EXTRA[@]}" || exit 1
    echo "choice done $(date -Is)"
    ADAPTER=$OUT/choice/final
else
    [ -s "$OUT/dpo/final/adapter_model.safetensors" ] || \
        "$PY" scripts/train_judge_lora.py dpo --data "$DATA/dpo.jsonl" "${INIT[@]}" \
            --out "$OUT/dpo" ${DPO_ARGS:-} "${EXTRA[@]}" || exit 1
    echo "dpo done $(date -Is)"
    ADAPTER=$OUT/dpo/final
fi
[ -s "$OUT/judge_awq/merged_adapter.json" ] || \
    "$PY" scripts/merge_judge_adapter.py --adapter "$ADAPTER" --out "$OUT/judge_awq" || exit 1
echo "done $(date -Is)"

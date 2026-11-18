#!/bin/bash
# Stage B step 1 of documents/head_probe_prereg.md, CPU half: diff_cmp prompts for the stored practice
# pairs (scripts/practice_dc.py prompts), one process per verdicts file, into $R/practice_dc in the same
# layout. The pair label files and holdout.json are copied next to them, so extract_judge_states.slurm
# (PRACTICE=) and probe_fit.py --practice read that directory as they read $R. A file is rebuilt
# unless its .done marker exists; input md5s are logged.
#
#   sbatch ~/judge-code-staging/nl2sql-v2/slurm/practice_dc_prompts.slurm      (LIMIT=20 for a smoke run)
#
#SBATCH --job-name=practice_dc_prompts
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=06:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/practice_dc_prompts_%j.out
set -u
U=/data/user_data/$USER
M=$U/nl2sql-databao
D=$U/judge-data
R=$D/results
P=${P:-$R/practice_dc}
PY=$M/nl2sql-v2/.venv/bin/python
export NL2SQL_DATA_ROOT=$M
echo "node=$(hostname) job=$SLURM_JOB_ID restarts=${SLURM_RESTART_COUNT:-0} start=$(date -Is)"
cd ~/judge-code-staging/nl2sql-v2
EXTRA=()
[ -n "${LIMIT:-}" ] && EXTRA=(--limit "$LIMIT")
pids=()
for spec in judge_train/train_v1:bird_plat judge_cplx/cplx_v1:bird_plat judge_cplx/cplx_v2:bird_plat \
        judge_claude/claude_v3:bird_plat judge_claude/claude_h1:bird_plat judge_claude/claude_h2:bird_plat \
        judge_beaver/beaver_p1:beaver; do
    rel=${spec%%:*}; ds=${spec##*:}; dir=${rel%/*}; tag=${rel##*/}
    in=$R/$dir/verdicts_$tag.jsonl; out=$P/$dir/prompts_$tag.jsonl
    mkdir -p "$P/$dir"
    echo "$(md5sum < "$in" | cut -c1-32) $in"
    [ -e "$out.done" ] && continue
    ( NL2SQL_DATASET_DIR=$D/$ds "$PY" scripts/practice_dc.py prompts --verdicts "$in" --out "$out" "${EXTRA[@]}" \
        > "$P/$dir/prompts_$tag.log" 2>&1 && [ -z "${LIMIT:-}" ] && touch "$out.done"
      tail -1 "$P/$dir/prompts_$tag.log" ) &
    pids+=($!)
done
[ ${#pids[@]} -gt 0 ] && wait "${pids[@]}"
for f in judge_cplx/pair_labels_v1.jsonl judge_cplx/pair_labels_v2.jsonl judge_claude/pair_labels_v3.jsonl \
        judge_claude/pair_labels_h1.jsonl judge_claude/pair_labels_h2.jsonl judge_beaver/pair_labels_p1.jsonl \
        judge_train_v4/data_v6/holdout.json; do
    mkdir -p "$P/$(dirname "$f")"
    cp -p "$R/$f" "$P/$f"
done
echo "exit 0 end=$(date -Is)"

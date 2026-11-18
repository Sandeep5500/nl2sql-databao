#!/bin/bash
# Selection-eval pools for Spider2 run sets added after the Nov 12 eval set (Nov 18: Sandeep's q36e and
# q36x, 4 lanes each). CPU only. Steps, each resumable:
#   1. install the staged judge scripts (~/judge-code-staging/runsets/) into judge-code, originals kept as
#      *.bak_nov18;
#   2. judge_pools.py --no-judge: every lane's SQL re-run as the reference pools ran it, equal results
#      grouped, groups labelled by the scorer (12 shards per run set);
#   3. runset_evalset.py: the eval set, halves from the Nov 12 split by database, plus a label check;
#   4. build_compare_cache.py: diff_cmp's comparisons (8 shards, merged);
#   5. checks: calls each judge arm will make, and one dry-run prompt.
# The judge arms then run in judge_variants.slurm (35B: EVALSET, QUEUE, LOG set to $R) and
# jev_variants.slurm (27B: EVALSET, COMPARISONS, REF_PREFIX=groups/sp, OUT, LOG).
#
#   sbatch --partition=lilab --qos=lilab_qos --exclude=babel-w9-28 ~/slurm/runset_pools.slurm
#
#SBATCH --job-name=runset_pools
#SBATCH --cpus-per-task=16
#SBATCH --mem=48G
#SBATCH --time=03:00:00
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/runset_pools_%j.out
set -u -o pipefail
U=/data/user_data/$USER
M=$U/nl2sql-databao                     # benchmark venv, Spider2 DBs and gold
W=$U/nl2sql-sel
R=${R:-$HOME/runsets}                   # inputs (csv/) and outputs, readable from the login node
RUNSETS=${RUNSETS:-q36e q36x}
PREFIX=groups/sp
C=$U/judge-code/nl2sql-v2
PY=$M/nl2sql-v2/.venv/bin/python
export NL2SQL_DATA_ROOT=$M
log() { echo "[$(date -Is)] $*"; }
log "node=$(hostname) job=$SLURM_JOB_ID runsets=$RUNSETS"

for f in judge_pools.py runset_evalset.py selection_eval.py rejudge_pools.py build_compare_cache.py \
         result_compare.py judge_prompts.py; do
    [ -e "$C/scripts/$f" ] && [ ! -e "$C/scripts/$f.bak_nov18" ] && cp -p "$C/scripts/$f" "$C/scripts/$f.bak_nov18"
    cp ~/judge-code-staging/runsets/$f "$C/scripts/$f.tmp.$$" && mv -f "$C/scripts/$f.tmp.$$" "$C/scripts/$f" || exit 1
done
md5sum "$C"/scripts/{judge_pools,runset_evalset,selection_eval,rejudge_pools,build_compare_cache,result_compare,judge_prompts}.py
cd "$C" || exit 1
mkdir -p "$W/results/pools/groups" "$R/pools" "$R/logs" "$R/cmp"

PIDS=()
for rs in $RUNSETS; do for k in $(seq 0 11); do
    "$PY" scripts/judge_pools.py --no-judge --shard "$k/12" --resume \
        --runs "$R/csv/${rs}_pass4_k1.csv,$R/csv/${rs}_pass4_k2.csv,$R/csv/${rs}_pass4_k3.csv,$R/csv/${rs}_pass4_k4.csv" \
        --output "$W/results/pools/${PREFIX}_${rs}_n12_s$k.jsonl" > "$R/logs/pools_${rs}_s$k.log" 2>&1 &
    PIDS+=($!)
done; done
fail=0
for p in "${PIDS[@]}"; do wait "$p" || fail=$((fail+1)); done
log "pool shards finished, $fail failed"
[ $fail = 0 ] || exit 1
cp "$W/results/pools/groups/"sp_*_n12_s*.jsonl "$R/pools/"

"$PY" scripts/runset_evalset.py --pools "$W/results/pools" --ref-prefix "$PREFIX" --runsets "${RUNSETS// /,}" \
    --split-from "$W/results/variants/selection_evalset.json" --out "$R/runsets_evalset.json" \
    | tee "$R/evalset_summary.txt" || exit 1

PIDS=()
for k in $(seq 0 7); do
    "$PY" scripts/build_compare_cache.py --evalset "$R/runsets_evalset.json" --pools "$W/results/pools" \
        --ref-prefix "$PREFIX" --select "half=design|test" --shard "$k/8" --out "$R/cmp/compare_cache_s$k.jsonl" \
        > "$R/logs/cmp_s$k.log" 2>&1 &
    PIDS+=($!)
done
fail=0
for p in "${PIDS[@]}"; do wait "$p" || fail=$((fail+1)); done
log "comparison shards finished, $fail failed"
[ $fail = 0 ] || exit 1
cat "$R/cmp/"compare_cache_s*.jsonl > "$R/compare_cache.jsonl"
tail -n 3 "$R"/logs/cmp_s*.log

ARGS=(--evalset "$R/runsets_evalset.json" --pools "$W/results/pools" --ref-prefix "$PREFIX"
      --comparisons "$R/compare_cache.jsonl" --judge-endpoint http://localhost:1/v1 --judge-model x)
log "diff_cmp x4 calls per judge: $("$PY" scripts/rejudge_pools.py "${ARGS[@]}" --variants diff_cmp --samples 4 \
    --out-dir "$R/empty" --count-only)"
"$PY" scripts/rejudge_pools.py "${ARGS[@]}" --variants diff_cmp --out-dir "$R/empty" --dry-run > "$R/dryrun.txt" 2>&1
log "dry run: exit $?, $(wc -c < "$R/dryrun.txt") chars, comparison lines $(grep -c '^Shapes:' "$R/dryrun.txt")"
log "done"

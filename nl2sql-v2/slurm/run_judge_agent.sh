#!/bin/bash
# Agent runs on the judge-training question set: LANES pass@K lanes at temperature 0.7
# (as the Spider2 pass@4 runs), each split into SHARDS processes, spread over the vLLM
# servers on this node that answer at launch (ports in $PORTS; judge_overnight.sh runs a
# second one). Every process writes its own CSV with --resume, so a rerun after preemption, or
# with more question ids added to the list, runs only what is missing. Lane CSVs are
# concatenated into lane<k>.csv at the end, the per-lane input sample_judge_verdicts.py takes.
#
# Run inside the judge GPU session:
#   srun --jobid=<session> --overlap -n1 --cpus-per-task=16 bash ~/slurm/run_judge_agent.sh \
#       <tag> <file with one instance id per line> [lanes=4] [shards=4]
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
U=/data/user_data/$USER
C=$U/judge-code
M=$U/nl2sql-databao
D=${DS:-$U/judge-data/bird_plat}   # DS: another question set in the same layout
TAG=$1
IDS=$2
LANES=${3:-4}
SHARDS=${4:-4}
NODE=$(hostname)
R=$U/judge-data/results/agent/$TAG
mkdir -p "$R"
[ -s "$D/dce/output/dce.duckdb" ] || { echo "no context index yet (enrich_judge_dce.sh)"; exit 1; }
# the servers are chosen once, here: one whose process is up but not yet answering (still
# loading after a restart) is waited for, up to 10 min
for _ in $(seq 1 60); do
    LIVE=(); loading=0
    for p in ${PORTS:-8765 8766}; do
        if curl -sf "localhost:$p/v1/models" >/dev/null; then LIVE+=("$p")
        elif pgrep -f -- "--port $p" >/dev/null; then loading=1; fi
    done
    [ $loading = 0 ] && break
    sleep 10
done
[ ${#LIVE[@]} -gt 0 ] || { echo "no vLLM on this node"; exit 1; }
export NL2SQL_DATASET_DIR=$D DCE_OLLAMA_HOST=$NODE
cd "$C/nl2sql-v2" || exit 1
echo "$(wc -l < "$IDS") questions x $LANES lanes, $SHARDS shards each, servers ${LIVE[*]}, $(date -Is)"
k=0
for l in $(seq 1 "$LANES"); do
    for s in $(seq 0 $((SHARDS - 1))); do
        ids=$(awk -v s="$s" -v S="$SHARDS" 'NF && (NR - 1) % S == s' "$IDS" | paste -sd, -)
        [ -n "$ids" ] || continue
        port=${LIVE[$((k % ${#LIVE[@]}))]}; k=$((k + 1))
        uv run --project "$M/nl2sql-v2" python scripts/run_benchmark.py \
            --endpoint "http://$NODE:$port/v1" --schema-overview --temperature 0.7 --resume \
            --instances "$ids" --output "$R/lane${l}_s${s}.csv" --trace-dir "$R/traces_lane$l" \
            > "$R/lane${l}_s${s}.log" 2>&1 &
    done
done
wait
for l in $(seq 1 "$LANES"); do
    awk 'FNR > 1 || NR == 1' "$R"/lane"${l}"_s*.csv > "$R/lane$l.csv"
    echo "lane $l: $(($(wc -l < "$R/lane$l.csv") - 1)) rows"
done
echo "done $(date -Is)"

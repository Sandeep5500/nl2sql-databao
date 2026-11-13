#!/bin/bash
# Rebuild spider2-dce/output/dce.duckdb from the enriched YAMLs already in git.
#
#   sbatch --chdir=/data/user_data/$USER/nl2sql-databao nl2sql-v2/slurm/build_dce_index.slurm
#
# Embeddings only: the per-column descriptions are committed under
# spider2-dce/output/databases/*.yaml, so no vLLM and no LLM calls are involved --
# index_one_db.py refuses to enrich and fails loudly if a YAML turns out to be missing.
#
# Sequential by necessity: DuckDB permits a single writer per database file, so the
# datasources are indexed one after another into the one dce.duckdb.
#
#SBATCH --job-name=dce_index
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:A6000:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=06:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/dce_index_%j.out
#SBATCH --error=/home/%u/joblogs/dce_index_%j.out

set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
REPO="$PWD"
[ -d "$REPO/spider2-dce" ] || { echo "not a checkout: $REPO (use --chdir)" >&2; exit 1; }
mkdir -p logs/dce

echo "node=$(hostname) job=$SLURM_JOB_ID started=$(date -Is)"

# The source datasource YAMLs carry absolute database_path values from whoever built the
# index first; repoint them at this checkout. Idempotent.
sed -i "s#/data/user_data/[^/]*/personal/nl2sql-databao#$REPO#g" spider2-dce/src/databases/*.yaml
sed -i "s#/data/user_data/[^/]*/nl2sql-databao#$REPO#g" spider2-dce/src/databases/*.yaml

export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_KEEP_ALIVE=24h
"$HOME/.dce/ollama/bin/ollama" serve > "logs/dce/ollama_${SLURM_JOB_ID}.log" 2>&1 &
OLLAMA_PID=$!
trap 'kill $OLLAMA_PID 2>/dev/null' EXIT TERM INT

for i in $(seq 1 60); do
    curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 2
done
curl -sf http://127.0.0.1:11434/api/tags >/dev/null || { echo "ollama never came up"; exit 1; }
echo "ollama up"

cd spider2-dce
OK=0; FAILED=0; FAILED_LIST=""
for y in output/databases/*.yaml; do
    name=$(basename "$y")
    # already indexed? skip, so a requeued job resumes instead of redoing the work
    if [ -f "output/.indexed/$name" ]; then
        echo "--- $name: already indexed, skipping"; OK=$((OK+1)); continue
    fi
    echo "=== $name ==="
    if uv run --project ../nl2sql-v2 python ../scripts/index_one_db.py \
           --datasource "databases/$name" --embed-host 127.0.0.1 --embed-port 11434 \
           --dce-dir . 2>&1 | tail -6; then
        mkdir -p output/.indexed && touch "output/.indexed/$name"
        OK=$((OK+1))
    else
        FAILED=$((FAILED+1)); FAILED_LIST="$FAILED_LIST $name"
    fi
done

echo "=========================================="
echo "indexed OK: $OK   failed: $FAILED"
[ -n "$FAILED_LIST" ] && echo "failed:$FAILED_LIST"
ls -la output/dce.duckdb 2>/dev/null
echo "finished=$(date -Is)"
[ "$FAILED" = "0" ]

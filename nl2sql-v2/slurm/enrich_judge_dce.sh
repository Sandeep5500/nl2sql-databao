#!/bin/bash
# Context-engine records for the judge-training question set, built as Spider2's were:
#   1. per-datasource records with descriptions from the served model (enrich_one_db.py),
#      in K parallel workers, each in its own project copy (DuckDB allows one writer per
#      index file, and the build holds it for the whole run), without indexing;
#   2. column descriptions rewritten from the column profile, as apply_notes_to_dce.py did
#      for Spider2 (there are no explored notes here; table descriptions keep the key line,
#      or the model's text where there is none), and foreign keys declared without a
#      target column given the parent's primary key (fix_dce_fk_targets.py);
#   3. one embedding pass into the main index.
# Each step skips what is done, so a rerun after preemption resumes.
#
# Run inside the judge GPU session (vLLM and Ollama on this node):
#   srun --jobid=<session> --overlap -n1 --cpus-per-task=8 bash ~/slurm/enrich_judge_dce.sh
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
U=/data/user_data/$USER
C=$U/judge-code                      # this work's code
M=$U/nl2sql-databao                  # existing checkout: the uv project with the context engine
D=${DS:-$U/judge-data/bird_plat}   # DS: another question set in the same layout
P=$D/dce
W=${DCE_W:-$U/judge-data/dce_workers}   # per question set (DCE_W)
K=${K:-6}
NODE=$(hostname)
MODEL=${MODEL:-QuantTrio/Qwen3.6-35B-A3B-AWQ}
curl -sf "localhost:8765/v1/models" >/dev/null || { echo "no vLLM on this node"; exit 1; }
curl -sf localhost:11434/api/tags >/dev/null || { echo "no Ollama on this node"; exit 1; }

# the staged records name the laptop's database paths; point them here (idempotent)
sed -i "s#^\(  database_path: \).*/\([^/]*\.sqlite\)\$#\1$D/databases/\2#" "$P"/src/databases/*.yaml
mkdir -p "$P/output/databases" "$W"
ls "$P/src/databases" | while read -r y; do
    [ -s "$P/output/databases/$y" ] || [ -s "$P/output/databases_pre_explore/$y" ] || echo "$y"
done > "$W/todo.txt"
echo "$(wc -l < "$W/todo.txt") datasources to describe, $K workers, $(date -Is)"

for k in $(seq 0 $((K - 1))); do
    wd=$W/w$k
    mkdir -p "$wd/src/databases" "$wd/output/databases"
    cp "$P/dce.ini" "$wd/"
    awk -v k="$k" -v K="$K" '(NR - 1) % K == k' "$W/todo.txt" | while read -r y; do
        ln -sf "$P/src/databases/$y" "$wd/src/databases/$y"
    done
    (
        cd "$wd" || exit 1
        for y in $(ls src/databases); do
            [ -s "output/databases/$y" ] && continue
            uv run --project "$M/nl2sql-v2" python "$C/scripts/enrich_one_db.py" \
                --datasource "databases/$y" --vllm-host "$NODE" --vllm-port 8765 \
                --vllm-model "$MODEL" --embed-host "$NODE" --embed-port 11434 --dce-dir . \
                --no-index >> "$W/w$k.log" 2>&1 || echo "FAILED $y" | tee -a "$W/w$k.log"
            echo "w$k $y $(date +%H:%M:%S)"
        done
    ) &
done
wait
for wd in "$W"/w*/; do
    for f in "$wd"output/databases/*.yaml; do
        [ -s "$f" ] && { [ -s "$P/output/databases/$(basename "$f")" ] || cp "$f" "$P/output/databases/"; }
    done
done
n=$(ls "$P/output/databases" | wc -l); echo "described: $n of $(ls "$P/src/databases" | wc -l)"
[ "$n" -eq "$(ls "$P/src/databases" | wc -l)" ] || { echo "some datasources failed; see $W/w*.log"; exit 1; }

cd "$C" || exit 1
export NL2SQL_DATASET_DIR=$D DCE_OLLAMA_HOST=$NODE
uv run --project "$M/nl2sql-v2" python scripts/apply_notes_to_dce.py --write || exit 1
# foreign keys declared without a target column cannot be read back from the records
uv run --project "$M/nl2sql-v2" python scripts/fix_dce_fk_targets.py "$P/output/databases" || exit 1
# the workers built no index, so the main project has none yet: create it empty
uv run --project "$M/nl2sql-v2" python -c "
from pathlib import Path
from databao_context_engine.project.layout import ensure_project_dir
from databao_context_engine.storage.migrate import migrate
p = ensure_project_dir(project_dir=Path('$P')).db_path
p.parent.mkdir(parents=True, exist_ok=True)
p.exists() or migrate(p)" || exit 1
uv run --project "$M/nl2sql-v2" python scripts/apply_notes_to_dce.py --index || exit 1
ls -la "$P/output/dce.duckdb"
echo "done $(date -Is)"

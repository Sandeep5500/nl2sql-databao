#!/bin/bash
# Judge training data, CPU part. Downloads BIRD train and BIRD-Platinum, checks every
# BIRD database against the Spider2 local ones, builds the question set
# (scripts/build_bird_dataset.py) and computes the data-only DCE inputs for its
# databases (column profile, unique keys). Every step is skipped when its output exists,
# so a preempted job just requeues. What the laptop already built (the overlap results and
# the question set, with its written questions and DCE inputs) is staged in
# ~/judge-data-staging and used as is, so both copies hold the same questions; only the
# databases come from this node's BIRD download. judge_gpu_session.slurm runs this script
# too, so whichever starts first builds.
#
#   code staged by the laptop into ~/judge-code-staging (login node), then:
#   sbatch ~/slurm/build_judge_data.slurm                                  (preempt)
#   sbatch --partition=lilab --qos=lilab_qos ~/slurm/build_judge_data.slurm  (lilab)
#
# Layout on the compute node:
#   $U/judge-code    this work's code (copied from the staging dir at job start)
#   $U/judge-data    sources/, results/, and the built dataset bird_plat/
# Spider2 questions and DBs come from the existing checkout via NL2SQL_DATA_ROOT.
#
#SBATCH --job-name=judge_data
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/judge_data_%j.out

set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
U=/data/user_data/$USER
C=$U/judge-code
D=$U/judge-data
export NL2SQL_DATA_ROOT=$U/nl2sql-databao
BACK=$HOME/joblogs/judge_data          # small results, readable from the login node
PLAT=https://raw.githubusercontent.com/uiuc-kang-lab/ReViSQL/main/data
echo "node=$(hostname) job=$SLURM_JOB_ID start=$(date -Is)"
df -h "$U" | tail -1
FREE_GB=$(df -BG --output=avail "$U" | tail -1 | tr -dc 0-9)
[ "${FREE_GB:-0}" -ge 60 ] || { echo "only ${FREE_GB}G free under $U; need ~60G"; exit 1; }
ls "$NL2SQL_DATA_ROOT"/Spider2/spider2-lite/resource/databases/spider2-localdb/*.sqlite | wc -l \
    | sed 's/^/spider2 local dbs: /'
mkdir -p "$C" "$D/sources/bird" "$D/sources/platinum" "$D/results" "$BACK"
# copies of this job may sit in two partitions; whichever starts second waits, then
# finds every step done
exec 9>"$D/.build.lock"
flock -n 9 || { echo "another judge_data job is building; waiting for it"; flock 9; }
rsync -a ~/judge-code-staging/ "$C/" || exit 1

# light environment for the data steps (no GPU packages, no context engine)
PY=$C/.venv-data/bin/python
[ -x "$PY" ] || { uv venv -q --python 3.12 "$C/.venv-data" && \
    uv pip install -q --python "$PY" duckdb==1.5.5 pandas==3.0.5 pyyaml==6.0.3 \
        sqlglot==30.18.0 openai==3.13.0; } || exit 1

# 0. the laptop's build
SEED=$HOME/judge-data-staging
[ -s "$D/results/db_overlap_bird_train.csv" ] || cp "$SEED/db_overlap_bird_train.csv" "$D/results/" 2>/dev/null
[ -s "$D/bird_plat/questions.jsonl" ] || [ ! -s "$SEED/bird_plat/questions.jsonl" ] || \
    rsync -a "$SEED/bird_plat/" "$D/bird_plat/" || exit 1

# 1. sources
cd "$D/sources/bird" || exit 1
if [ -z "$(ls -d */train_databases train_databases 2>/dev/null | head -1)" ]; then
    for i in $(seq 1 10); do  # the bucket drops long transfers; resume where it stopped
        curl -sfL -C - --max-time 3600 -o train.zip \
            https://bird-bench.oss-cn-beijing.aliyuncs.com/train.zip && break
        echo "download retry $i at $(stat -c%s train.zip 2>/dev/null) bytes"; sleep 10
    done
    unzip -q -o train.zip -x '__MACOSX/*' || { echo "train.zip incomplete"; exit 1; }
    inner=$(find . -name 'train_databases.zip' | head -1)
    [ -n "$inner" ] && { unzip -q -o "$inner" -d "$(dirname "$inner")" -x '__MACOSX/*' && rm -f "$inner"; }
    rm -f train.zip
fi
one=$(find "$D/sources/bird" -path '*train_databases/*/*.sqlite' | head -1)
[ -n "$one" ] || { echo "no BIRD train databases after unzip"; ls -R "$D/sources/bird" | head; exit 1; }
BIRD_DBS=$(cd "$(dirname "$one")/.." && pwd)
echo "BIRD train databases: $BIRD_DBS ($(ls "$BIRD_DBS" | wc -l) dirs)"
for f in bird-verified-train.json bird-verified-val.json; do
    [ -s "$D/sources/platinum/$f" ] || curl -sfL --retry 3 -o "$D/sources/platinum/$f" "$PLAT/$f" || exit 1
done
sha256sum "$D"/sources/platinum/*.json | tee "$BACK/platinum_sha256.txt"

cd "$C/nl2sql-v2" || exit 1
# 2. which BIRD databases hold the same data as a Spider2 one
[ -s "$D/results/db_overlap_bird_train.csv" ] || \
    "$PY" scripts/check_db_overlap.py --candidates "$BIRD_DBS" \
        --output "$D/results/db_overlap_bird_train.csv" --cache-dir "$D/results/fp" \
        > "$D/results/db_overlap_bird_train.log" 2>&1
cp "$D/results/db_overlap_bird_train.csv" "$D/results/db_overlap_bird_train.log" "$BACK/"
tail -3 "$D/results/db_overlap_bird_train.log"

# 3. the question set
[ -s "$D/bird_plat/questions.jsonl" ] || \
    "$PY" scripts/build_bird_dataset.py \
        --items "$D/sources/platinum/bird-verified-train.json,$D/sources/platinum/bird-verified-val.json" \
        --bird-dbs "$BIRD_DBS" --deny scripts/judge_data_deny.json --out "$D/bird_plat" \
        --workers 8 > "$D/results/build_bird_plat.log" 2>&1
tail -2 "$D/results/build_bird_plat.log"
cp "$D/bird_plat/build_report.json" "$D/bird_plat/db_split.json" "$D/results/build_bird_plat.log" "$BACK/"
# a staged question set names its databases; link each to this node's BIRD copy
mkdir -p "$D/bird_plat/databases"
for db in $("$PY" -c 'import json, sys; s = json.load(open(sys.argv[1])); print(*s["train"], *s["heldout"])' \
        "$D/bird_plat/db_split.json"); do
    [ -e "$D/bird_plat/databases/$db.sqlite" ] || ln -s "$BIRD_DBS/$db/$db.sqlite" "$D/bird_plat/databases/$db.sqlite"
done
ls -L "$D"/bird_plat/databases/*.sqlite | wc -l | sed 's/^/databases linked: /'
# the staged context-engine configs name the laptop's database paths; point them here
sed -i "s#^\(  database_path: \).*/\([^/]*\.sqlite\)\$#\1$D/bird_plat/databases/\2#" \
    "$D"/bird_plat/dce/src/databases/*.yaml

# 4. data-only DCE inputs (the LLM steps run later on a GPU node)
export NL2SQL_DATASET_DIR=$D/bird_plat
cd "$C" || exit 1
# skipped when staged: the key search runs under a time budget, so a second run on other
# hardware could settle on different keys than the laptop's
[ -n "$(ls "$D/bird_plat/dce/output/profile" 2>/dev/null)" ] || \
    "$PY" scripts/compute_profile.py --out-dir "$D/bird_plat/dce/output/profile" \
        > "$D/results/profile_bird_plat.log" 2>&1
[ -n "$(ls "$D/bird_plat/dce/output/keys" 2>/dev/null)" ] || \
    "$PY" scripts/compute_keys.py --out-dir "$D/bird_plat/dce/output/keys" --budget-s 60 \
        > "$D/results/keys_bird_plat.log" 2>&1
ls "$D/bird_plat/dce/output/profile" | wc -l | sed 's/^/profiles: /'
ls "$D/bird_plat/dce/output/keys" | wc -l | sed 's/^/keys: /'
du -sh "$D"
echo "done $(date -Is)"

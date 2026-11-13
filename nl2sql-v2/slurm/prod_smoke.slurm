#!/bin/bash
# Smoke test of the production judge path with the adopted prompt: select_answer.py --mode pairwise
# --thinking (default --judge-prompt diff_cmp) on 3 Spider2 questions whose run files are built from
# stored pools (~/judge-tmp/prodtest/runs_k*.csv), against one served base judge. Runs from a temporary
# copy of the judge code with ~/judge-tmp/select_answer.py, so the shared code is untouched.
#SBATCH --job-name=judge_smoke
#SBATCH --partition=preempt
#SBATCH --qos=preempt_qos
#SBATCH --gres=gpu:1
#SBATCH --constraint=A6000|6000Ada|L40S|A100_80GB
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=02:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/judge_smoke_%j.out
set -uo pipefail
U=/data/user_data/$USER
M=$U/nl2sql-databao
T=$U/judge-data/results/head_probe/prodtest
H=$HOME/judge-tmp/prodtest
echo "node=$(hostname) job=$SLURM_JOB_ID restarts=${SLURM_RESTART_COUNT:-0} start=$(date -Is)"
export HF_HOME=$U/.cache/huggingface
"$M/.vllm-venv/bin/python" -m vllm.entrypoints.openai.api_server --model QuantTrio/Qwen3.6-35B-A3B-AWQ \
    --served-model-name qwen36-base --port 8765 --host 127.0.0.1 --max-model-len 32768 \
    --gpu-memory-utilization 0.92 --dtype bfloat16 --enforce-eager --trust-remote-code \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 > "$T.vllm.log" 2>&1 &
P=$!
trap 'kill $P 2>/dev/null' EXIT
for _ in $(seq 1 240); do curl -sf localhost:8765/v1/models >/dev/null && break; sleep 10; done
curl -sf localhost:8765/v1/models >/dev/null || { echo "server not up"; tail -20 "$T.vllm.log"; exit 1; }
rm -rf "$T" && mkdir -p "$T/nl2sql-v2"
cp -r "$U/judge-code/nl2sql-v2/scripts" "$T/nl2sql-v2/scripts" && cp "$HOME/judge-tmp/select_answer.py" "$T/nl2sql-v2/scripts/"
ln -s "$U/judge-code/nl2sql-v2/src" "$T/nl2sql-v2/src"
cd "$T/nl2sql-v2" && NL2SQL_DATA_ROOT=$M "$M/nl2sql-v2/.venv/bin/python" scripts/select_answer.py \
    --runs "$H/runs_k1.csv,$H/runs_k2.csv,$H/runs_k3.csv,$H/runs_k4.csv" \
    --judge-endpoint http://127.0.0.1:8765/v1 --judge-model qwen36-base --mode pairwise --thinking \
    --output "$T/selected.csv"
echo "select_answer exit $? end=$(date -Is)"
cat "$T/selected.csv"

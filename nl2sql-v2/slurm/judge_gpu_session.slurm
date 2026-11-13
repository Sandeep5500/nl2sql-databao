#!/bin/bash
# Judge-training GPU session: serves the deployed agent model (the 35B AWQ build, with
# tool calling as in the benchmark runs) on the first GPU and the context engine's Ollama
# embeddings on the second, then stays up so the data steps (DCE enrichment, agent pilot,
# judge sampling) run against it from the login node, without a queue wait each:
#   srun --jobid=<id> --overlap -n1 --cpus-per-task=8 bash -c '<command>'
# Endpoints are written to ~/joblogs/judge_gpu_session.txt once vLLM answers. The session
# also runs build_judge_data.slurm's steps in the background (each skipped when done), so
# the question set does not wait for a CPU slot.
#
#   sbatch ~/slurm/judge_gpu_session.slurm                                   (lilab)
#   sbatch --partition=preempt --qos=preempt_qos --gres=gpu:2 \
#       --constraint='A6000|6000Ada|L40S|A100_80GB' ~/slurm/judge_gpu_session.slurm  (preempt)
#   [MODEL=... PORT=... in the environment]
# A lilab copy and a preempt copy can both wait in the queue: a preempt copy that starts
# while a lilab one runs exits at once, and a lilab copy cancels the preempt ones as soon
# as it serves (the runners resume against the new endpoint).
#
#SBATCH --job-name=judge_gpu
#SBATCH --partition=lilab
#SBATCH --qos=lilab_qos
#SBATCH --gres=gpu:A6000:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=2-00:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/judge_gpu_%j.out

set -u
U=/data/user_data/$USER
M=$U/nl2sql-databao                     # existing checkout: the vLLM venv
PORT=${PORT:-8765}
MODEL=${MODEL:-QuantTrio/Qwen3.6-35B-A3B-AWQ}
export HF_HOME=$U/.cache/huggingface VLLM_MLA_DISABLE=1
LOG=$U/judge-data/logs
mkdir -p "$LOG"
INFO=$HOME/joblogs/judge_gpu_session.txt
echo "node=$(hostname) job=$SLURM_JOB_ID partition=$SLURM_JOB_PARTITION start=$(date -Is) gpus=${CUDA_VISIBLE_DEVICES:-}"
if [ "$SLURM_JOB_PARTITION" != lilab ] && \
        [ -n "$(squeue -h -u "$USER" -n judge_gpu -p lilab -t RUNNING -o %i)" ]; then
    echo "a lilab session is running; exiting"; exit 0
fi
bash "$HOME/slurm/build_judge_data.slurm" > "$LOG/data_build_$SLURM_JOB_ID.log" 2>&1 &
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
df -h "$U" | tail -1
module load cuda-12.1 2>/dev/null || true
GPUS=(${CUDA_VISIBLE_DEVICES//,/ })

CUDA_VISIBLE_DEVICES=${GPUS[1]} OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=24h \
    "$HOME/.dce/ollama/bin/ollama" serve > "$LOG/ollama_$SLURM_JOB_ID.log" 2>&1 &
OLLAMA_PID=$!
CUDA_VISIBLE_DEVICES=${GPUS[0]} "$M/.vllm-venv/bin/python" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" --port "$PORT" --host 0.0.0.0 --max-model-len 60000 \
    --gpu-memory-utilization 0.92 --dtype bfloat16 --enforce-eager --trust-remote-code \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
    --enable-prefix-caching --mamba-cache-mode align \
    > "$LOG/vllm_$SLURM_JOB_ID.log" 2>&1 &
VLLM_PID=$!
trap 'kill $VLLM_PID $OLLAMA_PID 2>/dev/null' EXIT

for i in $(seq 1 240); do   # up to 40 min (a first run downloads the weights)
    curl -sf "localhost:$PORT/v1/models" >/dev/null && break
    kill -0 $VLLM_PID 2>/dev/null || { echo "vLLM died"; tail -40 "$LOG/vllm_$SLURM_JOB_ID.log"; exit 1; }
    sleep 10
done
curl -sf "localhost:$PORT/v1/models" >/dev/null || { echo "vLLM not up after 40 min"; exit 1; }
curl -sf localhost:11434/api/tags >/dev/null || echo "warning: ollama is not answering"
printf 'job=%s\nnode=%s\nvllm=http://%s:%s/v1\nmodel=%s\nollama_host=%s\nstarted=%s\n' \
    "$SLURM_JOB_ID" "$(hostname)" "$(hostname)" "$PORT" "$MODEL" "$(hostname)" "$(date -Is)" | tee "$INFO"
if [ "$SLURM_JOB_PARTITION" = lilab ]; then
    scancel -u "$USER" -n judge_gpu -p preempt && echo "cancelled any preempt session"
fi
wait $VLLM_PID
echo "vLLM exited $(date -Is)"; tail -20 "$LOG/vllm_$SLURM_JOB_ID.log"

#!/bin/bash
# Login-node keeper for eval_judge_pools.sh: Babel can cancel the eval step, and a preempted
# judge GPU session requeues on another node. Every 5 minutes, if a judge_gpu session is running
# and the eval is not running inside it (and has not finished), relaunch it there; every shard
# resumes.
#   setsid nohup bash ~/slurm/keep_eval_alive.sh > ~/joblogs/keep_eval_alive.log 2>&1 < /dev/null &
L=~/joblogs/eval_judge_pools.log
while true; do
    if tail -1 "$L" | grep -qE "\] done$"; then
        echo "[$(date -Is)] eval finished; keeper exits"; exit 0
    fi
    S=$(squeue -h -u "$USER" -n judge_gpu -t RUNNING -o %i | head -1)
    if [ -z "$S" ]; then
        squeue -h -u "$USER" -n judge_gpu | grep -q . || { echo "[$(date -Is)] no judge session queued; keeper exits"; exit 0; }
    elif ! srun --jobid="$S" --overlap -n1 --cpus-per-task=1 pgrep -f eval_judge_pools.sh >/dev/null 2>&1; then
        echo "[$(date -Is)] eval not running in session $S; relaunching"
        echo "[$(date -Is)] relaunched by the keeper in session $S" >> "$L"
        setsid nohup srun --jobid="$S" --overlap -n1 --cpus-per-task=14 bash ~/slurm/eval_judge_pools.sh >> "$L" 2>&1 < /dev/null &
    fi
    sleep 300
done

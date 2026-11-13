#!/bin/bash
# Login-node keeper for judge_v2_chain.sh: Babel can cancel the chain step, and a preempted
# judge GPU session requeues on another node. Every 5 minutes, if a judge_gpu session is running
# and the chain is not running inside it (and has neither finished nor stopped on a failure),
# relaunch it there; every stage resumes.
#   setsid nohup bash ~/slurm/keep_v2_chain_alive.sh > ~/joblogs/keep_v2_chain_alive.log 2>&1 < /dev/null &
L=~/joblogs/judge_v2_chain.log
while true; do
    if tail -1 "$L" | grep -qE "\] done$|STOPPED:"; then
        echo "[$(date -Is)] chain finished or stopped itself; keeper exits"; exit 0
    fi
    S=$(squeue -h -u "$USER" -n judge_gpu -t RUNNING -o %i | head -1)
    if [ -z "$S" ]; then
        squeue -h -u "$USER" -n judge_gpu | grep -q . || { echo "[$(date -Is)] no judge session queued; keeper exits"; exit 0; }
    elif ! srun --jobid="$S" --overlap -n1 --cpus-per-task=1 pgrep -f judge_v2_chain.sh >/dev/null 2>&1; then
        echo "[$(date -Is)] chain not running in session $S; relaunching"
        echo "[$(date -Is)] relaunched by the keeper in session $S" >> "$L"
        setsid nohup srun --jobid="$S" --overlap -n1 --cpus-per-task=8 bash ~/slurm/judge_v2_chain.sh >> "$L" 2>&1 < /dev/null &
    fi
    sleep 300
done

#!/bin/bash
# Login-node keeper for judge_overnight.sh: a preempted judge GPU session requeues on another
# node and its steps die with it. Every 5 minutes, if a judge_gpu session is running and the
# chain is not running inside it (and has neither finished nor stopped on a failure),
# relaunch the chain there; every stage of it resumes.
#   setsid nohup bash ~/slurm/keep_chain_alive.sh > ~/joblogs/keep_chain_alive.log 2>&1 < /dev/null &
L=~/joblogs/judge_overnight.log
while true; do
    if grep -qE "\] done$" "$L" || tail -1 "$L" | grep -qE "NOT submitting|failed"; then
        echo "[$(date -Is)] chain finished or stopped itself; keeper exits"; exit 0
    fi
    S=$(squeue -h -u "$USER" -n judge_gpu -t RUNNING -o %i | head -1)
    if [ -z "$S" ]; then
        squeue -h -u "$USER" -n judge_gpu | grep -q . || { echo "[$(date -Is)] no judge session queued; keeper exits"; exit 0; }
    elif ! srun --jobid="$S" --overlap -n1 --cpus-per-task=1 pgrep -f judge_overnight.sh >/dev/null 2>&1; then
        echo "[$(date -Is)] chain not running in session $S; relaunching"
        echo "[$(date -Is)] relaunched by the keeper in session $S" >> "$L"
        setsid nohup srun --jobid="$S" --overlap -n1 --cpus-per-task=12 bash ~/slurm/judge_overnight.sh >> "$L" 2>&1 < /dev/null &
    fi
    sleep 300
done

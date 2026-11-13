#!/bin/bash
# Login-node keeper for judge_v3_chain.sh. It waits until the last complex-question batch is done
# (judge_cplx_chain.sh, TAG=$WAIT_TAG), then every 5 minutes, if a judge_gpu session is running and
# the chain is not running inside it (and has neither finished nor stopped on a failure),
# launches it there; every stage resumes.
#   setsid nohup bash ~/slurm/keep_v3_chain_alive.sh > ~/joblogs/keep_v3_chain_alive.log 2>&1 < /dev/null &
L=~/joblogs/judge_v3_chain.log
W=~/joblogs/judge_cplx_chain_${WAIT_TAG:-v2}.log
until tail -1 "$W" | grep -qE "\] done$"; do
    tail -1 "$W" | grep -q "STOPPED:" && { echo "[$(date -Is)] complex batch stopped; keeper exits"; exit 1; }
    sleep 300
done
echo "[$(date -Is)] complex batch done"
while true; do
    if tail -1 "$L" 2>/dev/null | grep -qE "\] done$|STOPPED:"; then
        echo "[$(date -Is)] chain finished or stopped itself; keeper exits"; exit 0
    fi
    S=$(squeue -h -u "$USER" -n judge_gpu -t RUNNING -o %i | head -1)
    if [ -z "$S" ]; then
        squeue -h -u "$USER" -n judge_gpu | grep -q . || { echo "[$(date -Is)] no judge session queued; keeper exits"; exit 0; }
    elif ! srun --jobid="$S" --overlap -n1 --cpus-per-task=1 pgrep -f judge_v3_chain.sh >/dev/null 2>&1; then
        echo "[$(date -Is)] chain not running in session $S; launching"
        echo "[$(date -Is)] launched by the keeper in session $S" >> "$L"
        setsid nohup srun --jobid="$S" --overlap -n1 --cpus-per-task=8 bash ~/slurm/judge_v3_chain.sh >> "$L" 2>&1 < /dev/null &
    fi
    sleep 300
done

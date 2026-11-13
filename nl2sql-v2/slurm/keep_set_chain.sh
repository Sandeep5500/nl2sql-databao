#!/bin/bash
# Login-node keeper for judge_claude_chain.sh on one batch (any question set): launches it in the
# running judge GPU session and relaunches it in the next one when the session it ran in ends (every
# chain stage resumes). The session counts once judge_gpu_session.slurm has written its endpoint
# file, i.e. vLLM answers. Stops at the chain's "] done" or "STOPPED".
#   DS=<dataset dir> SET=<name> TAG=<batch> IDS=<id file> setsid nohup bash ~/slurm/keep_set_chain.sh \
#       >> ~/joblogs/keep_${SET}_chain_${TAG}.log 2>&1 < /dev/null &
DS=${DS:?}; SET=${SET:?}; TAG=${TAG:?}; IDS=${IDS:?}
CL=~/joblogs/judge_${SET}_chain_$TAG.log
log() { echo "[$(date -Is)] $*"; }
running() { [ -n "$1" ] && [ "$(squeue -h -j "$1" -o %T 2>/dev/null)" = RUNNING ]; }
serving() {  # the judge_gpu session whose vLLM answers
    local j; j=$(sed -n 's/^job=//p' ~/joblogs/judge_gpu_session.txt 2>/dev/null)
    running "$j" && echo "$j"
}
cur=
while true; do
    tail -3 "$CL" 2>/dev/null | grep -qE "\] done$|STOPPED" && { log "chain finished: $(tail -1 "$CL")"; exit 0; }
    if ! running "$cur"; then
        s=$(serving)
        if [ -n "$s" ]; then
            log "launching the chain in session $s"
            DS=$DS SET=$SET TAG=$TAG IDS=$IDS setsid nohup srun --jobid="$s" --overlap -n1 --cpus-per-task=8 \
                --export=ALL bash ~/slurm/judge_claude_chain.sh >> "$CL" 2>&1 < /dev/null &
            cur=$s
        fi
    fi
    sleep 300
done

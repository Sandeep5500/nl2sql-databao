#!/bin/bash
# BEAVER gold results on MySQL (CPU only): the official mysql image under apptainer (9.3.0, the dw
# dump's version; 9.1.0 segfaults on some nested-CTE dw golds), the three dumps
# loaded once (lower_case_table_names=1, as on the macOS servers the dumps came from), then every gold
# query run by scripts/beaver_gold_mysql.py into $B/mysql_gold. The server lives on the node's local
# /scratch (InnoDB and its socket on NFS risk lock errors), so a requeue on another node reloads the
# dumps; the gold run resumes.
#   sbatch ~/slurm/beaver_mysql.slurm
#SBATCH --job-name=beaver_mysql
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=24:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
#SBATCH --output=/home/%u/joblogs/beaver_mysql_%j.out
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
U=/data/user_data/$USER; M=$U/nl2sql-databao; C=$U/judge-code; B=$U/beaver
IMG=$B/mysql-9.3.0.sif; L=/scratch/$USER/beaver_mysql; DATA=$L/data; RUN=$L/run; SOCK=$RUN/mysqld.sock
export APPTAINER_CACHEDIR=$U/.apptainer
log() { echo "[$(date -Is)] $*"; }
die() { log "STOPPED: $*"; exit 1; }
log "node=$(hostname) job=$SLURM_JOB_ID restarts=${SLURM_RESTART_COUNT:-0}"
mkdir -p $RUN
[ -s $IMG ] || apptainer pull $IMG docker://mysql:9.3.0 || die "pull failed"
my() { apptainer exec -B $DATA:/var/lib/mysql -B $RUN:/var/run/mysqld $IMG "$@"; }
OPTS=(--datadir=/var/lib/mysql --socket=/var/run/mysqld/mysqld.sock --pid-file=/var/run/mysqld/mysqld.pid
      --lower-case-table-names=1 --skip-networking --skip-log-bin --innodb-buffer-pool-size=16G
      --innodb-flush-log-at-trx-commit=0 --max-allowed-packet=1G --tmpdir=/var/run/mysqld --secure-file-priv=)
if [ ! -d $DATA/mysql ]; then
    rm -rf $DATA; mkdir -p $DATA
    my mysqld "${OPTS[@]}" --initialize-insecure || die "initialize failed"
fi
MP=
start() {
    rm -f $SOCK $RUN/mysqld.pid
    my mysqld "${OPTS[@]}" >> $RUN/mysqld_$SLURM_JOB_ID.log 2>&1 &
    MP=$!
    for _ in $(seq 1 60); do my mysqladmin --socket=/var/run/mysqld/mysqld.sock -uroot ping >/dev/null 2>&1 && break; sleep 5; done
    my mysqladmin --socket=/var/run/mysqld/mysqld.sock -uroot ping >/dev/null 2>&1 || { tail $RUN/mysqld_$SLURM_JOB_ID.log; die "mysqld not up"; }
    log "mysqld up"
}
trap 'my mysqladmin --socket=/var/run/mysqld/mysqld.sock -uroot shutdown 2>/dev/null; wait $MP' EXIT
start

for db in neutron dw nova; do
    [ -e $L/loaded_$db ] && continue
    log "loading $db"
    my mysql --socket=/var/run/mysqld/mysqld.sock -uroot -e "DROP DATABASE IF EXISTS $db" || die "drop $db"
    my mysql --socket=/var/run/mysqld/mysqld.sock -uroot --max-allowed-packet=1G < $B/dumps/$db.sql \
        || die "loading $db failed"
    touch $L/loaded_$db
    log "loaded $db: $(my mysql --socket=/var/run/mysqld/mysqld.sock -uroot -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$db'") tables"
done

rsync -a ~/judge-code-staging/ $C/ && cd $C/nl2sql-v2 || die "no code"
GOLD=(uv run --project $M/nl2sql-v2 --with pymysql python scripts/beaver_gold_mysql.py
      --questions ~/beaver-staging/beaver-query/data --out $B/mysql_gold --socket $SOCK)
for try in 1 2 3 4 5 6; do  # a crash costs the queries in flight; they rerun after the restart
    "${GOLD[@]}" --workers 12; rc=$?
    [ $rc = 0 ] && break
    [ $rc = 3 ] || die "gold run failed ($rc)"
    log "the server crashed (try $try): $(grep '^Query' $RUN/mysqld_$SLURM_JOB_ID.log | tail -1 | cut -c1-150)"
    kill $MP 2>/dev/null; wait $MP; start
done
[ $rc = 0 ] || { log "still crashing; recording the rest one at a time"; kill $MP 2>/dev/null; wait $MP; start
    "${GOLD[@]}" --workers 1 --record-gone || die "gold run failed"; }
log "done"

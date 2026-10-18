#!/bin/bash
# Control the RPT-G PostgreSQL 19 cluster (unix socket only, port 5439).
# usage: scripts/pg19_ctl.sh init|start|stop|restart|status|psql [DB] [psql args...]
#   init     initdb (if the cluster directory does not exist yet) and write the RPT-G settings
#   start    start the server (runs init first if needed); log: $PGDATA/server.log
#   stop     fast shutdown; only ever touches the postmaster whose data directory is $PGDATA
#   status   pg_ctl status plus the processes of this cluster
#   psql     open psql on DB (default: postgres) through the cluster's socket
# Env: PG19_HOME (install prefix), PG19_DATA (cluster dir), PG19_PORT.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PGHOME=${PG19_HOME:-$ROOT/ext/pg19/install}
PGDATA=${PG19_DATA:-$ROOT/data/pg19/cluster}
PORT=${PG19_PORT:-5439}
BIN=$PGHOME/bin
export LD_LIBRARY_PATH=$PGHOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

write_conf() {
  cat >> "$PGDATA/postgresql.conf" <<EOF

# ---- RPT-G benchmark settings (scripts/pg19_ctl.sh) ----
port = $PORT
listen_addresses = ''                    # unix socket only (shared machine; 5432 belongs to others)
unix_socket_directories = '$PGDATA'
shared_buffers = 8GB
work_mem = 256MB
maintenance_work_mem = 2GB
effective_cache_size = 32GB
max_parallel_workers_per_gather = 7
max_parallel_workers = 8
max_worker_processes = 16
jit = off                                # short queries: JIT compilation would dominate
random_page_cost = 1.1
io_method = sync                         # no I/O worker processes (process budget); data is cached
wal_level = minimal                      # bulk loads into a table created in the same transaction skip WAL
max_wal_senders = 0
max_wal_size = 8GB
logging_collector = off
log_line_prefix = '%m [%p] '
EOF
}

case "$1" in
  init)
    if [ -f "$PGDATA/PG_VERSION" ]; then echo "cluster exists: $PGDATA"; exit 0; fi
    mkdir -p "$PGDATA"
    "$BIN/initdb" -D "$PGDATA" -U "$USER" --auth=trust --encoding=UTF8 --locale=C > "$PGDATA.initdb.log" 2>&1 \
      || { cat "$PGDATA.initdb.log"; exit 1; }
    mv "$PGDATA.initdb.log" "$PGDATA/initdb.log"
    write_conf
    echo "initialized $PGDATA"
    ;;
  start)
    [ -f "$PGDATA/PG_VERSION" ] || "$0" init
    "$BIN/pg_ctl" -D "$PGDATA" -l "$PGDATA/server.log" -w -t 120 start
    ;;
  stop)
    "$BIN/pg_ctl" -D "$PGDATA" -m fast -w stop
    ;;
  restart)
    "$BIN/pg_ctl" -D "$PGDATA" -l "$PGDATA/server.log" -m fast -w -t 120 restart
    ;;
  status)
    "$BIN/pg_ctl" -D "$PGDATA" status || true
    if [ -f "$PGDATA/postmaster.pid" ]; then
      PID=$(head -1 "$PGDATA/postmaster.pid")
      ps -o pid,etime,rss,cmd --ppid "$PID" -p "$PID" | cut -c1-120
    fi
    ;;
  psql)
    shift; DB=${1:-postgres}; [ $# -gt 0 ] && shift
    exec "$BIN/psql" -h "$PGDATA" -p "$PORT" -d "$DB" "$@"
    ;;
  *)
    echo "usage: $0 init|start|stop|restart|status|psql [DB]"; exit 2
    ;;
esac

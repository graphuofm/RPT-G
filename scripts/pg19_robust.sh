#!/bin/bash
# Join-order robustness in PostgreSQL 19 (2026-09-29): the 100 output-bounded DBLP queries under the random
# connected left-deep orders of the Kùzu run (results/kuzu_dblp_robust.orders.csv), forced with explicit JOINs
# and join_collapse_limit=1 (join methods and inner/outer sides stay free); without / with pg_rptg; 4 shards.
cd $RPTG_ROOT
RUNNER=scripts/run_pg.py KUZU_PY=python scripts/run_kuzu_sharded.sh dblp queries/dblp_robust100b.txt \
  results/pg19_dblp_robust.csv 4 --orders results/kuzu_dblp_robust.orders.csv \
  --configs "PGNO:join_collapse_limit=1,PGR:rptg.enabled=on;join_collapse_limit=1" \
  --reps 3 --warm 1 --timeout 10 > results/pg19_dblp_robust.log 2>&1

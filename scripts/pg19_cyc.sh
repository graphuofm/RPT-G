#!/bin/bash
# Cyclic patterns in PostgreSQL 19 with / without pg_rptg (2026-09-29): 1,000 cyclic DBLP Q-GEN queries, the
# host's own plans, 1 warm-up + 3 reps, 10 s; 2 shards.
cd $RPTG_ROOT
RUNNER=scripts/run_pg.py KUZU_PY=python scripts/run_kuzu_sharded.sh dblp queries/qgen_dblp_cyc.txt \
  results/pg19_dblp_cyc.csv 2 --configs "PGNO:,PGR:rptg.enabled=on" --reps 3 --warm 1 --timeout 10 > results/pg19_dblp_cyc.log 2>&1

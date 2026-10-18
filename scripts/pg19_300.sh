#!/bin/bash
# PostgreSQL 19 with and without pg_rptg on the 300-query DBLP sample (2026-09-29): default parallel plans
# (PGNO / PGR) and single-threaded plans (PG1 / PGR1), interleaved per query, 1 warm-up + 3 reps, 10 s.
# V has btree indexes on pu, pd and label (both configurations profit from them).
cd $RPTG_ROOT
RUNNER=scripts/run_pg.py KUZU_PY=python scripts/run_kuzu_sharded.sh dblp queries/qgen_dblp_300.txt \
  results/pg19_rptg_dblp300.csv 2 \
  --configs "PGNO:,PGR:rptg.enabled=on,PG1:max_parallel_workers_per_gather=0,PGR1:rptg.enabled=on;max_parallel_workers_per_gather=0" \
  --reps 3 --warm 1 --timeout 10 > results/pg19_rptg_dblp300.log 2>&1

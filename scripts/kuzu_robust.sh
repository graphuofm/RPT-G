#!/bin/bash
# Join-order robustness inside Kùzu 0.11.3 (plan §8.4, 2026-09-29): the 100 output-bounded robustness queries,
# each under up to 50 distinct random connected left-deep orders forced with HINT join trees (all orders when
# a query has fewer), no mask / Kùzu semi-mask / RPT-G interleaved per (query, order), median of 3 reps.
# usage: scripts/kuzu_robust.sh dblp|lj
G=$1
cd $RPTG_ROOT
Q=queries/dblp_robust100b.txt; [ "$G" = lj ] && Q=queries/lj_robust100.txt
export PYTHONPATH=ext/kuzu/tools/python_api/build KUZU_PY=python
scripts/run_kuzu_sharded.sh data/kuzu/$G.kz $Q results/kuzu_${G}_robust.csv 2 \
  --configs KNO:0:0,KSM:1:0,KR2:0:2:1.0 --random-orders 50 --order-seed 1 \
  --reps 3 --warm 1 --threads 8 --timeout 10 --buffer-gb 16 > results/kuzu_${G}_robust.log 2>&1
cat results/shards_kuzu_${G}_robust/q_*.csv.orders > results/kuzu_${G}_robust.orders.csv

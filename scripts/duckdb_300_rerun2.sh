#!/bin/bash
# Three fork configurations back-to-back on the 300-query DBLP sample, after the ExpressionFilter
# selectivity fix (2026-09-22). The earlier runs are kept as results/duckdb300_*_run1.csv
# (rptg_run1 = decisions made with the 20% default for CAST-wrapped predicates).
cd $RPTG_ROOT
for c in "rptg 1 1.0" "rptplus 0 1.0" "fork 1 0"; do
  set -- $c
  RPTG_MODE=$2 RPTG_BETA=$3 python scripts/run_duckdb_cli.py --bin ext/rptplus/build/release/duckdb \
    --graph data/bin/dblp --db data/bin/dblp/dblp_rptplus.db --queries queries/qgen_dblp_300.txt \
    --out results/duckdb300_$1.csv --reps 3 --warm 1 --method $1 --threads 8 --timeout 10 > results/duckdb300_$1.log 2>&1
done
echo "rerun2 done"

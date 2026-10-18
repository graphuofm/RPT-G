#!/bin/bash
# Join-order robustness in DuckDB (2026-09-29): the 100 output-bounded DBLP queries under the random connected
# left-deep orders of the Kùzu run (results/kuzu_dblp_robust.orders.csv), forced with explicit JOINs and the
# join-order optimizer disabled; our build without (dk0) and with (dkr) RPT-G; 2 shards of 50 queries.
cd $RPTG_ROOT
R=ext/duckdb_rptg/build/release/duckdb; D=data/bin/dblp/dblp_130.db; O=results/kuzu_dblp_robust.orders.csv
DIR=results/shards_duckdb_dblp_robust; mkdir -p $DIR
grep -v "^#" queries/dblp_robust100b.txt | grep -v "^$" > $DIR/all.txt; split -n l/2 -d $DIR/all.txt $DIR/q_
for f in $DIR/q_00 $DIR/q_01; do
  python scripts/run_duckdb_cli.py --graph data/bin/dblp --queries $f --orders $O \
    --configs dk0:$R:$D:0:0.1,dkr:$R:$D:1:0.1 --out $f.csv --reps 3 --warm 1 --threads 8 --timeout 10 > $f.log 2>&1 &
done
wait
head -1 $DIR/q_00.csv > results/duckdb_dblp_robust.csv; for f in $DIR/q_0?.csv; do tail -n +2 $f >> results/duckdb_dblp_robust.csv; done
echo "merged -> results/duckdb_dblp_robust.csv" > results/duckdb_dblp_robust.log

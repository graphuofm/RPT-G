#!/bin/bash
# Cyclic patterns in DuckDB with / without RPT-G (2026-09-29): 1,000 cyclic DBLP Q-GEN queries under DuckDB's
# own join order, our build RPTG_MODE=0 / 1 (beta 0.1), 1 warm-up + 3 reps, 8 threads, 10 s; 2 shards.
cd $RPTG_ROOT
R=ext/duckdb_rptg/build/release/duckdb; D=data/bin/dblp/dblp_130.db
DIR=results/shards_duckdb_dblp_cyc; mkdir -p $DIR
grep -v "^#" queries/qgen_dblp_cyc.txt | grep -v "^$" > $DIR/all.txt; split -n l/2 -d $DIR/all.txt $DIR/q_
for f in $DIR/q_00 $DIR/q_01; do
  python scripts/run_duckdb_cli.py --graph data/bin/dblp --queries $f \
    --configs dk0:$R:$D:0:0.1,dkr:$R:$D:1:0.1 --out $f.csv --reps 3 --warm 1 --threads 8 --timeout 10 > $f.log 2>&1 &
done
wait
head -1 $DIR/q_00.csv > results/duckdb_dblp_cyc.csv; for f in $DIR/q_0?.csv; do tail -n +2 $f >> results/duckdb_dblp_cyc.csv; done
echo "merged -> results/duckdb_dblp_cyc.csv" > results/duckdb_dblp_cyc.log

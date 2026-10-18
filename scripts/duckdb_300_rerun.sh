#!/bin/bash
cd $RPTG_ROOT
RPTG_MODE=1 RPTG_BETA=1.0 python scripts/run_duckdb_cli.py --bin ext/rptplus/build/release/duckdb --graph data/bin/dblp --db data/bin/dblp/dblp_rptplus.db --queries queries/qgen_dblp_300.txt --out results/duckdb300_rptg.csv --reps 3 --warm 1 --method rptg --threads 8 --timeout 10 > results/duckdb300_rptg.log 2>&1
RPTG_MODE=1 RPTG_BETA=0 python scripts/run_duckdb_cli.py --bin ext/rptplus/build/release/duckdb --graph data/bin/dblp --db data/bin/dblp/dblp_rptplus.db --queries queries/qgen_dblp_300.txt --out results/duckdb300_fork.csv --reps 3 --warm 1 --method fork --threads 8 --timeout 10 > results/duckdb300_fork.log 2>&1
echo "rerun done"

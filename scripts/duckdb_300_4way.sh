#!/bin/bash
# Four DuckDB configurations interleaved per query on the 300-query DBLP sample (2026-09-22):
# vanilla 1.3.0 CLI, RPT+ fork as-is, fork with every filter dropped, fork with RPT-G pruning.
# Interleaving replaces the earlier one-configuration-per-pass runs, whose configurations saw very
# different machine loads (results/duckdb300_*_run1.csv, *_run2drift.csv).
cd $RPTG_ROOT
F=ext/rptplus/build/release/duckdb; D=data/bin/dblp/dblp_rptplus.db
python scripts/run_duckdb_cli.py --graph data/bin/dblp --queries queries/qgen_dblp_300.txt \
  --configs vanilla:ext/duckdb130/duckdb:data/bin/dblp/dblp_130.db:0:1.0,rptplus:$F:$D:0:1.0,fork:$F:$D:1:0,rptg:$F:$D:1:1.0 \
  --out results/duckdb300_4way.csv --reps 3 --warm 1 --threads 8 --timeout 10 > results/duckdb300_4way.log 2>&1
echo "4way done" >> results/duckdb300_4way.log

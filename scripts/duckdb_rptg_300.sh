#!/bin/bash
# Vanilla DuckDB 1.3.0 with and without the RPT-G pass (ext/duckdb_rptg, 2026-09-29) on the 300-query DBLP
# sample: official 1.3.0 CLI (reference), our build with RPTG_MODE=0 (baseline: same binary), our build with
# RPT-G; interleaved per query, 1 warm-up + 3 reps in the same process, 8 threads, 10 s, read-only database.
cd $RPTG_ROOT
R=ext/duckdb_rptg/build/release/duckdb; V=ext/duckdb130/duckdb; D=data/bin/dblp/dblp_130.db
python scripts/run_duckdb_cli.py --graph data/bin/dblp --queries queries/qgen_dblp_300.txt \
  --configs vanilla:$V:$D:0:0.1,dk0:$R:$D:0:0.1,dkr:$R:$D:1:0.1 \
  --out results/duckdb_rptg_dblp300.csv --reps 3 --warm 1 --threads 8 --timeout 10 > results/duckdb_rptg_dblp300.log 2>&1
echo done >> results/duckdb_rptg_dblp300.log

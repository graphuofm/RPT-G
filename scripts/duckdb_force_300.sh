#!/bin/bash
# Headroom diagnosis in DuckDB (2026-09-29): the 300-query DBLP sample with RPT-G disabled (dk0), with the
# calibrated pre-screen (dkr), and with every useful transfer forced (dkf, beta 1e6, no fixed or predicate
# cost, scripts/duckdb_force_wrap.sh); interleaved per query, 1 warm-up + 3 reps, 8 threads, 10 s.
cd $RPTG_ROOT
R=ext/duckdb_rptg/build/release/duckdb; W=scripts/duckdb_force_wrap.sh; D=data/bin/dblp/dblp_130.db
python scripts/run_duckdb_cli.py --graph data/bin/dblp --queries queries/qgen_dblp_300.txt \
  --configs dk0:$R:$D:0:0.1,dkr:$R:$D:1:0.1,dkf:$W:$D:1:1e6 \
  --out results/duckdb_force_dblp300.csv --reps 3 --warm 1 --threads 8 --timeout 10 > results/duckdb_force_dblp300.log 2>&1
echo done >> results/duckdb_force_dblp300.log

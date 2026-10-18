#!/bin/bash
# RPT-G against RPT+ in DuckDB (2026-10-15, added after review): six configurations interleaved
# per query on the 300-query DBLP sample, 1 warm-up + 3 reps, 8 threads, 10 s, 3 shards of 100 queries.
#   vanilla  official DuckDB 1.3.0 CLI, no transfer
#   rptplus  RPT+ fork (embryo-labs/dynamic-predicate-transfer on DuckDB 1.3.0), RPT+ as-is (RPTG_MODE=0)
#   fork     the same fork with every filter plan dropped (RPTG_MODE=1, RPTG_BETA=0): the fork's own baseline
#   dk0      our vanilla-1.3.0 build with RPT-G off (RPTG_MODE=0): RPT-G's own baseline
#   rptg     RPT-G transfers only (RPTG_MODE=1, RPTG_BETA=0.1, RPTG_COUNT=0)
#   rptgc    RPT-G transfers + counting shortcut (RPTG_COUNT=1)
cd $RPTG_ROOT
F=ext/rptplus/build/release/duckdb; FD=data/bin/dblp/dblp_rptplus.db
R=ext/duckdb_rptg/build/release/duckdb; D=data/bin/dblp/dblp_130.db
V=ext/duckdb130/duckdb
OUT=results/duckdb300_rptplus; S=results/shards_duckdb300_rptplus
mkdir -p $S; grep -v '^#' queries/qgen_dblp_300.txt | grep . | split -l 100 -d - $S/q_
for f in $S/q_0?; do
  python scripts/run_duckdb_cli.py --graph data/bin/dblp --queries $f \
    --configs vanilla:$V:$D:0:1.0,rptplus:$F:$FD:0:1.0,fork:$F:$FD:1:0,dk0:$R:$D:0:0.1,rptg:$R:$D:1:0.1:RPTG_COUNT=0,rptgc:$R:$D:1:0.1:RPTG_COUNT=1 \
    --out $f.csv --reps 3 --warm 1 --threads 8 --timeout 10 > $f.log 2>&1 &
done
wait
head -1 $S/q_00.csv > $OUT.csv; for f in $S/q_0?.csv; do tail -n +2 $f >> $OUT.csv; done
echo "merged $(($(wc -l < $OUT.csv) - 1)) rows -> $OUT.csv" > $OUT.log; echo done >> $OUT.log

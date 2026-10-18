#!/bin/bash
# Kùzu 0.11.3 with the counting shortcut (host core v4, 2026-10-14) on the 300-query DBLP sample: no mask (KNO),
# RPT-G transfers only (KR2, rptg_count=false), RPT-G transfers + counting (KRC); interleaved per query,
# 1 warm-up + 3 reps, 8 threads, 10 s, 2 shards. Same sample and protocol as the PostgreSQL and DuckDB counting runs.
cd $RPTG_ROOT
export PYTHONPATH=ext/kuzu/tools/python_api/build KUZU_PY=python
scripts/run_kuzu_sharded.sh data/kuzu/dblp.kz queries/qgen_dblp_300.txt results/kuzu_count_dblp300.csv 2 \
  --configs KNO:0:0,KR2:0:2:1.0:rptg_count=false,KRC:0:2:1.0:rptg_count=true \
  --reps 3 --warm 1 --threads 8 --timeout 10 --buffer-gb 16 > results/kuzu_count_dblp300.log 2>&1
echo done >> results/kuzu_count_dblp300.log

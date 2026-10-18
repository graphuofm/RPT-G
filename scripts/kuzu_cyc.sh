#!/bin/bash
# Cyclic patterns in Kùzu 0.11.3 (2026-09-29): 1,000 cyclic Q-GEN queries, no mask / Kùzu semi-mask / RPT-G
# (cyclic support: spanning tree + closing edges, provenance on bridges only), median of 3 interleaved reps.
# usage: scripts/kuzu_cyc.sh dblp|lj
G=$1
cd $RPTG_ROOT
export PYTHONPATH=ext/kuzu/tools/python_api/build KUZU_PY=python
scripts/run_kuzu_sharded.sh data/kuzu/$G.kz queries/qgen_${G}_cyc.txt results/kuzu_${G}_cyc.csv 2 \
  --configs KNO:0:0,KSM:1:0,KR2:0:2:1.0 --reps 3 --warm 1 --threads 8 --timeout 10 --buffer-gb 16 > results/kuzu_${G}_cyc.log 2>&1

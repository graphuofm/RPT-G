#!/bin/bash
# LadybugDB, 300-query DBLP sample (2026-09-29): no mask / Ladybug semi-mask / RPT-G with masks on node
# scans only (stage E) / RPT-G with neighbour masks on the main plan's EXTENDs too (stage F), interleaved
# per query in one build (setting rptg_nbr_mask). The build also admits no worker threads to a skipped
# transfer and one thread per 16K adjacency entries to an executed one (Sink::participate).
cd $RPTG_ROOT
export PYTHONPATH=ext/ladybug/tools/python_api/build KUZU_PY=python RUNNER=scripts/run_ladybug.py
scripts/run_kuzu_sharded.sh data/ladybug/dblp.lb queries/qgen_dblp_300.txt results/ladybug_dblp300_f.csv 2 \
  --configs LNO:0:0,LSM:1:0,LR2E:0:2:1.0:rptg_nbr_mask=false,LR2:0:2:1.0:rptg_nbr_mask=true \
  --reps 3 --warm 1 --threads 8 --timeout 10 --buffer-gb 8 > results/ladybug_dblp300_f.log 2>&1

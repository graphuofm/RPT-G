#!/bin/bash
# LSQB-P on Kùzu (2026-09-29): 8 parameterized LSQB templates x 20 random entities (queries/lsqb_p_sf1_160.txt,
# scripts/lsqb_params.py), SF1; no mask / Kùzu semi-mask / RPT-G, 1 warm-up + 3 interleaved reps, 60 s timeout.
cd $RPTG_ROOT
SUF=${1:+_$1}   # optional run suffix, e.g. "intersect" for the rerun with INTERSECT support
export PYTHONPATH=ext/kuzu/tools/python_api/build KUZU_PY=python
scripts/run_kuzu_sharded.sh data/kuzu/lsqb_sf1.kz queries/lsqb_p_sf1_160.txt results/kuzu_lsqbp_sf1${SUF}.csv 2 \
  --configs KNO:0:0,KSM:1:0,KR2:0:2:1.0 --reps 3 --warm 1 --threads 8 --timeout 60 --buffer-gb 12 > results/kuzu_lsqbp_sf1${SUF}.log 2>&1

#!/bin/bash
# LiveJournal tree workload with the final prototype (v8), on the 3,893 queries whose baseline finished in the
# v5 run (queries/qgen_lj_ok.txt; the other 1,107 are excluded from every speedup anyway); no transfer, static
# semi-mask, Yannakakis bitmap, RPT-G; 1 warm-up + 3 interleaved reps, 10 s (2026-09-30).
cd $RPTG_ROOT
RPTG_BIN=prototype/bin/rptg_v8 scripts/run_sharded.sh data/bin/lj queries/qgen_lj_ok.txt results/lj_qgen_v8.csv 6 \
  --methods M0,M3,M4,M6 --reps 3 --warm 1 --timeout 10 > results/lj_qgen_v8.log 2>&1

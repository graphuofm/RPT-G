#!/bin/bash
# v24 (2026-10-06): the v18c protocol with the audited benefit model: degree-weighted survival (--deg-surv 1, histograms
# without random degree reads at init), cap over the levels after the entering one, skip_unit 24, beta 0.25 (a transfer
# entry costs ~5x a join entry on LJ-size bitmaps), counting benefit only when counting is plausible (--count-benefit 1).
# usage: scripts/final_run_v24.sh dblp|lj NSHARDS
G=$1; N=${2:-6}
cd $RPTG_ROOT
RPTG_BIN=prototype/bin/rptg_v24 scripts/run_sharded.sh data/bin/$G queries/qgen_${G}_1k.txt results/final24_${G}1k_main.csv $N \
  --methods M0,M6,M7,M8 --reps 3 --warm 1 --timeout 10 --col-index 1 --min-work 20000 --word-cost 0.3 \
  --extrapolate 1 --cascade 1 --count-far 8 --warm-each 1 --deg-surv 1 --count-benefit 1 --beta 0.25 > results/final24_${G}1k_main.log 2>&1

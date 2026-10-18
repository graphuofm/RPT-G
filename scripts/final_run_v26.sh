#!/bin/bash
# v26 (2026-10-06): v25 with budgeted transfers before an upfront counting decision (M8: the transfers run under the
# counting benefit alone, then the counting pass sees reduced sets). Protocol as v18c: per-method warm runs; three
# process groups: main = M0,M6,M7,M8; base = M0,M3,M4 (unchanged code paths, results/final25_*_base.csv);
# notransfer = M0,C0 (the counting join with the ski rental and no transfer phase, for the contribution of the transfers).
# usage: scripts/final_run_v26.sh dblp|lj NSHARDS main|base|notransfer
G=$1; N=${2:-6}; GRP=${3:-main}
case $GRP in main) M=M0,M6,M7,M8;; base) M=M0,M3,M4;; notransfer) M=M0,C0;; esac
cd $RPTG_ROOT
RPTG_BIN=prototype/bin/rptg_v26 scripts/run_sharded.sh data/bin/$G queries/qgen_${G}_1k.txt results/final26_${G}1k_$GRP.csv $N \
  --methods $M --reps 3 --warm 1 --timeout 10 --col-index 1 --min-work 20000 --word-cost 0.3 \
  --extrapolate 1 --cascade 1 --count-far 8 --warm-each 1 --deg-surv 1 --count-benefit 1 --beta 0.25 --beta-count 1 \
  > results/final26_${G}1k_$GRP.log 2>&1

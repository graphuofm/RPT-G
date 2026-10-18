#!/bin/bash
# v25 (2026-10-06): the v24 model with the counting benefit at its own unit (--beta-count 1: a counting entry costs
# about a transfer entry, so it is not scaled by beta 0.25). Protocol as v18c: per-method warm runs; main group
# M0,M6,M7,M8 and the M3/M4 base group in separate process groups

# usage: scripts/final_run_v25.sh dblp|lj NSHARDS main|base
G=$1; N=${2:-6}; GRP=${3:-main}
case $GRP in main) M=M0,M6,M7,M8; B=0.25;; base) M=M0,M3,M4; B=0.25;; esac
cd $RPTG_ROOT
RPTG_BIN=prototype/bin/rptg_v25 scripts/run_sharded.sh data/bin/$G queries/qgen_${G}_1k.txt results/final25_${G}1k_$GRP.csv $N \
  --methods $M --reps 3 --warm 1 --timeout 10 --col-index 1 --min-work 20000 --word-cost 0.3 \
  --extrapolate 1 --cascade 1 --count-far 8 --warm-each 1 --deg-surv 1 --count-benefit 1 --beta $B --beta-count 1 \
  > results/final25_${G}1k_$GRP.log 2>&1

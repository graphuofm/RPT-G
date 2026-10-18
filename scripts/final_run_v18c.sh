#!/bin/bash
# Final prototype protocol (v18c, 2026-10-06): column indexes, tiny-query guard, cost-based edge scans, cascade
# scans, M8 upfront counting; every measured run preceded by a run of the same method (--warm-each 1); join work
# split into scanned entries (join_work) and counted output (join_out). The full-reduction baselines run in a
# separate process group: M4's allocation churn widens the timing noise of every later method in the same process
# (same 92 LJ queries: M6 < 0.9x 7.6% without M4 present, 19.6% with it, identical sums).
# usage: scripts/final_run_v18c.sh dblp|lj NSHARDS main|base     (main = M0,M6,M7,M8; base = M0,M3,M4)
G=$1; N=${2:-6}; GRP=${3:-main}
case $GRP in main) M=M0,M6,M7,M8;; base) M=M0,M3,M4;; esac
cd $RPTG_ROOT
RPTG_BIN=prototype/bin/rptg_v18c scripts/run_sharded.sh data/bin/$G queries/qgen_${G}_1k.txt results/final18c_${G}1k_$GRP.csv $N \
  --methods $M --reps 3 --warm 1 --timeout 10 --col-index 1 --min-work 20000 --word-cost 0.3 \
  --extrapolate 1 --cascade 1 --count-far 8 --warm-each 1 > results/final18c_${G}1k_$GRP.log 2>&1

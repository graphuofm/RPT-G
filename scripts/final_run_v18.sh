#!/bin/bash
# Final prototype configuration (v18, 2026-10-05): column indexes, tiny-query guard, cost-based edge scans,
# cascade scans, M8 upfront counting; join work split into scanned entries (join_work) and counted output (join_out).
# usage: scripts/final_run_v18.sh dblp|lj NSHARDS
G=$1; N=${2:-6}
cd $RPTG_ROOT
RPTG_BIN=prototype/bin/rptg_v18 scripts/run_sharded.sh data/bin/$G queries/qgen_${G}_1k.txt results/final18_${G}1k.csv $N \
  --methods M0,M3,M4,M6,M7,M8 --reps 3 --warm 1 --timeout 10 --col-index 1 --min-work 20000 --word-cost 0.3 \
  --extrapolate 1 --cascade 1 --count-far 8 > results/final18_${G}1k.log 2>&1

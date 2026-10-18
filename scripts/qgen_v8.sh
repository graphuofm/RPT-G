#!/bin/bash
# Q-GEN tree workloads with the final prototype (v8: online filtered adjacency, host-free M6) and arc
# consistency (M5) as an extra graph-side baseline (2026-09-29). usage: scripts/qgen_v8.sh dblp|lj NSHARDS
G=$1; N=${2:-6}
cd $RPTG_ROOT
RPTG_BIN=prototype/bin/rptg_v8 scripts/run_sharded.sh data/bin/$G queries/qgen_${G}.txt results/${G}_qgen_v8.csv $N \
  --methods M0,M3,M4,M5,M6 --reps 3 --warm 1 --timeout 10 > results/${G}_qgen_v8.log 2>&1

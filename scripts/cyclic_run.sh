#!/bin/bash
# Cyclic patterns (2026-09-29): 1,000 cyclic Q-GEN queries, M0 (worst-case-optimal-style join, no transfer),
# M3 static semi-mask, M4 Yannakakis on a spanning tree, M5 arc consistency, M6 RPT-G; 3 interleaved reps.
# usage: scripts/cyclic_run.sh dblp|lj NSHARDS [exact|est]   (join order from exact sizes or from a
# constant 10% selectivity per predicate, as a host optimizer without column statistics would build it)
G=$1; N=${2:-4}; O=${3:-exact}
cd $RPTG_ROOT
SUF=""; [ "$O" = est ] && SUF="_est"
RPTG_BIN=prototype/bin/rptg_v8 scripts/run_sharded.sh data/bin/$G queries/qgen_${G}_cyc.txt results/cyc_${G}${SUF}.csv $N \
  --methods M0,M3,M4,M5,M6 --reps 3 --warm 1 --timeout 10 --order $O > results/cyc_${G}${SUF}.log 2>&1

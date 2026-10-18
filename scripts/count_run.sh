#!/bin/bash
# Counting join (prototype v9, 2026-10-01): M0 no transfer, M6 RPT-G, C0 counting switch without transfers, M7 RPT-G +
# counting switch (ski rental: enumerate until the work reaches the exact cost of counting over the spanning tree).
# usage: scripts/count_run.sh dblp|lj NSHARDS
G=$1; N=${2:-6}
cd $RPTG_ROOT
RPTG_BIN=prototype/bin/rptg_v9 scripts/run_sharded.sh data/bin/$G queries/qgen_${G}_1k.txt results/count_${G}1k.csv $N \
  --methods M0,M6,C0,M7 --reps 3 --warm 1 --timeout 10 > results/count_${G}1k.log 2>&1

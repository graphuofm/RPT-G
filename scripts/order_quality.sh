#!/bin/bash
# Headroom vs optimizer quality (2026-09-29): the same 1,000-query sample under the exact-size greedy order
# and under a host-like order built from a constant 10% selectivity per predicate; M0/M4/M6, 3 reps.
# usage: scripts/order_quality.sh dblp|lj NSHARDS
G=$1; N=${2:-4}
cd $RPTG_ROOT
export RPTG_BIN=prototype/bin/rptg_v8
for O in exact est; do
  scripts/run_sharded.sh data/bin/$G queries/qgen_${G}_1k.txt results/order_${O}_${G}1k.csv $N \
    --methods M0,M4,M6 --reps 3 --warm 1 --timeout 10 --order $O > results/order_${O}_${G}1k.log 2>&1 &
done
wait

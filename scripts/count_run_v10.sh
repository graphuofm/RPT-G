#!/bin/bash
# v10 (2026-10-01): counting join with a planned/ski-rental switch, predicate column indexes for every method
# (also the baseline), tiny-query guard (estimated join < 20K entries: no transfer phase).
# usage: scripts/count_run_v10.sh dblp|lj NSHARDS
G=$1; N=${2:-6}
cd $RPTG_ROOT
RPTG_BIN=prototype/bin/rptg_v10 scripts/run_sharded.sh data/bin/$G queries/qgen_${G}_1k.txt results/count10_${G}1k.csv $N \
  --methods M0,M6,C0,M7 --reps 3 --warm 1 --timeout 10 --col-index 1 --min-work 20000 > results/count10_${G}1k.log 2>&1

#!/bin/bash
# v20 (2026-10-06): v19 + counting benefit (--count-benefit 1: a transfer is also valued by the counting cost it removes); v19: the v18c protocol with degree-weighted survival in the benefit model (--deg-surv 1): per-set
# log2-degree histograms; a transfer is valued by the share of the target's degree sum it removes, so that hubs,
# which survive any transfer and carry most of the edges the join scans, are not counted as removed.
# usage: scripts/final_run_v19.sh dblp|lj NSHARDS
G=$1; N=${2:-6}
cd $RPTG_ROOT
RPTG_BIN=prototype/bin/rptg_v20 scripts/run_sharded.sh data/bin/$G queries/qgen_${G}_1k.txt results/final20_${G}1k_main.csv $N \
  --methods M0,M6,M7,M8 --reps 3 --warm 1 --timeout 10 --col-index 1 --min-work 20000 --word-cost 0.3 \
  --extrapolate 1 --cascade 1 --count-far 8 --warm-each 1 --deg-surv 1 --count-benefit 1 > results/final20_${G}1k_main.log 2>&1

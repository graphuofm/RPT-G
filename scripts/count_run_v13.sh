#!/bin/bash
# v13 (2026-10-01): v11 + cost-based plan-time edge scans (saved scans vs build price incl. bitmap words) and an
# online edge-scan rule that extrapolates the rest of the level from the outer loop's progress, discounts the
# observed hit rate, and requires each source vertex to be visited once on average. Pure ski-rental counting switch.
# usage: scripts/count_run_v13.sh dblp|lj NSHARDS
G=$1; N=${2:-6}
cd $RPTG_ROOT
RPTG_BIN=prototype/bin/rptg_v13 scripts/run_sharded.sh data/bin/$G queries/qgen_${G}_1k.txt results/count13_${G}1k.csv $N \
  --methods M0,M6,C0,M7 --reps 3 --warm 1 --timeout 10 --col-index 1 --min-work 20000 --word-cost 0.3 --extrapolate 1 \
  --count-far 0 > results/count13_${G}1k.log 2>&1

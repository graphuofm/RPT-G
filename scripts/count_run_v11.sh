#!/bin/bash
# v11 (2026-10-01): v10 + incremental push statistics + bitmap fixed cost in the budget (--word-cost 0.3).
# usage: scripts/count_run_v11.sh dblp|lj NSHARDS COUNT_FAR   (COUNT_FAR 0 = pure ski rental, 8 = predicted switch)
G=$1; N=${2:-6}; F=${3:-8}
cd $RPTG_ROOT
RPTG_BIN=prototype/bin/rptg_v11 scripts/run_sharded.sh data/bin/$G queries/qgen_${G}_1k.txt results/count11_${G}1k_f${F}.csv $N \
  --methods M0,M6,C0,M7 --reps 3 --warm 1 --timeout 10 --col-index 1 --min-work 20000 --word-cost 0.3 --count-far $F \
  > results/count11_${G}1k_f${F}.log 2>&1

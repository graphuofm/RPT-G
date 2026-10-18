#!/bin/bash
cd $RPTG_ROOT
for b in 0 0.25 0.5 2 4; do
  RPTG_BIN=prototype/bin/rptg_v4 scripts/run_sharded.sh data/bin/lj queries/qgen_lj_1k.txt results/sweep_beta_lj_$b.csv 10 --reps 3 --warm 1 --timeout 10 --methods M0,M6 --beta $b > results/sweep_beta_lj_$b.log 2>&1
done
echo "sweep done"

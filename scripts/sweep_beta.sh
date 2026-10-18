#!/bin/bash
# beta sensitivity sweep on the 1k DBLP subsample: M0 + M6 per beta value, 10 shards each, sequential
cd $RPTG_ROOT
for b in 0 0.25 0.5 1 2 4; do
  RPTG_BIN=prototype/bin/rptg_v4 scripts/run_sharded.sh data/bin/dblp queries/qgen_dblp_1k.txt results/sweep_beta_$b.csv 10 --reps 3 --warm 1 --timeout 10 --methods M0,M6 --beta $b > results/sweep_beta_$b.log 2>&1
done
echo "sweep done"

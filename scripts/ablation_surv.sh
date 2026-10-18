#!/bin/bash
# M6 exact accumulators vs sequential 1,000-sample estimates, survival from degree sums, on the 1k subsamples
cd $RPTG_ROOT
for g in dblp lj; do
  RPTG_BIN=prototype/bin/rptg_v5d scripts/run_sharded.sh data/bin/$g queries/qgen_${g}_1k.txt results/abl_${g}1k_exact.csv 8 --reps 3 --warm 1 --timeout 10 --methods M0,M6 > results/abl_${g}1k_exact.log 2>&1
  RPTG_BIN=prototype/bin/rptg_v5d scripts/run_sharded.sh data/bin/$g queries/qgen_${g}_1k.txt results/abl_${g}1k_acc.csv 8 --reps 3 --warm 1 --timeout 10 --methods M0,M6 --est-sample 1000 --est-mode 1 > results/abl_${g}1k_acc.log 2>&1
done
echo "ablation done"

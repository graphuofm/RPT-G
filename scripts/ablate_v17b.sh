#!/bin/bash
# Ablation of the RPT+-style mechanisms in the graph prototype (v17, 2026-10-05), one configuration per call:
#   A  base (v15 behaviour)                      B  + cascade scans (coarse-to-fine membership tests)
#   C  B + push abort + reach-weighted pilot     D  C + most-selective-sibling-first transfer order
# methods: M0 no transfer, M6 RPT-G, M7 RPT-G + ski-rental counting, M8 RPT-G + upfront counting decision
# usage: scripts/ablate_v17.sh dblp|lj NSHARDS A|B|C|D
G=$1; N=${2:-6}; CFG=$3
case $CFG in
  A) F="--cascade 0 --push-abort 0 --reach-pilot 0 --sibling-order 0";;
  B) F="--cascade 1 --push-abort 0 --reach-pilot 0 --sibling-order 0";;
  C) F="--cascade 1 --push-abort 1 --reach-pilot 1 --sibling-order 0";;
  D) F="--cascade 1 --push-abort 1 --reach-pilot 1 --sibling-order 1";;
esac
cd $RPTG_ROOT
RPTG_BIN=prototype/bin/rptg_v17b scripts/run_sharded.sh data/bin/$G queries/qgen_${G}_1k.txt results/abl17b_${G}1k_$CFG.csv $N \
  --methods M0,M7,M8 --reps 3 --warm 1 --timeout 10 --col-index 1 --min-work 20000 --word-cost 0.3 --extrapolate 1 \
  --count-far 8 $F > results/abl17b_${G}1k_$CFG.log 2>&1

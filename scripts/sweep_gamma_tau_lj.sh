#!/bin/bash
cd $RPTG_ROOT
RPTG_BIN=prototype/bin/rptg_v4 scripts/run_sharded.sh data/bin/lj queries/qgen_lj_1k.txt results/sweep_lj_gamma500.csv 10 --reps 3 --warm 1 --timeout 10 --methods M0,M6 --gamma 500 > results/sweep_lj_gamma500.log 2>&1
RPTG_BIN=prototype/bin/rptg_v4 scripts/run_sharded.sh data/bin/lj queries/qgen_lj_1k.txt results/sweep_lj_gamma10k.csv 10 --reps 3 --warm 1 --timeout 10 --methods M0,M6 --gamma 10000 > results/sweep_lj_gamma10k.log 2>&1
RPTG_BIN=prototype/bin/rptg_v4 scripts/run_sharded.sh data/bin/lj queries/qgen_lj_1k.txt results/sweep_lj_tausel02.csv 10 --reps 3 --warm 1 --timeout 10 --methods M0,M6 --tau-sel 0.2 > results/sweep_lj_tausel02.log 2>&1
RPTG_BIN=prototype/bin/rptg_v4 scripts/run_sharded.sh data/bin/lj queries/qgen_lj_1k.txt results/sweep_lj_tausel05.csv 10 --reps 3 --warm 1 --timeout 10 --methods M0,M6 --tau-sel 0.5 > results/sweep_lj_tausel05.log 2>&1
echo "sweep done"

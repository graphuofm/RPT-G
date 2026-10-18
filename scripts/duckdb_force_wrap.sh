#!/bin/bash
# DuckDB with the RPT-G pass forced to run every useful transfer: no fixed cost, free predicates and filters,
# every predicate materialized exactly (diagnostic: is there headroom that the pre-screen leaves unused?)
export RPTG_FIRST_COST=0 RPTG_PRED_COST=0 RPTG_FILTER_COST=0 RPTG_EXACT_ROWS=1e12
exec $RPTG_ROOT/ext/duckdb_rptg/build/release/duckdb "$@"

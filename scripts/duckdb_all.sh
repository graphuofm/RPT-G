#!/bin/bash
# The DuckDB runs in sequence (RPT-G pass v4, 2026-09-30: host-plan model with per-edge undo, self filters, column indexes,
# empty-result short-circuit).
cd $RPTG_ROOT
scripts/duckdb_robust.sh
scripts/duckdb_rptg_300.sh
scripts/duckdb_cyc.sh

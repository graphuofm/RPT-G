#!/bin/bash
# The PostgreSQL 19 runs in sequence (pg_rptg v3, 2026-09-30: host-plan model with per-edge undo, column
# indexes, self filters, empty-result short-circuit).
cd $RPTG_ROOT
scripts/pg19_robust.sh
scripts/pg19_300.sh
scripts/pg19_cyc.sh

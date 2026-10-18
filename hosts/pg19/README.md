# RPT-G in PostgreSQL 19 (`pg_rptg`)

PostgreSQL 19 beta 4 (`ext/pg19`, REL_19_STABLE, built with `--prefix=ext/pg19/install`). SQL/PGQ (GRAPH_TABLE) was
committed on 2026-03-16 (2f094e7ac6) and reverted on 2026-09-07 (2b9e1aff4d); `ext/pg19_pgq` is 19beta3 with it.
Pattern queries are plain SQL self-joins (`scripts/run_duckdb.py:to_sql`), identical to the DuckDB runs.

## Extension

`hosts/pg19/pg_rptg/` (C glue + the shared core `prototype/src/rptg_c.cpp`):
- planner hook: recognizes E/V self-joins (comma joins and explicit inner JOINs), reads the join tree off the final
  plan, and runs the pre-screen. Vertex predicates of the form `col op const` (op in < <= = >= >, numeric column,
  also conjunctions on one column) are answered by a **column index** (`rptg_colindex` in the core: sorted copy of the
  column with prefix sums of degrees and degree products, built once per backend like the adjacency index; exact
  size / degree sums / second moments by binary search). Other predicates fall back to PostgreSQL's row estimates
  (`create_upper_paths_hook`) and the two-level (optimistic, then SPI-materialized small sets) pre-screen. A query
  without an admitted transfer keeps its plan untouched; otherwise appends `rptg_member(exec, vertex, column)` filters
  to the E/V scans and marks the plan (`PlannedStmt.extension_state`);
- executor-start hook: materializes the needed predicates (column index, else SPI with a bit-setting DestReceiver),
  runs the transfer phase on an adjacency index built once per backend (DBLP: ~0.3-0.5 s), keeps the filters of
  vertices reduced beyond their own predicates or carrying a **self filter** (the predicate's own bitmap on edge scans
  that reach the vertex before the plan applies its predicate), drops those made redundant by a join directly above,
  short-circuits a provably **empty result** (an empty candidate set -> every vertex empty, every filter kept), and
  publishes the bitmaps to `/dev/shm` for parallel workers.

GUCs: `rptg.enabled` (off), `rptg.beta` (10), `rptg.filter_cost` (3), `rptg.pred_cost` (160, SPI path),
`rptg.index_pred_cost` (2), `rptg.first_cost` (150000 = 0.6 ms), `rptg.column_index` (on), `rptg.exact_rows` (20000),
`rptg.edge_table` (e), `rptg.vertex_table` (v), `rptg.debug` (off; decisions in the server log / client with
`client_min_messages=log`), `rptg.trace` (off; host-plan model rows per node to the server log).
Assumes a static vertex/edge table (indexes are not invalidated on updates).

Versions: v1 (exec-time pre-screen), v2 (plan-time pre-screen on PG estimates; runs aborted), v3 (2026-09-30:
per-edge undo in the host model, column indexes, self filters, empty short-circuit). Diagnosis helper:
`scripts/pg_pair.py QID ORDER` (alternates off/on, prints times and decisions).

**Counting shortcut (2026-10-06).** In `rptg_planner`, a bare `SELECT count(*)` over a tree pattern (`is_count_star`:
one `count(*)` target, no grouping, DISTINCT, ORDER BY, LIMIT or FILTER) is answered at plan time by the core's
counting join (`count_plan`): the decision comes first, from the column index's exact sizes and degree sums or the
planner's row estimates (`rptg_count_decide`): count when the counting cost is at most `rptg.count_host` (8) times
the engine's own enumeration estimate (at least 20K entries), or below `rptg.count_floor` (2e6 entries, a few
milliseconds) regardless of that estimate (the estimate can fall two orders of magnitude short on hub
neighbourhoods; DBLP q2825: estimate 2e4, 3.5M matches, counted in 1.5 ms against 400 ms for the host plan). Only
then are the predicate sets materialized (column index or SPI) and counted (`rptg_count`), and the planner returns
the plan of `SELECT <count>::int8` (a `Result` node). `rptg.count = off` disables it. Earlier variants on record:
`pg19_count_dblp300_f8.csv` (materialize first, factor 8: 9.6% < 0.8x from the materialization alone),
`pg19_count_dblp300_f1.csv` (decide first, factor 1, no floor: geo 1.56, 667 -> 314 s). Results:
`results/pg19_count_dblp300.csv` (`PGNO` / `PGR`).

```
make -C hosts/pg19/pg_rptg && make -C hosts/pg19/pg_rptg install
scripts/pg19_ctl.sh start                                   # port 5439, socket in data/pg19/cluster
~/miniconda3/bin/python scripts/pg19_load.py data/bin/dblp dblp
scripts/pg19_ctl.sh psql dblp -c "CREATE EXTENSION pg_rptg" -c "ALTER DATABASE dblp SET session_preload_libraries='pg_rptg'"
~/miniconda3/bin/python scripts/run_pg.py --db dblp --queries queries/test_small.txt --configs "PGNO:,PGR:rptg.enabled=on"
```

Runs: `scripts/pg19_all.sh` (join-order robustness with `--orders` and `join_collapse_limit=1`, the 300-query sample,
cyclic patterns). Notes and findings: `docs/reports/gain_diagnosis.md` (Finding 5, 7), `docs/insights.md` (phase 2).

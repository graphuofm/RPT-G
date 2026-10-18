# RPT-G in DuckDB

**Current integration (v4, 2026-09-30): vanilla DuckDB 1.3.0** (`ext/duckdb_rptg`, tag v1.3.0 +
`rptg_vanilla130.patch`, `third_party/rptg` -> `prototype/src`). An optimizer pass after all built-in optimizers
(`src/optimizer/rptg_optimizer.cpp`) recognizes E/V self-joins and runs the shared core's pre-screen on DuckDB's join
tree. Range/equality predicates on a numeric V column (possibly CAST-widened) use a **column index** built once per
process through a side connection (`SELECT id, col::DOUBLE FROM v`): exact size, degree sums and moments by binary
search, materialization without a side query. Other predicates: zone-map min/max estimates, optimistic level 1,
then small sets (<= `RPTG_EXACT_ROWS`) materialized on the side connection. Admitted transfers run in the core;
`rptg_member` filters (plus the bitmap's min/max as table filters) go above the scans that need them, including
**self filters** (a predicate's own bitmap on the edge scans that reach the vertex before its join); an empty
candidate set gives every scan the empty bitmap (min > max: zone maps skip every row group).
Environment: `RPTG_MODE=1`, `RPTG_BETA` (0.1), `RPTG_FILTER_COST` (0.3), `RPTG_COLUMN_INDEX` (1),
`RPTG_INDEX_FIRST_COST` (100000), `RPTG_INDEX_PRED_COST` (2), non-indexed path: `RPTG_PRED_COST` (15),
`RPTG_FIRST_COST` (500000), `RPTG_EXACT_ROWS` (50000); `RPTG_DEBUG=1`. Build: `cmake --build build/release --target shell`.
Compare against the same binary with `RPTG_MODE=0` (our GCC 9 build is slower than the official one on some queries).
**Counting shortcut (2026-10-06).** A bare `SELECT count(*)` over a tree pattern (projections above one
aggregate without groups whose only aggregate is `count(*)`, and nothing but joins, filters and scans below it) is
answered by the core's counting join: every predicate set is materialized (column index, else one side query), the
transfers run under the counting benefit alone, and one forward pass over the counting semiring (`rptg_count` in
`rptg_c.h`, `Engine::count_host`) gives the number of matches, which replaces the aggregate and the join tree by a
projection of the constant over a one-row scan (`CountShape` / `ReplaceCount`). The decision is made from the
plan-time estimates before any predicate set is materialized (`rptg_count_decide`): count when the counting cost is
at most `RPTG_COUNT_HOST` (8) times the engine's own enumeration estimate (at least 20K entries), or below
`RPTG_COUNT_FLOOR` (2e6 entries, a few milliseconds) regardless of that estimate, because the enumeration
estimate, built from degree sums under independence, can fall two orders of magnitude short on hub neighbourhoods
and a host has no ski rental to catch that. Otherwise the query keeps DuckDB's plan and the transfer path below.
`RPTG_COUNT=0` disables it. Results: `results/duckdb_count_dblp300.csv`
(`dk0` = same binary, `RPTG_MODE=0`; `dkr` = transfers + counting shortcut).

RPT+ comparison (2026-10-15): `scripts/duckdb_300_rptplus.sh` -> `results/duckdb300_rptplus.csv` (official CLI,
RPT+ fork as-is / filters dropped, our build off / RPT-G / RPT-G + counting, interleaved; `run_duckdb_cli.py` now
takes extra `VAR=value` fields per configuration, e.g. `RPTG_COUNT=0`).

Runs: `scripts/duckdb_all.sh`; headroom check `scripts/duckdb_force_300.sh` (every useful transfer forced);
diagnosis `scripts/duckdb_pair.py QID ORDER [--force]`.

The sections below document the earlier integration into the RPT+ fork (planning-only decision layer).

# RPT-G decision layer in DuckDB (RPT+ fork)

Two engines are used:

- `ext/duckdb130/duckdb` — vanilla DuckDB v1.3.0 CLI (from `ext/duckdb_cli_130.zip`), the version the
  RPT+ fork is based on.
- `ext/rptplus` — embryo-labs/dynamic-predicate-transfer (RPT+ on DuckDB 1.3.0, head `e5a5633`),
  built with `make release` → `ext/rptplus/build/release/duckdb`. Without the patch it runs RPT+
  as-is (always on); this is the "RPT+ as-is" configuration of Judgment 2.

`rptg_stage2.patch` (~900 lines; supersedes `rptg_stage1.patch`, which lacks mode 2) adds `src/optimizer/predicate_transfer/rptg_planner.cpp`
(`PredicateTransferOptimizer::RPTGPrune`, called in `Optimize()` before the transfer operators are
inserted) and fixes a latent RPT+ bug in `src/execution/physical_plan/plan_use_bf.cpp` (creator plan
matched by pointer identity; the apply-binding match broke after creator lists were compacted).
Stage 1 is a planning layer only: it keeps RPT+'s Bloom-filter operators and decides which of the
filter plans to drop, using the graph-specific model (vertex table = smallest keyed base scan, edge
table = largest; selectivity from column min/max statistics, read through the `CAST(col AS DOUBLE)`
expression filters DuckDB creates for literals it cannot narrow to FLOAT; benefit = plan work without minus with
the filter, excluding the root join's output; cost = build rows × `c_mat` + probe rows × `c_probe`).
Mode 1 decides each plan greedily in execution order; mode 2 (`RPTGSelectPlans`) picks the kept set that
minimizes cost + β·work over the whole simulated sequence, with a fixed cost per CreateBF pipeline. Neither
sees DuckDB's min-max scan pruning, which is why a run-time controller is the next stage
(`docs/duckdb_integration.md`, "Why a plan-time layer is not enough in DuckDB").

Environment variables (read once per process):

| variable | default | meaning |
|----------|---------|---------|
| `RPTG_MODE` | 0 | 0 = RPT+ as-is; 1 = RPT-G pruning, greedy per plan; 2 = RPT-G pruning, whole-set objective |
| `RPTG_BETA` | 1.0 | keep a filter plan iff cost ≤ β × benefit; 0 drops every plan ("fork, no filters") |
| `RPTG_C_MAT`, `RPTG_C_PROBE` | 3.0, 0.3 | cost per built row / per probed row |
| `RPTG_C_PIPE`, `RPTG_C_ANY` | 150000, 400000 | mode 2: fixed cost per used CreateBF / of running any filter |
| `RPTG_DEBUG` | unset | print every decision to stderr |
| `RPTG_ONLY_DROP` | unset | drop only the k-th candidate (bisection aid) |

The fork is slower than vanilla DuckDB on output-heavy joins even when every filter is dropped
(its hash-join change), so every comparison includes the `RPTG_BETA=0` configuration.

## Build

```
cd ext/rptplus && git apply ../../hosts/duckdb/rptg_stage2.patch && make release
```

## Load and run

```
~/miniconda3/bin/python scripts/export_parquet.py data/bin/dblp        # V.parquet / E.parquet
RPTG_MODE=0 ~/miniconda3/bin/python scripts/run_duckdb_cli.py --bin ext/duckdb130/duckdb \
    --graph data/bin/dblp --db data/bin/dblp/dblp_130.db --queries queries/qgen_dblp_300.txt \
    --out results/duckdb300_vanilla.csv --method vanilla --reps 3 --warm 1 --threads 8 --timeout 10
RPTG_MODE=1 RPTG_BETA=1.0 ~/miniconda3/bin/python scripts/run_duckdb_cli.py --bin ext/rptplus/build/release/duckdb \
    --graph data/bin/dblp --db data/bin/dblp/dblp_rptplus.db --queries queries/qgen_dblp_300.txt \
    --out results/duckdb300_rptg.csv --method rptg --reps 3 --warm 1 --threads 8 --timeout 10
~/miniconda3/bin/python scripts/analyze_cli.py vanilla=results/duckdb300_vanilla.csv \
    rptplus=results/duckdb300_rptplus.csv rptg=results/duckdb300_rptg.csv fork=results/duckdb300_fork.csv \
    --meta queries/qgen_dblp.txt.meta.csv
```

Several configurations interleaved per query (the protocol for every result reported now; one process per
query and configuration, `method` = configuration name), then analysed from the one CSV:

```
~/miniconda3/bin/python scripts/run_duckdb_cli.py --graph data/bin/dblp --queries queries/qgen_dblp_300.txt \
    --configs vanilla:ext/duckdb130/duckdb:data/bin/dblp/dblp_130.db:0:1.0,rptplus:$F:$D:0:1.0,fork:$F:$D:1:0,rptg:$F:$D:1:1.0 \
    --out results/duckdb300_4way.csv --reps 3 --warm 1 --threads 8 --timeout 10
~/miniconda3/bin/python scripts/analyze_cli.py fork=results/duckdb300_4way.csv rptplus=results/duckdb300_4way.csv \
    rptg=results/duckdb300_4way.csv vanilla=results/duckdb300_4way.csv
```

(`F=ext/rptplus/build/release/duckdb`, `D=data/bin/dblp/dblp_rptplus.db`; a config is
`name:binary:db:RPTG_MODE:RPTG_BETA`.) `scripts/duckdb_300_4way.sh` is the exact command line of the
reported run; `scripts/duckdb_3way_300.sh` and `scripts/duckdb_300_rerun*.sh` those of the earlier
one-configuration-per-pass runs. The driver builds the `.db` file once, then runs each query in a fresh CLI process with
`.timer on` (warm + reps), kills it at the timeout, and records `error` when the process exits before
any timing line. Design notes and the two bugs found in the first run: `docs/duckdb_integration.md`.

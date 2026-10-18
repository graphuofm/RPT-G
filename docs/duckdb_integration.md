# RPT-G in DuckDB — integration notes

Host: the RPT+ fork of DuckDB v1.3.0 (`ext/rptplus`, embryo-labs/dynamic-predicate-transfer, built with
`make release`, binary `ext/rptplus/build/release/duckdb`). RPT-G is added as a decision layer on top of
RPT+'s planning and execution, so the two can be compared in the same engine with everything else equal.
Baselines: vanilla DuckDB v1.3.0 (`ext/duckdb130/duckdb`), RPT+ unchanged.

## What RPT+ does (code map, ~2,300 lines)
- `optimizer/predicate_transfer/table_operator_namager.cpp`: every LogicalGet (each E copy, each V copy
  of a self-join query) is a "table"; joins with equality conditions are collected.
- `transfer_graph_manager.cpp`: EdgeInfo per join condition; join-key equivalence classes
  (`JoinKeyTableGroup`, one leader table per class = our pattern vertex); `SkipUnfilteredTable`
  (tables without filters only receive BFs); `LargestRootUpdated` orders tables by cardinality;
  `CreateTransferPlanUpdated` builds ATP edges: forward smaller -> larger, backward larger -> class leader.
- `predicate_transfer_optimizer.cpp`: `Optimize` runs the forward pass (reverse order) and the backward
  pass over `transfer_order`, producing per table a chain of LogicalUseBF (filters to apply) and a
  LogicalCreateBF (filters to build, each a `FilterPlan{build cols, apply cols}`), then
  `InsertTransferOperators` splices them above the table's scan/filter. It runs after DuckDB's join
  order optimizer, so the plan tree at that point is the join order.
- `physical_create_bf.cpp`: sink that materializes its input and builds cascade filters (min-max +
  CSBF); dynamic pipeline: after gamma rows, if received/scanned > 0.35 -> abandon (`is_successful=false`,
  the probes of that BF are disabled). No cost/benefit comparison anywhere.
- DuckDB's estimates on our data: every range predicate 20% (63,416 of 317,080 for `pu < 0.001`, true 302),
  equality 77 (true 4,670). Same situation as Kùzu (10%): plan-time decisions need our own selectivity
  estimate from column min/max statistics (DuckDB keeps them per column: `NumericStats::Min/Max`).

## Graph-aware failure of RPT+ on pattern queries (from Judgment 2)
Every pattern edge is a copy of E; ATP treats each copy as a bridge table and builds a filter on it
(materializing 2.1M rows per copy on DBLP) whether or not the join above can benefit. 55% of Q-GEN
regress, 8.7% below 0.5x; output-dominated queries pay the full materialization for nothing.

## RPT-G stage 1 design (planning layer, no new operators)
1. Pattern recovery from RPT+'s structures: vertex = join-key class; predicate holder = V copy of the
   class with table filters; pattern edge = E copy (its two key columns lie in two classes).
2. Sizes: |B_v| from zone-map/uniformity estimate of the V copy's filters (n if none); |E| from the
   catalog; avgdeg = |E|/n per side; cached per-vertex degree sums are not available in a column store
   without a CSR, so survival uses the table average (accept the hub error, note it).
3. Per FilterPlan f (build table T, apply table U, key class g), in the order RPT+ would run them:
   cost(f) = materialize rows of T after its own upstream filters (c_mat per row) + BF build;
   benefit(f) = rows removed from U * downstream work per U row (number of join operators above U's
   scan in the plan tree, from the join order) + what later admitted filters gain from the smaller
   key set (marginal, simulated with the survival formula like the prototype/Kùzu models).
   surv(f) = 1 - (1 - |keys(T)|/n)^{avgdeg on U's side}; keys(T) = |B_g| for a V copy, N(B_.) for an E copy.
   Admit iff cost <= beta * benefit. Drop the FilterPlan from both the CreateBF (build side) and the
   UseBF chain (apply side); unwrap empty CreateBF/UseBF operators. Run-time: keep RPT+'s abandonment.
4. Pre-screen == the same procedure (there is no exact-size phase in DuckDB: the CreateBF sink is itself
   the materialization). A later stage can feed the sink's exact counts (num_input_rows) into the
   decisions of *later* filters (they run in pipeline order).
5. Deliverable: `CALL rptg_mode` equivalent via a DuckDB setting (`SET rptg_mode=...`), the same Q-GEN
   three-way run: DuckDB vanilla / RPT+ / RPT+ with RPT-G planning, DBLP then LJ.

## Status
- 2026-09-22: design written; implementation starting in `ext/rptplus` on top of the RPT+ sources.

## Stage 1 implemented (2026-09-22): `RPTGPrune` in `src/optimizer/predicate_transfer/rptg_planner.cpp`
Patch `hosts/duckdb/rptg_stage1.patch` (RPT+ fork + ~600 lines). Controlled by environment variables,
read per process (the CLI driver spawns one process per query): `RPTG_MODE=1` enables, `RPTG_BETA`
(1.0), `RPTG_C_MAT` (3.0 per materialized build row), `RPTG_C_PROBE` (0.3 per probed row), `RPTG_DEBUG=1`.
- Runs inside `PredicateTransferOptimizer::Optimize` after RPT+ built its forward/backward filter plans
  and before they are spliced into the plan; RPT+ execution (CreateBF/UseBF, cascade filters, dynamic
  abandonment) is unchanged, so the comparison is planning-only.
- Tables = RPT+'s table operators that are base scans (LogicalGet, or LogicalFilter over one); the
  ungrouped AGGREGATE that RPT+ also registers as a "table" is skipped. Key classes = RPT+'s
  `JoinKeyTableGroup`s (friend access). Key columns per table from `table_join_keys` (all join
  conditions). Vertex table = smallest keyed table, edge table = largest (an edge-table copy at a
  pattern leaf joins on one column only, so arity does not tell them apart). n = |V|, |E|, avgdeg = |E|/n.
- Selectivity from column min/max statistics (`TableFunction.statistics` -> `NumericStats::Min/Max`),
  uniformity; `table_filters` are keyed by the table's column id (not the scan output position — that
  cost one debugging round). DuckDB itself estimates 20% for every range predicate and 1/4096 for
  equality on our data.
- Decision per FilterPlan in RPT+'s execution order (forward pass in reverse table order, then backward):
  keys(build) = candidate set for a vertex table, endpoints of the surviving rows for an edge table
  (n(1-(1-rows/|E|)^avgdeg)); apply rows *= keys/n; cost = build rows * c_mat / plans of that CreateBF
  + apply rows * c_probe; benefit = plan work without minus with, where plan work = rows leaving every
  scan + outputs of intermediate joins (l*r/n) — the final join output is invariant under semi-join
  reduction and is excluded (q3, 130M output rows, was kept for a phantom 2M-row "benefit").
  Dropped plans are removed from the CreateBF's list and from the UseBF chains; empty operators unwrapped.
- Sanity (DBLP test queries, 8 threads, median of 3): q4955 (RPT+ case study) 0.23 -> 0.20 s (vanilla
  0.19); q8 95 -> 68 ms (vanilla 65); q6/q7 keep RPT+'s gains (415/1001 ms RPT+, 446/1044 RPT-G, vanilla
  586/2178). All counts correct.
- Finding: with every filter dropped the RPT+ fork still runs q3 in 0.65 s vs vanilla 0.41 s: the fork's
  hash-join change (build-side thread_num >= 8, see APPLY_ME_TO_GET_VANILLA_RPT.patch) costs on
  output-heavy joins independently of predicate transfer. Add "fork, no filters" (RPTG_MODE=1,
  RPTG_BETA=0) as a fourth configuration so that RPT+'s regressions are split into transfer cost and
  fork overhead.
- Running: `scripts/duckdb_3way_300.sh` -> results/duckdb300_{vanilla,rptplus,rptg}.csv.

## First 300-query run and two bugs (2026-09-22)
- Run 1 (`results/duckdb300_{vanilla,rptplus,rptg}.csv`, 3 reps in fresh processes, 8 threads): RPT+
  regresses 35.7% of queries below 0.8x (noise floor 6.0%), geomean 0.97; RPT-G 32.9%, geomean 1.11 —
  but 32 queries crashed under RPT-G ("Attempted to dereference unique_ptr that is NULL") and the CLI
  driver had recorded them as ok with count -1 (fixed: an error before any result is now `error`).
- Bug 1 (mine): re-linking a pruned CreateBF/UseBF chain top-down moved chain[i+1] into chain[i] and then
  dereferenced the moved-from pointer. Fixed by relinking bottom-up. Bug 2 (latent in RPT+): the
  physical UseBF planner matched its filter by apply bindings; after pruning, a forward and a backward
  CreateBF can become adjacent and get compacted by the linker into one creator holding two plans
  with the same apply column, so the second user moved an already-moved filter. Fixed by matching on
  plan pointer identity first (`plan_use_bf.cpp`).
- After both fixes: the 32 queries and the 8 test queries all agree with vanilla.
- Re-running the RPT-G configuration and adding "fork, no filters" (RPTG_MODE=1 RPTG_BETA=0): the RPT+
  fork changes the hash join (build-side thread_num >= 8) and is slower than vanilla on small and
  output-heavy queries even with no transfer at all — RPT+'s regressions must be split into fork
  overhead and transfer cost before any of them is attributed to predicate transfer.
- Small queries (< 20 ms, 124 of 283): RPT+ 0.81 / RPT-G 0.73 geomean — the fork's fixed costs;
  20–100 ms: 1.06 vs 1.59; 100 ms–1 s: 1.22 vs 1.49; >= 1 s: 1.08 vs 1.36 (run 1, before the fixes).

## Four-way 300-query run and a third bug: CAST-wrapped predicates (2026-09-22)

First complete run (`results/duckdb300_*_run1.csv`, vanilla 1.3.0 / RPT+ as-is / fork with every filter
dropped / RPT-G, median of 3 reps, 8 threads), against the fork-without-filters baseline:

| config | < 0.8× | < 0.5× | > 1.25× | geomean | total |
|--------|-------:|-------:|--------:|--------:|------:|
| RPT+ as-is | 18.6% | 1.1% | 40.1% | 1.172 | 82 s |
| RPT-G (run 1) | 31.5% | 4.3% | 26.5% | 0.997 | 96 s |

RPT-G was worse than RPT+ as-is: it dropped filters that RPT+ profits from most (q1747: 0.19 s with
all filters, 1.3 s with RPT-G's choice = the no-filter time). Cause: DuckDB pushes `FLOAT col < DOUBLE
literal` into the scan as an `ExpressionFilter` `CAST(col AS DOUBLE) < literal` whenever the literal
cannot be narrowed to FLOAT — in the Q-GEN workloads every selectivity below ~1e-4, i.e. exactly the
predicates that matter (112 of the 300 queries carry one). `TableFilterSelectivity` only understood
`ConstantFilter`, so these predicates fell back to the host's 20% default: a 15-vertex predicate was
costed as 63,416 vertices, the forward filter it feeds (`T2 → T1`, 115 keys in reality) was estimated at
244,733 keys and dropped, and the whole downstream join ran unfiltered.

Fix: `ExpressionFilterSelectivity` (strip casts, accept `BoundReferenceExpression` leaves, the column is
the `table_filters` key) — patch `hosts/duckdb/rptg_stage1.patch` regenerated. After the fix every
filter of q1747 / q723 / q930 is kept with the right key counts (T6 rows~10, T2 rows~63) and q1747 runs
in 0.17–0.22 s. Rerun of the three fork configurations back-to-back: `scripts/duckdb_300_rerun2.sh`
(`results/duckdb300_{rptg,rptplus,fork}.csv`).

Lesson for the paper (same as Kùzu's stats, §7): the host's own selectivity machinery is not usable
as-is — DuckDB's estimate for a CAST-wrapped range predicate is the 20% default, and the transfers that
matter are precisely the ones behind such predicates. The zone-map estimate must see through casts.

Tiny-query note: with the shared machine at load 30–75 the 10–20 ms queries move by 2–3× between
runs made at different times; only back-to-back runs of the compared configurations are meaningful
for that bucket (the CLI driver runs one configuration per pass, unlike the rep-major interleaving of
the prototype and Kùzu drivers).

## Four configurations interleaved per query — the number to report (2026-09-22, analysed 2026-09-29)

The back-to-back reruns (`results/duckdb300_*_run2drift.csv`) saw machine loads so different that even the
fork-vs-fork comparison drifted; `scripts/duckdb_300_4way.sh` runs vanilla 1.3.0 / RPT+ as-is / fork with every
filter dropped / RPT-G (mode 1, β = 1) one after the other for every query (`run_duckdb_cli.py --configs`),
3 reps each in a fresh process, 8 threads. `results/duckdb300_4way.csv`; 300 queries, counts identical.

Against the fork without filters (237 evaluated, noise floor < 0.8× 5.1%):

| config | < 0.8× | < 0.5× | > 1.25× | geomean | P5 | P95 | total | timeouts fixed / new |
|--------|-------:|-------:|--------:|--------:|---:|----:|------:|------:|
| fork, no filters | | | | | | | 74 s | |
| RPT+ as-is | 26.2% | 3.0% | 21.1% | 0.965 | 0.55 | 2.33 | 87 s | 1 / 2 |
| RPT-G (mode 1) | 24.5% | 2.5% | 19.4% | 1.004 | 0.58 | 2.20 | 65 s | 3 / 0 |
| vanilla 1.3.0 | 5.1% | 2.1% | 30.0% | 1.086 | 0.80 | 1.50 | 80 s | 3 / 2 |

By baseline time (geomean, share < 0.8×): < 20 ms RPT+ 0.75 (44%) / RPT-G 0.79 (43%); 20–100 ms 1.03 (23%) /
1.06 (22%); 100 ms–1 s 1.41 (4%) / 1.42 (2%); ≥ 1 s 1.03 (5%) / 1.16 (0%).
Against vanilla 1.3.0 (238 evaluated, noise floor 4.6%): RPT+ 44.1% below 0.8× (geomean 0.846), fork without
filters 31.1% (0.847), RPT-G 43.3% (0.857).

Reading:
- The fork's own overhead is as large as the whole transfer effect: with no filter at all it is 15% slower
  than vanilla (geomean 0.847; the hash-join build change of the fork). Of RPT+'s 44% regressions against
  vanilla, most are there without any transfer.
- Within the fork, RPT-G's plan-time layer cuts total time by 25% relative to RPT+ (65 s vs 87 s, 12% below the
  no-filter fork) and has no new timeouts, but it does not remove the small-query regressions: below 20 ms
  both RPT+ and RPT-G lose ~20% to fixed per-pipeline costs of CreateBF.

## Why a plan-time layer is not enough in DuckDB (2026-09-29)

Two effects the plan-time model cannot see, both visible in q3978 (`E e0,e1,e2` star, `v1.pu < 1.1e-5`,
`v2.label = 3140`, count 0; fork 12–15 ms, RPT+ 9–10 ms, RPT-G 16–17 ms):
1. **Min-max pruning with graph locality.** RPT+'s cascade filter pushes the [min, max] of the build keys into
   the apply table's scan. E is stored in CSR order (sorted by `src`), and DBLP ids have locality: the
   co-authors of a community occupy a narrow id range. With RPT+'s full filter set the three E scans read
   575,569 + 156,401 + 0 rows (the last key set is empty, so its scan is pruned entirely); with RPT-G's choice
   1,929,610 + 1,923,267 + 148,791. RPT-G had dropped the forward filter T1 → T0 (local benefit 21 rows, cost
   1,266 units): it removed almost nothing from T0 itself but would have emptied T0's key set, and with it the
   backward filters T0 → T1 / T0 → T2 whose scans it then prunes.
2. **Fixed per-pipeline cost.** A CreateBF is a pipeline breaker; on the < 30 ms queries RPT+ costs ~2 ms more
   than the fork with one CreateBF and ~0.5–0.75 ms per further one (regression on the 4-way data; one work unit
   of the model ≈ 2.5–4.5 ns on these queries).

Mode 2 (`RPTG_MODE=2`, `RPTGSelectPlans`): choose the kept set K minimizing cost(K) + β·work(K) by backward
elimination from RPT+'s full set, simulating the kept plans in execution order (so a forward plan is credited
with what it adds to the backward plans it feeds) and charging `RPTG_C_PIPE` (150K units) per used CreateBF and
`RPTG_C_ANY` (400K) once. On q3978 it keeps 4 of 7 plans but drops the forward label filter T4 → T1 (the backward
T0 → T1 gives the same row reduction in the model) and is still slower than RPT+: the model counts rows leaving
scans, not rows the scans read, so min-max pruning stays invisible. Mode 2 is kept as an option; not evaluated
on the full sample.

Consequence: in DuckDB the decisions need run-time information — the exact key count and [min, max] of every
build side once its CreateBF has finished, before the dependent filters are built (they run in pipeline
order) — which is what the Kùzu/LadybugDB controller has for free from mask cardinalities. Next DuckDB stage
(not started): a run-time controller in `PhysicalCreateBF` that decides each later filter from the finished
build sides (count, range, and zone-map coverage of the range in the apply table), reusing RPT+'s dynamic
pipeline to skip a filter's materialization. For the paper (§7): a plan-time-only port of the decision layer
cuts RPT+'s total time by 25% in its own engine but cannot remove the small-query regressions; the run-time
design is what does in the graph engines.

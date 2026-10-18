# RPT-G in Kùzu — integration notes

Host: Kùzu v0.11.3 (archived upstream 2025-10-10; LadybugDB is the maintained fork, port later).
Source + build: `ext/kuzu` (conda env `rptg-build`, GCC 13: `make release NUM_THREADS=28`),
shell at `ext/kuzu/build/release/tools/shell/kuzu`. Official wheel `kuzu==0.11.3` in conda base for
baselines. Databases in `data/kuzu/*.kz` (`scripts/kuzu_load.py`), runner `scripts/run_kuzu.py`
(Cypher, walk semantics = homomorphisms; counts match the prototype on the 8 test queries).

## How Kùzu executes our queries
- `SCAN_NODE_TABLE (+FILTER) -> SCAN_REL_TABLE (extend over CSR, factorized) -> ...`; a predicate on
  a vertex reached by an extend is applied by a HASH_JOIN with `[SCAN_NODE_TABLE + FILTER]` as build
  side. Two filtered branches meet in a hash join on the shared vertex.
- SIP (`src/optimizer/acc_hash_join_optimizer.cpp`): static rule `subPlanContainsFilter` — if one side
  of a hash join has a filter, ACCUMULATE that side (materialize into a factorized table), run a
  SEMI_MASKER over it, apply the mask to the other side's SCAN_NODE_TABLE. One hop, static,
  toggled by `CALL enable_semi_mask=true|false`.
- Masks: `common::SemiMask` (Roaring) owned by each physical ScanNodeTable; a SemiMasker writes
  into all its target scans. `SemiMaskerSharedState::mergeToGlobal` REPLACES the target mask by the
  union of thread-local masks (no intersection between different maskers).
- Scheduling: every Sink is a task; a task runs after all its child sink-tasks finished
  (`QueryProcessor::decomposePlanIntoTask`). `mapSIPJoin` adds a sink as an extra child of the join
  root to force ordering. `DummySink` runs a child plan and discards its output.

## Where Kùzu's semi-mask regresses (DBLP test q8, three 30% predicates, 8 threads)
192 ms without, 383 ms with. Profile: two RESULT_COLLECTORs (accumulate of the probe side) 272 + 220 ms
and two SEMI_MASKERs 61 + 48 ms, to shrink one scan from 95K to 67K rows. Same diagnosis as RPT+ made
for RPT: the filter needs a materialization that breaks the pipeline, and the rule never asks whether
the mask is worth it.

## Design of RPT-G in Kùzu (K1)
1. Transfer = side pipeline, not accumulate: `SCAN_NODE_TABLE(x, masked) [+FILTER σ_x] ->
   SCAN_REL_TABLE(e, dir) -> SEMI_MASKER(key y, intersect mode) -> DUMMY_SINK`. Cost = Σdeg(B_x) as
   in the prototype; the main plan stays streaming.
2. Intersect mode for SemiMasker: target mask := target mask AND new mask when the target already
   holds a transfer result (needed for multi-hop: B_y <- B_y ∩ N(B_x)).
3. Ordering: chain the transfer sinks as extra children (T_k has T_{k-1} as extra child; the main
   plan root gets the last one), so the scheduler runs them in sequence before the main plan.
4. Plan: Algorithm 1' on the pattern recovered from the logical plan (LogicalExtend gives bound node,
   nbr node, rel, direction; LogicalFilter gives σ_x). Consumers of B_y = SCAN_NODE_TABLE(y) operators
   of the main plan and of later transfers. Usefulness: a transfer into y is useful iff some consumer
   scan of y exists whose downstream work it can reduce, or a later useful transfer reads y.
5. Budget: exact-cost side from table statistics (|V|, |E|, avg degree) and, at run time, from the
   exact mask cardinality of the source (known when the previous transfer finished); benefit from
   Kùzu's cardinality estimates of the sub-plan above the consumer scan.
6. Later (K2): pull direction, mask filter after SCAN_REL_TABLE (replaces the hash join used only to
   apply a predicate), edge scan.

## Baseline run K0 (in progress)
`results/kuzu_dblp_qgen.csv`: Q-GEN 5,000 on DBLP, enable_semi_mask on (KSM) vs off (KNO), rep-major
interleaved, 8 threads, 10 s timeout — the regression rate of a real graph DB's static semi-mask.

## Stage A done (2026-09-21): plumbing validated
Patch: `hosts/kuzu/rptg_stage_a.patch` against Kùzu v0.11.3 (branch `rptg` in `ext/kuzu`, uncommitted).
- `CALL rptg_mode=1` replaces the hash-join SIP by `RPTGTransferOptimizer` (src/optimizer/
  rptg_transfer_optimizer.cpp): recovers the tree pattern from the logical plan (EXTENDs, SCAN_NODE_TABLEs,
  FILTER chains over scans), builds the forward/backward sequence (Algorithm 1'), prunes by source-skip
  simulation + consumption (a scan of y in the main plan, or a later kept transfer reading y), and emits
  each kept transfer as `[FILTER chain copy | SCAN_NODE_TABLE] -> EXTEND -> SEMI_MASKER(intersect) ->
  DUMMY_SINK` stored in `LogicalPlan::rptgTransfers`.
- `SemiMask::written` + `SemiMaskerSharedState::intersect`: a second transfer into the same scan ANDs
  instead of overwriting.
- `PlanMapper::mapLogicalPlanToPhysical`: maps transfers in reverse (targets first), nests T_{i-1} as
  last child of T_i and the chain as last child of the root; the scheduler runs child tasks
  sequentially, right-most first, so the order is T_1..T_k, then the main plan. (An enabled-but-empty
  mask would filter everything, so this ordering is a correctness requirement, not a nicety.)
- Bails out (no transfers) for non-tree patterns, recursive or undirected rels, non-inner joins, and
  any operator outside a whitelist.
- Result on the 8 DBLP test queries (8 threads, machine loaded): all counts correct. Times off / Kùzu
  semi-mask / RPT-G stage A: q2 92/80/221 ms, q6 596/555/1092, q7 2360/4403/2624, q8 144/210/249.
  Stage A has no budget, so it over-transfers like M4; that is the next step.

## Next
1. Budget: exact cost side at run time (mask cardinality of the source is known when the previous
   transfer finished; avg degree from table stats), benefit from Kùzu's cardinalities above the
   consumer scans; skipped transfers must leave their target masks non-filtering.
2. Python binding of the modified build (tools/python_api) so `scripts/run_kuzu.py` can drive it with
   interleaved reps; then Q-GEN 5,000 on DBLP/LJ: off vs Kùzu semi-mask vs RPT-G.
3. Pull direction, mask filter after SCAN_REL_TABLE, edge scan.

## Evaluation tooling (2026-09-21)
- Python binding of the modified build: `make python` -> `ext/kuzu/tools/python_api/build` (cp311; run with
  `PYTHONPATH=ext/kuzu/tools/python_api/build python scripts/run_kuzu.py ...`).
- `run_kuzu.py --configs KNO:0:0,KSM:1:0,KRG:0:1` interleaves no-mask / Kùzu semi-mask / RPT-G per rep.
  `--buffer-gb` bounds the buffer pool: Kùzu defaults to 80% of RAM per process, which got two of
  three shards OOM-killed in the first K0 attempt.
- First K0 attempt (kept as `results/kuzu_dblp_qgen_noisy_partial.csv`, 2,569 queries, noise floor 22.8%
  because a build ran concurrently): semi-mask on regresses 26.1%, geomean 1.07; helps for
  selectivity < 1e-4 (geomean 1.23), hurts for 1e-3..0.1 (0.88–0.92); total 567 s off vs 632 s on.
  Clean re-run in progress.
- Prototype fix (rptg_v5c): predicates compare in double like the hosts (FLOAT column vs DOUBLE
  literal); three of 2,561 counts had differed by < 0.01% at the float32 boundary.

## Stage B done (2026-09-21): run-time transfer budget
Patch: `hosts/kuzu/rptg_stage_b.patch` (supersedes stage A; 20 files, ~900 lines).
- Settings: `CALL rptg_mode=0|1|2` (off / all useful transfers / budgeted), `CALL rptg_beta=<double>`.
- Self-mask pipelines `[FILTER chain -> SCAN] -> SEMI_MASKER(x)` run first for every predicate vertex
  taking part in a kept transfer, so |B_x| is an exact mask cardinality afterwards. Needed because
  Kùzu estimates every range predicate at 10% selectivity.
- `RPTGController` (src/processor/operator/rptg_transfer_sink.*): when transfer i is about to start,
  cost = |B_x| * avgdeg(x->y) (exact size, table-average degree) vs benefit = (1 - surv) * |B_y| *
  workPerTuple(y), surv = 1 - (1 - |B_x|/|V_x|)^avgdeg(y->x), with the same-edge round-trip
  correction and inheritance from later transfers the target feeds; workPerTuple(y) = host-estimated
  tuples flowing through the operators above y's consumer scans per tuple leaving them.
  Rejected transfer: `SemiMaskerSharedState::setSkipped()`, no write; masks of RPT-G maskers are
  enabled by their first write (not at map time), so a rejected transfer cannot filter anything.
  Run-time source skip: a predicate-less source whose incoming transfers were all rejected.
- Gotcha: rel statistics need `rel->getInnerRelTableIDs()` (storage ids), not the rel-group catalog id
  (`unordered_map::at`). `RPTG_DEBUG=1` prints the emitted sub-plans.
- 8 DBLP test queries, 8 threads, median of 5 (no mask / Kùzu semi-mask / RPT-G no budget / budget):
  q2 68/74/200/77 ms, q6 607/610/917/693, q7 2306/3595/2617/2532, q8 136/215/257/151; all counts correct.

## Four-way Q-GEN run on DBLP with Stage B (2026-09-21) — not good enough, and why
`results/kuzu_dblp_4way.csv` (5,000 queries, 8 threads, median of 3 interleaved reps, counts identical
across all configs). Noise floor: < 0.8x 9.6%, < 0.5x 0.1%.
| config | < 0.8x | < 0.5x | > 2x | geomean | total | timeouts fixed / new |
|---|---|---|---|---|---|---|
| no mask | | | | | 1,098 s | |
| Kùzu semi-mask | 17.1% | 4.7% | 11.8% | 1.08 | 1,234 s | 41 / 16 |
| RPT-G no budget | 41.1% | 14.7% | 12.0% | 0.92 | 1,129 s | 20 / 0 |
| RPT-G budget (stage B) | 32.9% | 7.6% | 12.4% | 1.02 | 1,055 s | 21 / 0 |
Queries >= 1 s: RPT-G budget geomean 1.37, 0% below 0.8x (Kùzu semi-mask 0.89, 27%). Queries < 20 ms:
RPT-G 0.81 (39% below 0.8x), Kùzu semi-mask 0.96.
Diagnosis from decision logs:
1. Benefit side used Kùzu's cardinalities (10% per range predicate, multiplied up the plan): work per
   tuple of 59–2,671, benefits of millions of units on 25 ms queries, so nearly everything was admitted.
2. Inheritance credited a transfer with the whole benefit of any later transfer reading its target,
   even when that later transfer did not depend on it (q2584: a 289K-unit transfer into a 4-vertex set
   admitted because of an unrelated 7-unit transfer). Only the marginal benefit counts; on a same-edge
   round trip it is zero.
3. Compile overhead is small (+1–6 ms). Self-mask pipelines alone cost +4.5 ms per query (median),
   geomean 0.91: Kùzu has ~2 ms of fixed cost per pipeline.

## Stage C (2026-09-21): run-time work model
Patch `hosts/kuzu/rptg_stage_c.patch`. The optimizer serializes the main plan into SCAN / EXTEND /
HASH_JOIN nodes (post-order) with table-average degrees and key-table sizes; the controller evaluates
its work on the exact mask cardinalities: SCAN -> |B_v|, EXTEND -> child * deg, HASH_JOIN -> probe *
build / |V_key|. benefit(T_i) = [work + cost of later transfers] simulated without T_i minus the same
with T_i (later transfers simulated with the survival formula and the no-compounding rule per edge);
cost(T_i) = rptg_pipeline_cost (default 80,000 units ~ 2 ms) + |B_x| * avgdeg.
Decisions now look right (q2584 T2 cost 289K gain 87 -> SKIP; q3763 three 100K+ transfers -> SKIP).
Known model error: survival uses the table-average degree; with degree-correlated predicates (hubs)
the target's true degree is far larger and survival ~1 while the model predicts 0.33 (q3922). This is
what the prototype's exact degree accumulators fix; Kùzu has no per-mask degree sums yet.

## Stage C on the 300-query sample (2026-09-21)
`results/kuzu_dblp300_v3.csv` (KNO / KSM / KR2, median of 3, noise floor < 0.8x 8.1%, < 0.5x 0.0%):
| | < 0.8x | < 0.5x | > 2x | geomean | total |
|---|---|---|---|---|---|
| no mask | | | | | 94.0 s |
| Kùzu semi-mask | 21.5% | 6.3% | 8.1% | 1.01 | 107.0 s |
| RPT-G stage B (same queries, 4-way run) | 32.0% | 4.2% | 11.6% | 1.05 | 100.3 s |
| RPT-G stage C | 24.6% | 0.7% | 10.2% | 1.04 | 92.0 s |
By baseline time, RPT-G C vs Kùzu semi-mask (geomean, share < 0.8x): < 20 ms 0.80 (54%) vs 0.91 (27%);
20–100 ms 1.10 (24%) vs 1.14 (18%); 100 ms–1 s 1.14 (14%) vs 0.97 (21%); >= 1 s 1.01 (0%) vs 0.88 (25%).

## Where the remaining small-query overhead comes from
- A filtered scan of the 317K-row node table costs 1.8–3.2 ms in Kùzu (8 threads barely help; an empty
  query costs 0.6 ms), so every self-mask pipeline is +2–3 ms, and the masked main-plan scan does not
  give it back for non-selective predicates (masks skip at 2,048-row vector granularity).
- Budgeting the self-masks with an upper bound on main-plan work (unknown predicate vertices at table
  size) almost never fires: the bound is dominated by the unknown scan itself.
- Exact sizes cost a scan; zero overhead needs plan-time information. Next: plan-time pre-screen with
  zone-map (min/max) selectivity estimates for range predicates, emit no side pipeline at all when no
  transfer can pass the budget under those estimates, keep run-time exact decisions for the rest.
- Separate known model error: table-average degree in the survival formula (hub predicates, q3922).

## Stage D (2026-09-21): plan-time pre-screen with zone-map selectivities
Patch `hosts/kuzu/rptg_stage_d.patch` (supersedes C). Settings: `rptg_mode`, `rptg_beta`,
`rptg_pipeline_cost` (80,000 units ~ 2 ms), `rptg_prescreen_slack` (1.0).
- `common/rptg_budget_model.h`: the decision logic (plan work model, survival, marginal gain by
  simulation) shared by the run-time controller (exact mask cardinalities) and the optimizer.
- Optimizer estimates |sigma_x| from the column min/max kept for zone maps (uniformity; equality on
  integers 1/(max-min+1)); AND/OR handled, anything else falls back to the host's 10%. On DBLP the
  estimates are within 5% (317 vs 302, 95,124 vs 95,031, 43,703 vs 43,700) where Kùzu says 31,708.
- Pre-screen: dry-run the transfer sequence on those estimates; emit only the admitted transfers and
  the self-masks of the vertices they touch; a query with none gets no side pipeline (zero overhead).
- Stage C+ check on the 300-query sample (`results/kuzu_dblp300_v4.csv`): budgeting the self-masks at
  run time changed nothing (< 20 ms bucket 0.80, 57% below 0.8x) — the information has to come before
  any pipeline runs. With the pre-screen the six sampled regressions: q234 9.9 vs 10.7 ms, q2584
  14.4 vs 14.0, q3533 13.8 vs 13.8, q3763 41.9 vs 42.8, q8 133.7 vs 135.9 (no side pipelines emitted).
- Remaining regressions (q2689 33 -> 58 ms, q3922 32 -> 59 ms, q2 74 -> 88 ms) share one cause:
  candidate sets of hubs. Both the cost and the survival need the degree sum of the source:
  cost = sum deg(B_x), P(random neighbour in B_x) = sum deg(B_x) / |E|, not |B_x| / |V|. q2689: source
  = top-0.6% degree vertices, true cost ~290K entries (model 12.9K), true hit probability 14% (model
  0.6%), gain overestimated ~30x. This is the degree accumulator of the master plan, and here it matters.
  Needs a cheap per-vertex degree (cached degree array per rel table/direction, built once from the CSR
  headers) so that sum deg(mask) is an O(|B|) pass.
- Full three-way run with stage D: `results/kuzu_dblp_3way_d.csv` (in progress).

## Stage D, full three-way run on DBLP (2026-09-21) — RPT-G now ahead of Kùzu's semi-mask
`results/kuzu_dblp_3way_d.csv`, 4,676 queries evaluated (304 baseline timeouts excluded), 8 threads,
median of 3 interleaved reps, counts identical across configs. Noise floor: < 0.8x 7.9%, < 0.5x 0.0%.
| config | < 0.8x | < 0.5x | > 2x | geomean | P5 | total | timeouts fixed / new |
|---|---|---|---|---|---|---|---|
| no mask | | | | | | 1,106 s | |
| Kùzu semi-mask | 15.8% | 4.6% | 11.7% | 1.086 | 0.51 | 1,235 s | 43 / 16 |
| RPT-G stage D | 13.8% | 0.5% | 9.3% | 1.098 | 0.69 | 1,050 s | 13 / 0 |
By baseline time (geomean, share < 0.8x), RPT-G vs Kùzu semi-mask: < 20 ms 0.98 (8%) vs 0.97 (14%);
20–100 ms 1.19 (17%) vs 1.24 (17%); 100 ms–1 s 1.09 (15%) vs 1.05 (14%); >= 1 s 1.11 (0%) vs 0.91 (25%).
Queries with a hub predicate: 1.01 (15% < 0.8x) vs 0.98 (23%); without: 1.13 (13%) vs 1.13 (13%).
Progression of RPT-G in Kùzu on this workload (< 0.8x / < 0.5x / total): no budget 41.1% / 14.7% /
1,129 s -> budget on host estimates 32.9% / 7.6% / 1,055 s -> run-time work model + pre-screen
13.8% / 0.5% / 1,050 s.

Bug found by this run and fixed: 20 queries segfaulted under rptg_mode=2. The pre-screen dropped later
transfers, leaving an earlier kept transfer whose target had no scan left to write to; a semi masker
with an empty target list dereferences an empty vector. Fix: after the pre-screen, re-run the
backward consumption check on the kept set, and never build a masker without targets. Those 20 queries
are missing from the table above (they crashed before any row was written); re-run with the next build.

## Stage E (2026-09-21): degree sums, measured transfer cost, exact masks
Patch `hosts/kuzu/rptg_stage_e.patch` (supersedes D).
1. Degree cache (`storage/rptg_degree_cache.*`): per rel table and direction, the CSR header lengths of
   all node groups read once into a `vector<uint32_t>` (process-wide cache). `SemiMask::sumOver(weights)`
   gives sum deg(B) in one pass over the set bits. The budget model keeps, per pattern edge and
   endpoint, the average degree of the *current candidate set* (table average until the mask is
   written): cost uses sum deg(B_x); a random neighbour lies in B_x with probability sum deg(B_x)/|E|.
   Hub sets show up as deg 88–193 where the table average is 6.6.
2. Factorized plan-work model: per-vertex flat counts (SCAN -> |B_v|, EXTEND(b->o) -> cnt[o] = cnt[b]*deg,
   HASH_JOIN scales the probe side by |build_k|/|V_k|); stars no longer multiply (q3922 had been
   estimated at 1.4e9 units for a 34 ms query).
3. Measured transfer cost in Kùzu (521 executed transfers, DBLP, 8 threads): wall time grows like
   0.27 ms * |B_x|^0.43 and is nearly independent of the number of adjacency entries (0.5 / 1.5 / 4 /
   11 / 21 ms for |B_x| in 1e0..1e4+); a self-mask pipeline costs ~1.1 ms. Cost model:
   rptg_pipeline_cost (10,000 units) + 10,800 * |B_x|^0.43 + 0.5 * entries, units of ~25 ns.
   Pre-screen now also charges the self-masks of the touched vertices against the net gain.
4. THE important one — Kùzu's masks are not exact. `ChunkedNodeGroup::scan` calls
   `anchorSelVector.setToUnfiltered(numRowsToScan)` after `applySemiMaskFilter` prepared the row-level
   selection, so a semi mask only skips whole 2,048-row vectors. A 782-vertex mask spread over 155
   vectors pruned 5% of the scan; the main plan got almost nothing from the reductions and transfer
   sources were vector-rounded supersets. Fix: masks written by RPT-G are flagged `exact` and the
   node-group scan re-applies them row by row after the chunk scan (`applySemiMaskRowFilter`);
   Kùzu's own semi-mask path is left untouched for a fair baseline. All earlier Kùzu numbers
   understate RPT-G for this reason.
   Effect (8 threads, median of 7): q2 91.9 -> 22.7 ms (4.0x), q3 111.5 -> 69.3 (1.6x), q6 570 -> 445
   (1.3x), q7 2291 -> 2057 (1.1x), q2689 31.6 -> 23.7 (1.3x; was 0.6x before the fix); counts correct.
Full three-way run with stage E: `results/kuzu_dblp_3way_e.csv` (in progress).

## Stage E, full three-way run on DBLP (2026-09-22) — the number to report
`results/kuzu_dblp_3way_e.csv`, 5,000 queries, 4,693 evaluated (307 baseline timeouts excluded), 8 threads,
median of 3 interleaved reps, counts identical across the three configs on all 4,674 queries where all
finished. Noise floor (no-mask rep0 vs rep1): < 0.8x 9.6%, < 0.5x 0.0%, > 1.25x 9.2%.
| config | < 0.8x | < 0.5x | > 1.25x | > 2x | > 5x | geomean | P5 | P50 | P95 | total | timeouts fixed / new |
|---|---|---|---|---|---|---|---|---|---|---|---|
| no mask | | | | | | | | | | 1,072 s | |
| Kùzu semi-mask | 17.3% | 5.1% | 20.5% | 11.5% | 0.8% | 1.07 | 0.50 | 1.00 | 3.17 | 1,210 s | 44 / 19 |
| RPT-G stage E | 4.6% | 0.0% | 56.0% | 41.1% | 14.3% | 1.92 | 0.81 | 1.45 | 8.07 | 688 s | 40 / 0 |
By baseline time, RPT-G geomean (share < 0.8x): < 20 ms 0.97 (15%), 20–100 ms 2.19 (2%), 100 ms–1 s
2.80 (0%), >= 1 s 2.03 (0%). Kùzu semi-mask: 0.94 (18%), 1.23 (17%), 1.02 (16%), 0.90 (26%).
By minimum selectivity, RPT-G: < 1e-4 2.27, < 1e-3 1.98, < 1e-2 1.68, < 0.1 1.19, non-selective 1.00
(Kùzu semi-mask 1.24 / 0.92 / 0.88 / 0.90 / 0.97). Hub predicates present: RPT-G 1.64 (6% < 0.8x) vs 0.97 (25%).
Progression on this workload (< 0.8x / < 0.5x / geomean / total): stage A no budget 41.1% / 14.7% / 0.92 /
1,129 s -> B 32.9% / 7.6% / 1.02 / 1,055 s -> D 13.8% / 0.5% / 1.10 / 1,050 s -> E 4.6% / 0.0% / 1.92 / 688 s.
Figure: results/kuzu_dblp_3way_e.png. LJ three-way run started: results/kuzu_lj_3way_e.csv.

## kuzu_dev tree (2026-09-22)
`ext/kuzu_dev` = copy of `ext/kuzu` (stage E) for development while the LJ run holds the `ext/kuzu`
python module. Adds `CALL exact_semi_mask=true|false` (default false = stock 0.11.3 behaviour): when
true, every enabled mask — including Kùzu's own hash-join semi-masks — is applied row by row.
Planned KSM baseline re-run with exact masks (config "KSX": enable_semi_mask=1, exact_semi_mask=1).

## LadybugDB port (2026-09-22)
`ext/ladybug` = LadybugDB v0.21.0-dev (head 6953959, 2026-09-19), branch `rptg`, patch
`hosts/ladybug/rptg_stage_e.patch`. The Kùzu stage-E patch applied with 5 hunks fixed by hand
plus these API changes: namespace `lbug`, `storage::StorageManager::Get(*context)`,
`transaction::Transaction::Get(*context)`, `context->getDatabase()->getMemoryManager()`,
`getMergedColumnChunkStats()` without a transaction, `InMemChunkedCSRHeader` for the in-memory CSR
header, settings' method bodies out of line in `settings.cpp`. Build: conda `openssl>=3`
(`OPENSSL_ROOT_DIR`), `tools/python_api` submodule, `make python`; module `ladybug` (`_lbug.so`).
Loader `scripts/ladybug_load.py`, runner `scripts/run_ladybug.py` (same flags as run_kuzu.py).
- All 8 test queries return correct counts under rptg_mode 0/1/2 and Ladybug's own semi-mask.
- Ladybug's own masks are already row-exact (upstream fix), so KSM there is the fair host baseline.
- Ladybug 0.21 plans some of our queries much worse than Kùzu 0.11.3: q8 (three 30% predicates)
  builds a hash table on a 13.5M-row intermediate (38 s CPU, 5.5 s wall vs 140 ms in Kùzu) and the
  driving node scan is not factorized (4.4M scanned rows instead of 95K); q2 on the other hand is 3x
  faster (30 vs 90 ms). RPT-G inherits the host plan, so absolute numbers are not comparable across
  the two hosts; the comparison that matters is within Ladybug (no mask / semi-mask / RPT-G).
- 300-query three-way run on Ladybug: `results/ladybug_dblp300.csv` (in progress).

## LadybugDB, 300-query run with the stage-E port (2026-09-22)

`results/ladybug_dblp300.csv`, `qgen_dblp_300.txt`, LNO / LSM / LR2 = no mask / Ladybug's own semi-mask /
RPT-G (mode 2, β = 1), 8 threads, median of the measured reps, run under a machine load of 120–200
(noise floor LNO vs its own rerun: 11.8% below 0.8×). 236 queries have all three configurations.

| config | < 0.8× | < 0.5× | > 1.25× | > 2× | geomean | P5 | P95 | total | timeouts |
|--------|-------:|-------:|--------:|-----:|--------:|---:|----:|------:|---------:|
| LSM | 3.4% | 0.0% | 17.4% | 7.2% | 1.184 | 0.84 | 2.54 | 155 s | 2 |
| LR2 | 11.5% | 0.9% | 17.4% | 9.8% | 1.190 | 0.72 | 8.16 | 135 s | 0 |

By baseline time (geomean, share < 0.8×): 0–20 ms LR2 0.91 (17%) vs LSM 1.00 (10%); 20–100 ms 1.02 (16%)
vs 1.11 (2%); 100 ms–1 s 1.57 (4%) vs 1.47 (0%); > 1 s 1.83 (0%) vs 1.35 (0%). Kùzu 0.11.3 on the same
queries: KR2 1.93 geomean, KSM 1.02.

Reading:
- Ladybug's own semi-mask is a much stronger baseline than Kùzu 0.11.3's: its masks are row-exact and,
  new in the fork, a semi mask can target the *neighbour node of an EXTEND* (`SemiMaskTargetType::
  EXTEND_NBR_NODE`, `ScanRelTable::applyNbrNodeMask`): the rel scan drops neighbours outside the mask
  instead of materialising every expanded edge. Kùzu 0.11.3 masks only node-table scans.
- Our port attached RPT-G masks to node-table scans only. For a vertex the main plan reaches through an
  EXTEND (q780: v0, v2, v3 are all reached from the label-filtered v1) the transfers ran (T0–T3, T6: ~10 ms,
  |B0| 317080 → 19, |B3| 90160 → 7) but nothing consumed them: LR2 = LNO = 40–53 ms while LSM's
  neighbour mask gave 27–31 ms. This is the whole small-query regression bucket.
- Ladybug's own planner also starts from the selective vertex more often than Kùzu 0.11.3 (q4340, one
  1e-5 predicate on a 3-vertex path: LNO 6 ms vs KNO 93 ms), so part of what RPT-G gained in Kùzu is
  already in Ladybug's baseline. The remaining gain is on large queries (1.83× at > 1 s, total 135 s vs
  155 s for LSM and 175 s for LNO).
- Stage F (below): target the main plan's EXTENDs with the same mask.

Wrong counts in LadybugDB itself: 4 of 300 queries (q293, q790, q4016, q4511) return a count different from
Kùzu 0.11.3 and the prototype in *every* configuration, including LNO (no masks, no transfers); q293
returns 190,857 with `enable_semi_mask=false`, 2,959,782 with it, 2,536,921 with the MATCH clauses
reordered — the right answer is 7,225,430. All 3-edge sub-patterns of q293 count correctly; the 4-edge
chain does not; thread count does not matter. The unpatched tree is being built (`ext/ladybug_vanilla`) to
confirm this is upstream (nothing of the patch runs in LNO except the row-exact mask filter, which needs a
mask). These queries are excluded from the LadybugDB comparison.

Known gap: `EXPLAIN`/`PROFILE` with `rptg_mode > 0` throws `unordered_map::at` in the LadybugDB port (the
explain path copies the plan, and the raw operator pointers kept for the transfers do not follow); plain
execution is unaffected.

## Stage F, LadybugDB only (2026-09-22): neighbour masks on the main plan's EXTENDs

Each RPT-G masker now also targets every EXTEND of the main plan whose neighbour node is the masked
vertex (when the extend scans the neighbour ID; `PatternVertex::mainExtends`). `mapSemiMasker` accepts
node-scan and rel-scan targets for an intersecting masker and leaves the rel-scan masks disabled until the
first write, like the scan masks. The budget model's EXTEND step multiplies the produced edges by the
degree-sum survival |B_o| · deg_e(B_o) / |E_e| when the neighbour vertex is masked (`RPTGPlanNode::nbrMask`).
Consumption checks (plan-time pruning and the run-time orphan check) count an EXTEND target as a consumer.
Kùzu 0.11.3 has no neighbour masks; porting Ladybug's `applyNbrNodeMask` there is the corresponding item.

## Stage E on LiveJournal (2026-09-22, analysed 2026-09-29)

`results/kuzu_lj_3way_e.csv`, LJ Q-GEN, 4,989 queries recorded (11 lost to worker crashes), 3,746 evaluated
(1,243 baseline failures excluded: 10 s timeouts and buffer-pool-full errors at ~10 s, which count as
timeouts), 8 threads, median of 3 interleaved reps, counts identical across configs. Noise floor (no-mask
rep vs rep): < 0.8× 3.5%, < 0.5× 0.0%, > 1.25× 4.0%.

| config | < 0.8× | < 0.5× | > 1.25× | > 2× | geomean | P5 | P50 | P95 | total | failures fixed / new |
|---|---|---|---|---|---|---|---|---|---|---|
| no mask | | | | | | | | | 3,693 s | |
| Kùzu semi-mask | 29.5% | 15.1% | 11.7% | 4.0% | 0.856 | 0.30 | 0.97 | 1.78 | 4,415 s | 67 / 27 |
| RPT-G stage E | 4.5% | 0.4% | 56.0% | 40.2% | 2.189 | 0.82 | 1.46 | 18.89 | 1,902 s | 83 / 3 |

By baseline time, RPT-G geomean (share < 0.8×): < 20 ms 0.99 (4%), 20–100 ms 0.99 (17%), 100 ms–1 s 3.05 (2%),
≥ 1 s 2.84 (0%); Kùzu semi-mask 0.99 (6%), 0.82 (37%), 0.81 (31%), 0.92 (31%). Hub predicate present:
RPT-G 1.68 (7% < 0.8×) vs semi-mask 0.80 (41%); none: 2.45 (4%) vs 0.88 (25%).
- On the heavy-tailed graph Kùzu's own semi-mask is a net loss (geomean 0.86, one query in seven below 0.5×)
  while RPT-G halves total time. The remaining RPT-G regressions sit in the 20–100 ms bucket: the worst
  (q1108 27 → 109 ms, q1827 39 → 112 ms) are paid transfers from hub sets whose benefit did not materialize:
  q1108's push shrinks |B_v1| 10× and the extended rows 2.6× as predicted, but Kùzu's rel scan costs per
  2,048-node vector of sources and 5,940 random sources still touch 92% of the vectors, so the extends take as
  long as before (see insights.md, 2026-09-29). The model needs a touched-vectors term.
- 3 new failures under RPT-G (q3321: 744 ms → timeout; the semi-mask config times out too) — to diagnose.

## Fair host baseline: Kùzu semi-mask with row-exact masks (KSX, 2026-09-22, analysed 2026-09-29)

`results/kuzu_dblp_ksx.csv`, `ext/kuzu_dev` (`CALL exact_semi_mask=true`), KNO and KSX interleaved, DBLP Q-GEN,
4,668 evaluated. Noise floor < 0.8× 10.9%. The run is separate from `kuzu_dblp_3way_e.csv` (KNO total 1,207 s
here vs 1,072 s there), so each config is compared against the no-mask baseline of its own run:

| config (vs its own run's KNO), same 4,668 queries | < 0.8× | < 0.5× | > 1.25× | geomean | new timeouts |
|---|---|---|---|---|---|
| Kùzu semi-mask, stock vector-granular masks (KSM) | 17.2% | 5.1% | 20.5% | 1.07 | 19 |
| Kùzu semi-mask, row-exact masks (KSX) | 15.7% | 4.8% | 28.7% | 1.24 | 25 |
| RPT-G stage E (KR2) | 4.6% | 0.0% | 56.0% | 1.92 | 0 |

- Exact masks make the host's own semi-mask better on the upside (geomean 1.07 → 1.24) and leave its regressions
  where they were (15.7% below 0.8×, 4.8% below 0.5×, 25 new timeouts). RPT-G's lead over the fair baseline is
  1.55× per query (geomean of the speedup ratio); it is not an artifact of giving only RPT-G exact masks.
- Per query, RPT-G beats KSX by > 1.25× on 44% of queries and loses by > 1.25× on 19.5% — a cross-run ratio of
  two noisy ratios, so only indicative; an interleaved KSX/KR2 run would settle it.

## Stage G (2026-10-14): the counting shortcut (host core v4) in Kùzu 0.11.3

The same counting path that PostgreSQL and DuckDB run (`docs/insights.md`, "Counting inside the hosts"),
added to `rptg_transfer_optimizer.cpp` (`rptgTryCount`, called from `rewrite` once the pattern has a predicate
and before any transfer is planned). It fires for a bare `MATCH ... RETURN count(*)` over a tree pattern on one
node and one rel table whose root chain is projections over a single keyless `COUNT_STAR` aggregate:

- The shared core (`third_party/rptg -> prototype/src`, `rptg_c.cpp` compiled into `kuzu_optimizer`) gets the
  adjacency index from a side connection (`MATCH (a:V)-[:E]->(b:V) RETURN offset(id(a)), offset(id(b))`; DBLP
  n = 317,080, m = 2,099,732, 672 ms, once per process, cached by (storage manager, rel table)).
- The decision (`rptg_count_decide`: count when C <= 8 x E with E >= 20K, or C <= 2e6) is made from Kùzu's own
  zone-map estimates (`estimateChainSelectivity`) and average degrees, before any predicate is evaluated; the
  start vertex is the plan's first node scan, the steps follow the plan's extends from it.
- The predicate sets come from side queries (`MATCH (v:V) WHERE <chain> RETURN offset(id(v))`), with each bound
  FILTER rendered back to Cypher (comparisons, AND/OR/NOT, properties, literals; casts dropped; anything else
  leaves the query to the transfer path).
- `rptg_count` transfers under the counting benefit alone and counts; the plan becomes a projection of the
  constant over a dummy scan. Counts were identical to the no-mask and transfer-only configurations on every
  query of the 20-query check and of the 300-query run.

Settings `rptg_count` (default true), `rptg_count_host` (8), `rptg_count_floor` (2e6) are per connection, so
an interleaved runner must set `rptg_count` in every configuration (the first run of the 300-query experiment
left it false after the transfer-only configuration and measured nothing). Patch: `hosts/kuzu/rptg_stage_g.patch`
(stage E plus this; the symlink `third_party/rptg` is created by hand, see `hosts/kuzu/README.md`).

Run: `scripts/kuzu_count_300.sh` -> `results/kuzu_count_dblp300.csv` (`qgen_dblp_300.txt`, the sample of the
PostgreSQL and DuckDB counting runs; KNO / KR2 with `rptg_count=false` / KRC with `rptg_count=true`, interleaved,
1 warm-up + 3 reps, median, 8 threads, 10 s, 2 shards, 16 GB buffer pool, five unrelated training jobs on the
machine at about one core each).

Results (`results/kuzu_count_dblp300.csv`, `scripts/analyze_host.py --base KNO --timeout 10`): 282 queries evaluated
(18 baseline failures excluded: 15 timeouts and 3 buffer-pool-full errors at the timeout), counts identical across
the three configurations on every finished query, noise floor (KNO rep vs rep) < 0.8x 7.1%, > 1.25x 14.9%.

| config | < 0.8x | < 0.5x | > 1.25x | > 2x | geomean | P5 | P50 | P95 | total (282) | failures | fixed / new |
|---|---|---|---|---|---|---|---|---|---|---|---|
| KNO (no mask) | | | | | 1 | | | | 87.7 s | 18 | |
| KR2 (RPT-G transfers, `rptg_count=false`) | 3.2% | 0.0% | 55.0% | 41.1% | 2.04 | 0.87 | 1.41 | 10.0 | 66.8 s | 15 | 3 / 0 |
| KRC (RPT-G transfers + counting) | 3.5% | 0.0% | 75.2% | 63.8% | 4.65 | 0.85 | 4.92 | 46.0 | 6.4 s | 0 | 18 / 0 |

- Over all 300 queries with failures counted at 10 s: 267.7 s (KNO) -> 233.5 s (KR2) -> 9.0 s (KRC), 29.8x. The
  18 baseline failures take 6-127 ms under KRC, except q2934 (a buffer-pool failure at 10.4 s; 1.9 s counted).
- By baseline time (geomean KRC, share < 0.8x): 0-20 ms n=63 1.01 (10%), 20-100 ms n=88 3.06 (3%), 100-1000 ms
  n=110 9.94 (1%), > 1 s n=21 48.5 (0%). KRC against KR2 per query: 2.99 (geomean); 121 queries more than 2x.
- Regressions (10 queries, 3.5% against 7.1% noise): nine with a baseline below 35 ms (median loss 4.9 ms), one
  241 -> 314 ms (q1720). No new failures.
- The gain is smaller than in PostgreSQL (5.73) and DuckDB (11.9) on the same sample because Kùzu's baseline is
  already the fastest of the three (87.7 s evaluated against 146.7 and 89.3 s, with 18 failures against 46 and 16).
- A first run was discarded: `Value::toString` prints doubles with six decimals, so the side queries used rounded
  thresholds (`pu < 0.000723822` became `pu < 0.000724`) and 14 of 300 counts differed from the host's. The
  renderer now prints doubles with `%.17g`; the 14 queries were re-checked one by one before the rerun.

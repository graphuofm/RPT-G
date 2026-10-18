# Where do RPT-G's gains go? (2026-09-29)

Question: why is RPT-G's average gain small in the prototype (geomean 1.02 / 1.03) and in LadybugDB / DuckDB,
but large in Kùzu (1.92 / 2.19)? Tool: `scripts/diagnose_gain.py RUN.csv` (per-query output `RUN.diag.csv`).

## Method

Per query, from the phase times of the prototype (mean over reps):
- floor = predicate scans + planning (`init_ms` of M0), paid by every method;
- ideal = floor + min(join of M0, join of M4): the query as if full reduction were delivered for free;
- headroom = M0 / ideal — the most any transfer scheme can gain on that query;
- achieved = M0 / M6; queries with headroom >= 1.1 are *captured* (achieved >= sqrt(headroom)), *eaten*
  (M6's transfer time >= half the headroom gap), or *missed* (otherwise: M6's join stayed slow).
- oracle = per query the fastest of M0, M4, M6 (what perfect decisions between "no transfer", "full
  reduction" and RPT-G would achieve).

## Finding 1: under a good join order the workload has almost no headroom

Full Q-GEN, host-like default order (greedy on **exact** candidate-set sizes):

| | DBLP (4,889 q) | LiveJournal (3,859 q) |
|---|---|---|
| queries with headroom < 1.1 | 86.8% | 87.0% |
| geomean headroom | 1.11 | 1.07 |
| geomean achieved by RPT-G | 1.02 | 1.03 |
| total time M0 / RPT-G / oracle / ideal | 726 / 653 / 604 / 604 s | 1,896 / 1,712 / 1,673 / 1,693 s |
| share of the oracle's saving that RPT-G obtains | 60% | 82% |

- Even with free full reduction, 87% of the queries cannot become 10% faster. Q-GEN draws selectivities
  log-uniformly down to 1e-5, so most queries start from a tiny candidate set and the join is cheap; the
  prototype's default order starts from the smallest set by *exact* size — an optimizer no host has.
- Headroom concentrates in few queries: headroom >= 3 on 3.0% (DBLP) / 1.0% (LJ) of the queries, where
  RPT-G achieves 1.9–4.2× (DBLP) and 4.1–13× (LJ).

## Finding 2: what RPT-G leaves on the table

- DBLP: 645 queries with headroom >= 1.1: 187 captured, 152 eaten, 306 missed. The missed queries lose
  40 s of the 120 s headroom; on a third of them (about 100 queries) full reduction (M4) is > 10% faster
  than RPT-G. M6's decisions there: SKIP-useless 47%, SKIP-budget 22% of the planned transfers; M6's join
  is 0.98× M0's, M4's join 0.16× — the budget (or the join-work estimate behind it) is too conservative on
  these queries. To investigate: benefit estimates vs measured join savings on the missed set.
- LJ: 500 queries with headroom >= 1.1: 253 captured, 146 eaten (6 s), 101 missed (16 s); capture median 0.53.
- "Eaten" queries are short (median 7 ms DBLP): the transfer is cheap in absolute terms but so is the query.

## Finding 3: gain = headroom that the host optimizer leaves; RPT-G makes the time independent of it

Same 1,000-query DBLP sample, prototype v8, M0/M4/M6, 3 interleaved reps; the only difference is the
join order: greedy on exact candidate-set sizes vs greedy on a constant 10% selectivity per predicate
(what Kùzu assumes for every range predicate). `results/order_{exact,est}_dblp1k.csv`.

| order | queries with headroom >= 1.1 | geomean headroom | RPT-G geomean | RPT-G < 0.9x | total M0 / RPT-G / ideal |
|---|---|---|---|---|---|
| exact sizes | 12.2% | 1.10 | 1.035 | 10.6% | 153 / 144 / 143 s |
| constant 10% | 31.6% | 1.43 | 1.339 | 6.9% | 211 / 144 / 142 s |

| LJ exact sizes | 13.2% | 1.21 | 1.079 | 7.4% | 378 / 305 / 282 s |
| LJ constant 10% | 29.4% | 1.48 | 1.321 | 4.9% | 460 / 282 / 263 s |

- Totals above are over the queries that every method finished. Over all 1,000 queries with a timeout counted
  as 10 s (the paper's numbers, `paper/figgen/numbers.json:order_quality`): DBLP M0 376 -> 490 s (+30%),
  Yannakakis 388 -> 387 s, RPT-G 358 -> 356 s; LJ M0 2,632 -> 2,993 s (+14%), RPT-G 2,367 -> 2,453 s (+4%).
  RPT-G removes the dependence on the estimate. Capture (log achieved / log headroom) median 0.88 (DBLP est).
- Headroom >= 10 under the estimate order: 4.9% of the queries, RPT-G geomean 37.7x there.
- So the small average gain in the prototype's Q-GEN runs is a property of the exact-size default order,
  not of RPT-G; Kùzu's 1.92-2.19x gains come from the headroom its 10% estimates create.

## Finding 4: the join phase lost gains that online filtered adjacency recovers (v8)

On the full DBLP Q-GEN (v5b), 306 queries with headroom missed 40 s: the budget or the plan-time
BitmapEdgeScan criterion kept the join scanning whole adjacency lists (M4's join 0.16x of M0's, RPT-G's
0.98x). v8 builds a step's filtered adjacency as soon as the entries it scanned reach the build cost
(ski rental, at most 2x the better choice): the six worst missed queries go from 0.93-2.8 s to 0.1-0.67 s
(M4: 0.10-0.50 s), and on the 1k sample "lost in missed" drops to 0 s.

## Finding 5: in PostgreSQL the predicate scan is not a sunk cost

PostgreSQL's plans evaluate a vertex predicate by index lookups on the vertices the join reaches, so
materializing a whole predicate set (SPI, ~0.7 us per row) can cost more than the query (q715: 12 ms query,
60 ms to materialize `pu < 0.24`). First pg_rptg version: geomean 0.73, 39% of queries < 0.8x. Fixes: (1)
pre-screen on the host's histogram estimates, (2) evaluate only the predicates whose information an
admitted transfer carries, (3) charge `rptg.pred_cost` per predicate row in the pre-screen, (4) calibrate
beta to the host (PG nested-loop step ~60 ns vs transfer entry ~4 ns -> beta 10). Worst cases back to parity.

## Other contributors (from the host integrations)

- Fixed per-transfer costs in the hosts (~1 ms per pipeline in Kùzu, ~0.3 ms per thread per pipeline in
  LadybugDB 0.21, filter operators in DuckDB): decisive on queries < 20 ms.
- Kùzu's rel scan costs per 2,048-node vector of source nodes: a reduction that leaves the sources spread
  over the same vectors saves little (LJ q1108) — the benefit model needs a touched-vectors term.
- DuckDB: decisions at plan time cannot see the min-max locality that RPT+'s cascade filters exploit.

## Finding 6: cyclic patterns behave the same (prototype v8, 1,000 cyclic queries per order, DBLP)

| order | static semi-mask < 0.9x | Yannakakis (spanning tree) | arc consistency (M5) | RPT-G < 0.9x | RPT-G geomean | noise |
|---|---|---|---|---|---|---|
| exact sizes | 49.2% | 71.3% | 83.3% | 7.5% | 1.010 | 6.7% |
| constant 10% | 41.6% | 59.7% | 78.2% | 4.5% | 1.171 | 1.7% |
| LJ, exact sizes (610 evaluated; M0 timeouts excluded) | 67.0% | 80.0% | 89.3% | 10.5% | 1.038 | 10.8% |

LiveJournal (results/cyc_lj.csv): 0 count mismatches; M6 by shape between 0.99 (triangle) and 1.12
(triangle with two tails); M5 fixes 13 timeouts but costs 931 s total against 556 s for M0; M6 514 s.

In Kùzu, cycles leave far more headroom than trees: Kùzu closes a cycle with a multi-key hash join over
full node scans, so its plans for cyclic patterns are poor. First 295 DBLP cyclic queries
(results/kuzu_dblp_cyc.csv, partial): RPT-G geomean 4.80x, 0.4% < 0.8x (noise 2.3%), total 215 -> 115 s;
Kùzu's semi-mask 2.46x with 3.5% < 0.8x. Two queries hit buffer-pool exhaustion in KSM and KR2 (counted as
timeouts); counts agree everywhere else.

All five methods return identical counts on all 1,000 queries. Arc consistency (the candidate filter of
subgraph-matching algorithms) is the worst: it iterates pushes to a fixpoint regardless of cost.

## Finding 7: PostgreSQL under its own plans leaves no headroom

PG 19 plans with histogram estimates (accurate for our range predicates) and index nested loops over the
adjacency btree. `results/pg19_rptg_dblp300.csv` (execution-time pre-screen version): geomean 0.96, total
152.2 -> 153.5 s; >= 100 ms: 1.00-1.01; < 20 ms: 0.93 with 17% < 0.8x (noise 3%) — the fixed cost of the
pre-screen (SPI planning of each predicate) and of copying the plan. Next version moves the pre-screen to
plan time on PG's own row estimates (create_upper_paths_hook), so a query with no admitted transfer keeps
its plan untouched.

## Finding 8: in relational hosts the gain was lost in the benefit model (2026-09-29, evening)

Random-order runs in DuckDB and PG first showed per-pair speedups of 0.99 (DuckDB, first 8 queries) and 1.14
(PG, 49 queries) although the baselines' slowest orders were 7-40x their fastest: the headroom was there, the
capture was not. Four modelling errors, found on DuckDB q2061 (hub predicates, 148M-row intermediate):
1. Every vertex was assumed restricted in every plan node; an edge-table scan without a filter produces all
   of its rows, and a predicate restricts only nodes that contain its vertex-table copy. The 148M-row node
   joined the hub vertex *before* its predicate and was also wrongly excluded as "already restricted".
2. Stars around hub sets: rows need sum_v prod_e deg_e(v), i.e. the second degree moment (l2 norm, cf.
   LpBound), not |B| * avgdeg^k. The core now keeps sum dout^2, sum din^2, sum dout*din per candidate set.
3. PG's inner index scans of nested loops produce no rows of their own; counting them made a single-edge
   query admit a useless transfer (+6 ms).
4. The pre-screen used size estimates with average degrees, so hub sets always looked cheap to ignore. Now
   two levels: an optimistic bound (the largest degree sums a set of that size can have; no predicate is
   evaluated if even this fails), then exact stats of the small predicate sets (<= 50K DuckDB / 20K PG rows).
After the fixes: q2061 1.75 -> 0.98 s in DuckDB; PG bad order of q42 111 -> 65 ms; smoke tests at parity.

## Finding 9: DuckDB under its own plans has no headroom (forced-transfer check, 2026-09-30)

`scripts/duckdb_force_300.sh` -> `results/duckdb_force_dblp300.csv`: every useful transfer forced (beta 1e6, no fixed
or predicate cost in the model): geomean 0.82, 46.8% < 0.8x, total 104.9 -> 102.8 s (-2%); >= 1 s queries 1.05x.
The calibrated pre-screen (dkr) admits a transfer on 14/300 queries: 0.999 geomean, 105.1 s. On the 286 queries
it leaves untouched (same plan, verified with EXPLAIN), 5.8% are < 0.8x: that is the between-process noise
(the within-process rep-vs-rep floor says 4.2%). The 8 evaluated queries with a transfer: 1.13x, none < 0.8x.

## Finding 10: PostgreSQL under random orders — four fixes (pg_rptg v3, 2026-09-30)

First 898 pairs of the v2 robust run: 1.43x per pair, 9.8% < 0.8x, 96 of 145 timeouts left. Diagnosis:
1. Short queries (2-3 ms, count 0) paid 5-10 ms of *plan-time* pre-screen (the SPI-materialized small sets of
   level 2, e.g. `pu < 0.023` = 7,105 random heap fetches = 3 ms). Planning 2.2 -> 9.5 ms, execution unchanged.
2. q431 (14 hubs, count 0): PG estimated cost 1,140 for a 13 s plan (avg-degree join estimates). The core
   admitted nothing because the configuration model treated a set reduced by a transfer from x along e as
   independent of x (54 edges instead of 4,200) -> fix: per-edge undo (`hundo`), and the pre-screen's unconstrained
   vertices had second moments 0 (moment correction clamped to 0.1) -> fixed.
3. Filter cost of inner index scans was charged as |E| rows -> now the rows their join looks up; vertex scans with
   a predicate: the predicate's rows.
4. q2568 (31,793 matches): after the transfers, 3.8M rows still reached v4 by one PK index probe each (v4's
   predicate applied only at its vertex join) -> self filters: v4's own bitmap on the e3 scan (10.7 s -> 0.8 s).
Plus: column indexes (sorted column + degree prefix sums: exact stats by binary search, materialization in O(rows))
replace SPI for simple predicates; an empty candidate set short-circuits the plan (q431: 12.7 s -> 2 ms).
v3, first 510 pairs: 4.68x per pair, 1.6% < 0.8x, timeouts 145 -> 58 (0 new), robustness factor 32.7 -> 7.4.
Final v3 robust run (`results/pg19_dblp_robust.csv`, 100 queries, 1,918 pairs): 4.83x per pair, 1.6% < 0.8x,
27.8% > 10x, timeouts 462 -> 142 (322 fixed, 2 new), factor 43.2 -> 10.7, slowest-order sum 462 -> 169 s; 131 of
the 142 remaining timeouts are 9 queries with 1-10M matches (output-bound at ~1 us per joined row).
DuckDB v4 (column indexes) partial, 1,000 pairs: 1.51x per pair, 3.0% < 0.8x (v3 without column indexes: 1.26x,
16.7% — the 10 ms side-query pre-screen), slowest-order sum 50.7 -> 8.9 s, factor 5.25 -> 2.77.
DuckDB v4 own plans (`results/duckdb_rptg_dblp300.csv`, 284 evaluated): 1.00x, 78.0 -> 75.9 s, 3.5% < 0.8x (within-
process floor 1.1%). EXPLAIN with RPTG_DEBUG: 10/300 queries admit a transfer; those (9 evaluated) 1.34x, none
< 0.8x, max 4.87x; the 275 untouched-plan queries: 3.6% < 0.8x = between-process noise.

## Finding 11: where the time goes, and counting instead of enumerating (2026-10-01, idle machine)

Time split of the v8 tree workloads (RPT-G): predicate scans 3% (DBLP) / 14% (LJ), transfers 0.3% / 1.9%, join
97% / 85%. Queries with >= 1M matches are 31% (DBLP) / 61% (LJ) of the queries and 97% / 93% of RPT-G's time; after
full reduction this join work is all output enumeration, which no transfer removes. For count(*) on tree patterns,
the forward pass over the counting semiring (same push/pull choice) computes the count without enumeration.
v9 (`count_{dblp,lj}1k.csv`, ski-rental switch at the exact counting cost):
- DBLP 1k (noise 0.4%): M6 1.06x total / 1.04 geo; C0 14.6x / 1.29; M7 14.7x / 1.29, 3.9% < 0.9x.
- LJ 1k (noise 1.7%, 217 baseline timeouts): M6 1.25x / 1.08; C0 2.1x / 1.12 (2.6% < 0.5x); M7 2.3x / 1.19
  (0.5% < 0.5x), all 217 baseline timeouts finish. Transfers make counting cheaper and safer on LJ.
v10 adds predicate column indexes for every method (DBLP 200 q: predicate time 356 -> 14 ms), which exposed a
~15 us fixed cost of RPT-G's plan-time edge scans on 50-us queries -> tiny-query guard (estimated join < 20K
entries: no transfer phase, no plan-time edge scan).

## Finding 12: measuring on an idle machine exposed hidden fixed costs (v10-v15, 2026-10-01)

With predicate column indexes (v10, all methods), queries drop to ~50 us-1 ms and RPT-G's fixed costs became
visible: (1) plan-time filtered adjacency built without comparing saved scans with its price (incl. the rank table
over all bitmap words) -> cost-based rule (v12); (2) the online ski-rental build did not know how much of the level
remained, nor that a high hit rate leaves little to save, and it built lists for full source sets that the level
visits only partly -> extrapolation from the outer loop's progress, hit-rate discount, >= 1 visit per source
(v13); (3) counting used n-sized arrays (page faults, cache misses: ~35 ns per cost unit vs 1.3 ns for enumeration)
and pushed counts from unconstrained leaves -> rank-indexed O(|B|) arrays and degree lookups (v14/v15).
v15 on the 1k samples (idle machine, `count15_{dblp,lj}1k.csv`, all counts equal to M0):
| | DBLP total | DBLP geo | DBLP < 0.9x | LJ total | LJ geo | LJ < 0.9x | LJ < 0.5x |
| noise | | | 0.4% | | | 1.3% | |
| M6 RPT-G | 1.05x | 1.06 | 1.9% | 1.25x | 1.11 | 6.0% | 0.6% |
| C0 counting only | 20.1x | 1.48 | 1.7% | 3.3x | 1.56 | 3.7% | 0.6% |
| M7 RPT-G + counting | 20.3x | 1.53 | 2.1% | 3.9x | 1.76 | 6.1% | 0.6% |
M7 finishes all 20 DBLP and 217 of 219 LJ baseline timeouts. Open: M6's remaining LJ regressions (benefit
estimation errors of single pushes, e.g. 12K vertices into the full set for 40 ms without join savings).

## Finding 13: RPT+'s mechanisms in graph form (v16/v17, 2026-10-05)

Implemented behind flags (`prototype/VERSIONS.md`): cascade membership tests (two-level word summary + range clamp,
galloping over empty words; lazily built when the expected scan pays for the pass over the words), push abort
(random source order, extrapolated survival > tau_sel before tau_prog), reach-weighted pilot (survival measured on
vertices the join reaches through its own entering edge; rescales the budget of transfers costlier than 16K
entries), most-selective-sibling-first order, and M8 (upfront counting when the enumeration estimate exceeds
count_far x the counting cost). All counts equal M0; test_api 0 mismatches.
DBLP 1k (`abl17_dblp1k_{A..D}.csv`): no measurable difference between A and D for M6 (geo 1.07, 1.4-1.7% < 0.9x)
or M7 (17.5-19.1x total, geo ~1.5): RPT-G executes only ~130 transfers over the 1,000 queries (1.7e7 entries, ~70 ms
in total), so there is nothing left for the mechanisms to save on this graph. M8 was slower than M7 (11.9 vs 8.8 s)
for two reasons, both fixed in v17b: the patience rule (enumerate up to 4C when the estimate favoured enumeration)
cost 3C on 150 queries whose estimate was wrong; the upfront estimate cost ~1 us on 17-us queries (18.5% "regressions"
below 50 us) -> guarded by min_work.
v17b DBLP config D, M7 vs M8 (`abl17b_dblp1k_D.csv`, run alongside the LJ ablation): M7 14.0x / geo 1.47 / 3.3% < 0.9x,
M8 14.1x / 1.50 / 2.9%: the upfront decision is now at least as good as pure ski rental.
LJ 1k (`abl17_lj1k_{A..D}.csv`, all counts equal to M0): A -> D changes nothing for M6 (geo 1.10-1.11, 6.6-7.2% < 0.9x)
or M7 (geo 1.62-1.66); the reach pilot skipped 44 transfers and the push abort 10, without measurable effect.
Operation counts explain why: M6's transfer phase visits 5.3e8 adjacency entries over the 1,000 queries (4.5 s)
against 1.4e13 in the join (349 s), i.e. 1.4% of the time. RPT+'s transfer-side mechanisms have nothing left to
save on graphs once the budget prunes the plan; the remaining regressions and the remaining headroom are both in
the join (enumeration vs counting, filtered adjacency). Cascade scans help the counting pass a little (M7 total
2.7x -> 3.2x on LJ). Decision: keep the mechanisms as flags; the paper reports them as a measured negative result
with the operation counts.
v17b LJ config D (`abl17b_lj1k_D.csv`): M7 3.8x / geo 1.75 / 7.4% < 0.9x; M8 3.9x / geo 1.84 / 6.3%. All 36 upfront
decisions were right (M7 0.8 s -> M8 0.2 s on those queries, geo 2.34x), none hurt. M8 is the counting method of
record; recommended flags: --col-index 1 --min-work 20000 --word-cost 0.3 --extrapolate 1 --cascade 1 --count-far 8.

## Finding 14: method order inside a repetition contaminates 10-us timings (2026-10-05)

`final18_dblp1k.csv` (methods interleaved as M0,M3,M4,M6,M7,M8) showed M6 at 41% < 0.9x although its total time
was below M0's. On the 440 queries with M0 < 0.1 ms, median init time by method: M0 7.0 us, M3 7.0, M4 8.0, M6 11.1,
M7 7.2, M8 7.0: only the method that runs right after M4 (whose full reduction allocates and frees large bitmaps)
pays ~4 us of allocator/page-fault cost; 55% of M6's extra time on those queries is this init difference, the
rest is the same carry-over in transfer/join. Harness fix (v18b, main.cpp): a run below 1 ms is repeated and the
second run kept; every method is treated alike and the total time is unaffected. Lesson for the protocol section:
interleaving methods within a repetition must be paired with a per-method warm run at the microsecond scale.

## Operation counts of the final configuration (v18, 1k samples, queries every method finished)

LJ, 771 queries, output 2.15e13 matches:
| method | transfer entries | transfer ms | scanned entries | counted output | join ms | total ms |
| M0 | 0 | 0 | 5.11e10 | 2.15e13 | 389,372 | 390,154 |
| M3 static semi-mask | 1.9e10 | 112,689 | 4.51e10 | 2.15e13 | 373,098 | 486,577 |
| M4 Yannakakis bitmap | 1.03e11 | 462,656 | 1.63e10 | 2.15e13 | 292,948 | 756,425 |
| M6 RPT-G | 2.79e8 | 2,474 | 1.82e10 | 2.15e13 | 285,864 | 289,136 |
| M8 RPT-G + counting | 2.79e8 | 2,427 | 6.14e9 | 1.84e12 | 103,099 | 106,309 |
DBLP, 979 queries, output 1.07e12: M0 scanned 1.39e10 / join 175 s; M6 transfer 1.18e7 entries (143 ms), scanned
1.08e10, join 165 s; M8 scanned 6.0e8, counted 2.6e10, join 8.6 s (total 8.7 s).
Reading: the baseline's join work is almost entirely output (counted 2.15e13 vs scanned 5.1e10 on LJ); RPT-G removes
64% of the scanned entries with 0.5% of their cost in transfers (2.8e8 vs 3.3e10 removed); the static semi-mask
spends 1.9e10 entries to remove 6e9, the full reduction 1.0e11 to remove 3.5e10; counting replaces 2.15e13 counted
output entries by 1.8e12 (the counting pass's own output-sized arithmetic is 10x smaller) and cuts the join from
286 s to 103 s.
Extension (v18b, `final18b_lj1k.csv`): repeating only sub-millisecond runs is not enough on LJ. Same 773 queries: M6
regresses 6.1% when it runs after M0 (v15 order) and 23.3% when it runs after M4 (v18b order), with identical join
work (ratio 1.00); the regressions sit at 1-100 ms and the extra time is in transfer and join, i.e. cache state left
by M4's 1e11-entry reduction. Along the run order M4 -> M6 -> M7 -> M8 the regression rates fall 23.2 -> 11.5 -> 6.9%.
Protocol of record (v18c, `--warm-each 1`): every measured run is preceded by a run of the same method, for every
method alike; the final tables come from `final18c_*`.
Final DBLP (v18c, `final18c_dblp1k.csv`, 980 evaluated, noise 1.4%, all counts equal): M3 geo 0.16 / 80.5% < 0.9x;
M4 0.04 / 92.6%; M6 1.05 / 4.6% / total 1.05x; M7 1.55 / 3.0% / 20.5x; M8 1.60 / 2.7% / 20.9x, all 20 baseline
timeouts finished. Operation counts: M6 transfers 1.18e7 entries (140 ms) and removes 3.1e9 of 1.39e10 scanned;
M8 scans 6.0e8 and counts 2.6e10 instead of 1.07e12 (join 8.7 s vs 179 s).
Final LJ (v18c, `final18c_lj1k.csv`, 775 evaluated, noise 2.6%, all counts equal): M3 geo 0.17 / 83.7%; M4 0.05 / 93.4%;
M6 1.07 / 20.0% / 1.31x total; M7 1.77 / 7.0% / 4.0x; M8 1.87 / 5.9% / 4.0x, 224 of 224 baseline timeouts finished.
Operation counts (769 queries, output 2.14e13): M6 transfers 2.79e8 entries (2.4 s) and removes 3.0e10 of 4.74e10
scanned; M8 scans 5.9e9 and counts 1.8e12 (join 100 s vs 378 s). M6's 20% < 0.9x persists with per-method warm
runs (6.0% in the v15 run without M3/M4 in the process) -> tested directly (order_*.csv in the scratchpad).
Order test (300 LJ queries, v18c, --warm-each 1, three method lists in separate processes; `scratchpad/order_*.csv`,
92 queries finished by all three): M6 < 0.9x = 7.6% with methods M0,M6,M8; 19.6% with M0,M4,M6,M8; 17.4% with
M0,M3,M4,M6,M8, while the sums (27.35 / 26.94 / 27.03 s) and per-query medians (ratio 0.999) are identical: M4's
allocation churn widens the timing noise of every later method, and queries near 1.0x cross the 0.9x line.
Protocol of record: the full-reduction baselines (M3, M4) run in their own process group (`final18c_*_base.csv`),
RPT-G and the counting methods with M0 in another (`final18c_*_main.csv`).
Protocol of record, final numbers (`final18c_*_main.csv` / `_base.csv`, 2026-10-06):
DBLP (971 evaluated, noise 1.8%): M3 0.17 / 80.1%; M4 0.05 / 93.0% (base group, noise 2.6%); M6 1.07 / 2.5% / 162 -> 153 s;
M7 1.50 / 2.3%; M8 1.53 / 2.9% / 162 -> 12 s, 29/29 timeouts. LJ (769 evaluated, noise 1.8%): M3 0.17 / 84.6%;
M4 0.05 / 93.6% (base group, noise 3.9%); M6 1.11 / 6.6% / 434 -> 343 s; M7 1.74 / 5.7%; M8 1.82 / 5.6% / 434 -> 123 s,
222/231 timeouts. All counts equal M0 in every run. The paper's Table proto and §6.2/§6.6 use these numbers.

## Finding 15: why RPT+'s mechanisms do not carry over, and what graphs need instead (2026-10-06)

Structural reasons, from the operation counts:
1. In a relational engine the reduction (a Bloom-filter build and probe, a few ns per tuple, block skipping by
   min-max) is far cheaper per tuple than the join (hash build and probe, tens of ns); RPT+'s cascade filters and
   dynamic pipelines exploit that gap. In a graph engine the transfer and the join are the same primitive, an
   adjacency scan at ~4 ns per entry: there is no cheap/expensive pair to cascade, and a transfer that is not worth
   its entries cannot be made worth them by doing it faster. The budget prunes 90% of the planned transfers for
   this reason, and the rest is ~1% of the time.
2. Hubs. LJ: the top 1% of vertices hold 17% of the edges, the top 10% hold 57%. A transfer into a set that
   contains hubs cannot prune them (a hub has a neighbour in any set of moderate size), and the join reaches
   vertices in proportion to their degree. Survival counted in vertices therefore overestimates the benefit:
   the 20 costliest transfers of the LJ sample (half of all transfer time) are pushes from 10%-selective sets
   into the full set that cut it to 15-25% of its vertices but leave the hubs, so the join saves nothing
   (q1602: 40 ms push, identical join work). M6's remaining LJ regressions sit on queries without a hub predicate
   but with such a transfer (34.9% of them regress; 2.1% of the queries without a transfer). Fix (v19,
   `--deg-surv 1`): per-set log2-degree histograms; the benefit uses the share of the target's degree sum that
   survives, sum_d h(d) * (1 - (1 - rho)^d), so hubs count with their edges.
3. Undirected graphs (DBLP): out- and in-degree coincide and N_p is symmetric, so push and pull cost the same for
   the same set and the direction choice reduces to choosing the smaller degree sum; DBLP's degree distribution
   is also flat (top 1%: 11% of the edges), which is why its transfer decisions were already clean (2.5% < 0.9x).
v19 (`final19_*_main.csv`, --deg-surv 1) vs v18c on the same queries: DBLP M6 < 0.9x 2.4% -> 1.6% (geo 1.07 both);
LJ M6 6.6% -> 4.4% (geo 1.11 -> 1.09) but M8 geo 1.82 -> 1.57, total 123 -> 185 s: the transfers that
degree-weighted survival rejects do not help enumeration (the hubs stay) but do help counting, whose cost is
sum |B_x| + degree sums and whose arrays shrink with the vertex count; without them M8 falls back to the level of
counting over unreduced sets (C0: 1.56). v20 (--count-benefit 1): for a query that may count, the benefit of a
transfer is max(enumeration benefit, reduction of the counting cost C computed by count_cost on the shrunken set).

## Finding 16: the push itself was 18x slower than its cost model (2026-10-06)

Audit of the 17 executed pushes into (near-)full sets on the LJ regression set, with budgets logged: 14 are cheap
(1.7K-11K entries, < 2 ms) and save 20-700x their cost in join scans, yet their queries are 2-6 ms slower; the
three large ones (0.94M-1.19M entries) took 56-74 ms = 73 ns per entry against the model's 4 ns. Cause: v11's
"statistics on the fly" read dout[u] and din[u] for every newly marked vertex in the random order in which the
adjacency lists produce them (two 19 MB arrays on LJ, a cache miss each); the earlier ordered pass after the push
(recompute_D) is sequential. v21 restores the ordered pass (now also filling the degree histograms).

## Finding 17: three accounting errors in the benefit model (push traces, 2026-10-06)

Per-phase traces of three regressing LJ queries (q2494, q4954, q1039):
1. The cap counted the scan of the level that enters y as saveable. q2494: push 0>1 cut B_1 from 4.8M to 3,033
   and the join's scanned entries from 5.8M to 1.0M, but the join took 18.5 instead of 19.5 ms: the entering
   level scans the previous vertex's adjacency whatever B_y is; only later levels shrink. For a vertex entered
   at the last level the modelled benefit is almost entirely fictitious. v22: cap[y] = scans of the levels after
   the entering one (the start vertex keeps the total).
2. A transfer entry costs ~5x a join entry: the push scans at 17-18 ns per entry (two random bitmap accesses per
   neighbour on 600 KB bitmaps), the baseline's join at 3.4 ns (sequential). beta = 1 assumed equal unit costs;
   q4954's push saved 2.9M join entries (~10 ms) for 22 ms of its own. beta ~0.25 on LJ-size bitmaps, or an
   online calibration of the two unit costs.
3. A cascade jump in the join probe costs ~100 ns, not the modelled 6 entries (24 ns): q2494's reduced join did
   1.0M counted units in 18.5 ms. v22: skip_unit 24.
beta 0.25 on the LJ regression set (v22): M6 21% -> 6% < 0.9x, geo 0.94 -> 1.00, none below 0.5x. M8 still regressed
20% (38% at beta 1): 38 of its queries executed transfers that M6 did not (admitted by the counting benefit) and 37%
of those regressed, because the query enumerated in the end. v23: the counting benefit applies only when the
estimated enumeration is at least the counting cost (counting plausible).

## Finding 18: the degree histograms made initialization 100x slower for large predicate sets (2026-10-06)

v19 built the per-set degree histogram in init_states by reading dout[v] and din[v] for every member of a predicate
set produced by the column index, i.e. in value order, which is random vertex order: pu < 0.9 (4.3M members) cost
~900 ms of cache misses for every method including M0 (q3800: init 7.3 -> 916 ms). Besides inflating totals, it
compresses the per-query ratios of small queries toward 1, so the regression rates of v19-v23 are not comparable.
v24: uniform and label predicates take the global histogram scaled by |B|/n (independent of degree by construction);
a pd predicate selects the top-k vertices by degree, whose histogram is the top-k slice of the sorted degree
arrays (sequential); sets produced by transfers keep the exact histogram from the ordered pass. The v22 and v23
runs were stopped and are rerun as v24.
v24 (`final24_*_main.csv`) vs v18c on the same queries: LJ M6 < 0.9x 6.6% -> 2.5% (noise 1.2%), < 0.5x 0.9% -> 0.3%,
geo 1.11 unchanged; M8 geo 1.82 -> 1.73 (the counting benefit is also scaled by beta 0.25 although a counting entry
costs about as much as a transfer entry); DBLP unchanged (M6 geo 1.08, M8 1.50). Profiling set, DBLP: transfer
8.4 ns/entry, join 14.7 ns/scanned entry (beta ~1 would be right there); LJ: ~17 vs 3.4 ns (beta ~0.2): beta must be
calibrated per graph, best online from the measured unit costs.

## Finding 19: online beta from average unit costs admits too much (profiling sets, 2026-10-06)

v25 `--beta auto` = (join ns per scanned entry) / (transfer ns per entry), both pooled over the completed runs of
all methods. On LJ the pooled transfer cost is 5.8 ns per entry because small pulls dominate the count, while the
pushes that cause the regressions cost 17-23 ns per entry; the pooled join cost is ~10 ns because probing doubles
the cost per scanned entry (M0 6.4 ns, M6 13.5 ns). The ratio comes out near 2, the budget admits 76 instead of 42
transfers on the light LJ set, and M6's regressions rise from 5.2% to 7.2%; M8 is unchanged (geo 1.48). A unit cost
per operation kind and target size would be needed; the fixed beta 0.25 (the measured cost of a push into a large
bitmap) stays the setting of record. Light profiling sets (queries/profile_{dblp,lj}.txt, 240 and 194 queries,
one M0 run under a minute) are the development loop from here on.
Decision (2026-10-06): configuration of record = v25 binary with --deg-surv 1 --count-benefit 1 --beta 0.25
--beta-count 1 (`scripts/final_run_v25.sh`). Light profiling sets vs v24: DBLP M6 < 0.9x 2.5% -> 1.7%, M8 5.0% ->
2.9% (geo 1.97); LJ M6 5.2% -> 4.6%, M8 8.2% -> 7.2% (geo 1.47 both); all counts equal. Final 1k runs:
`final25_{dblp,lj}1k_main.csv`; the base group (M3, M4) stays `final18c_*_base.csv`.

## Final prototype numbers (configuration of record v25, `final25_*_main.csv`, 2026-10-06)

DBLP (979 evaluated, noise 5.5% in this run): M6 geo 1.07 / 2.7% < 0.9x / 0.0% < 0.5x / 174 -> 165 s;
M8 1.57 / 4.5% / 0.3% / 174 -> 9.1 s (19.3x), 21/21 baseline timeouts finish.
LJ (776 evaluated, noise 3.1%): M6 1.12 / 3.0% / 0.4% / 441 -> 346 s; M8 1.78 / 6.3% / 1.2% / 441 -> 116 s (3.8x),
222/223 timeouts finish. Operation counts (776 queries, output 2.35e13): M6 transfers 1.45e8 entries (0.7 s),
scanned 8.34e10 -> 2.48e10; M8 scanned 7.3e9, counted 2.2e12 instead of 2.35e13, join 440 -> 114 s.
Against v18c on the same queries: LJ M6 < 0.9x 6.6% -> 3.0% at the same geo 1.11; M8 geo 1.82 -> 1.72
(beta 0.25 also withholds some transfers that counting profits from; beta_count 1 did not recover them).

## Finding 20: an upfront counting decision must not skip the transfers (v26, 2026-10-06)

v25's M8 skipped the transfer phase whenever it decided upfront to count (E > 8C). On 8 of the 143 queries where
that fired (25 DBLP, 118 LJ), M8 then lost up to 20x against the ski rental M7, which had run the transfers first:
LJ q1648 M7 39 ms vs M8 825 ms (an 8.2e8-entry edge scan and a counting pass over unreduced sets), q3578 92 vs 861 ms.
v26 runs the transfers under the counting benefit alone (benefit = reduction of the counting cost at beta_count, the
enumeration benefit is 0) and then counts. On the upfront subsets (M7,M8, one rep, loaded machine):
DBLP 25 queries, M8 v25 -> v26 geo 1.23, faster > 20% on 10, slower on 0, edge-scan work 2.1e6 -> 3.5e5;
LJ 118 queries, geo 1.09, faster > 20% on 18, slower on 5 (worst 0.63: q4726 881 -> 1407 ms, still ahead of M7's
2001 ms), M8 total 60.3 -> 59.2 s, M8 slower than M7 by > 20%: 7 -> 0, transfer work 6.2e9 -> 2.5e9 (edge scans
included). Counts identical on every finished query. M0/M6/M7 code paths unchanged. Not adopted: the paper is frozen on v25 (the
8 queries are reported as they are); v26 stays in the source and `scripts/final_run_v26.sh` for later.

## Finding 21: long chains leave far more headroom (2026-10-06, `chain25_dblp_main.csv`)

Workload: 300 paths of 8-10 vertices (`scripts/qgen.py --shape path --kmin 8 --kmax 10`, seed 11), v25 binary,
configuration of record, 4 shards on a loaded machine (noise far above the 1k runs; the operation counts are exact).
DBLP: the baseline times out on 104 of 300 (10 s); totals M0 1080 s, M6 1002 s, M7 27 s, M8 22 s (49x); M6 geo 1.27
on the 196 evaluated queries, M8 1.49 (every baseline timeout finishes). Operation counts over the 196 queries every
method finished: the transfers (1.1e6 entries, 16 ms) cut the scanned entries from 1.72e10 to 1.31e9 (92%, against
28% on the mixed 1k sample) and the join time from 40.5 s to 18.2 s; counting replaces 2.16e10 enumerated matches
by 1.37e9 counted entries (join 2.4 s). Longer chains compound the estimate errors of a host and multiply the
output, so both mechanisms gain more than on the mixed workload.

## Finding 22: the hosts' headroom is the output, and the counting join reaches it (2026-10-06)

Host core v4 (`rptg_count_decide` / `rptg_count`, DuckDB `CountShape`/`ReplaceCount`, PG `count_plan`). PG19,
DBLP-300 (`pg19_count_dblp300.csv`, PGNO/PGR, 3 reps, 10 s): geo 5.73 (transfers alone: 1.03), total 606 -> 87 s,
40/46 baseline timeouts finish, 0 count mismatches, < 0.8x 5.1% against a noise floor of 2.0%: 13 queries, all
below 20 ms (median baseline 1.9 ms, median loss 1.4 ms, max 17.5 ms). By baseline time: 0-20 ms geo 1.41 (10%
regress), 20-100 ms 6.08, 100-1000 ms 24.7, > 1 s 73.0. Three rules mattered: (1) decide before materializing
(the first variant, `_f8`, materialized every predicate set first and regressed 9.6%); (2) a floor on the counting
cost (2e6 entries), because the enumeration estimate E is two orders of magnitude low on hub neighbourhoods
(q2825: E 2e4, 3.5M matches, 350 ms host plan vs 3.5 ms counted; factor 1 without the floor, `_f1`: geo 1.56 only);
(3) in counting mode the transfer phase skips the tiny guard and treats transfers along the entering edge as
useful, because a push out of a 15-vertex predicate set shrinks the count arrays of an unconstrained neighbour
from n to a few entries (tiny-query count time 1.3 -> 0.1-0.8 ms).
DuckDB 1.3, DBLP-300 (`duckdb_count_dblp300.csv`, dk0/dkr): total 255 -> 14 s, 16/16 baseline timeouts finish,
geo 11.9 with the CLI timer's 1 ms floor (two 0 ms readings), 91.9% of the queries above 2x, < 0.8x 0.7% (2 queries,
13 and 16 ms lost) against a noise floor of 1.1%, 0 count mismatches. By baseline time: 0-20 ms geo 6.4, 20-100 ms
9.5, 100-1000 ms 22.5, > 1 s 196.

## Finding 23: five graphs, same picture (2026-10-07, v25, `final25_{youtube,orkut,pokec}1k_*`, `chain25_*`)

1,000 tree queries per graph (`qgen.py --n 1000 --seed 7`), main group M0,M6,M7,M8 and base group M0,M3,M4 in
separate process groups, 10 s timeout. Noise = share of queries whose baseline is < 0.9x between two repetitions.

| graph | noise | M3 < 0.9 | M4 < 0.9 | M6 < 0.9 | M6 geo | M8 geo | M0 total | M8 total | timeouts finished |
|---|---|---|---|---|---|---|---|---|---|
| YouTube (1.1M / 6.0M) | 4.7% | 80.5% | 88.4% | 2.2% | 1.14 | 1.62 | 1,667 s | 42 s | 147/147 |
| Orkut (3.1M / 234M) | 2.8% | 78.7% | 91.2% | 2.4% | 1.23 | 2.01 | 3,287 s | 886 s | 258/282 |
| Pokec (1.6M / 30.6M) | 3.0% | 77.1% | 87.7% | 2.0% | 1.21 | 1.92 | 1,799 s | 158 s | 139/139 |
| DBLP chains (k 8-10) | 13.3% | | | 8.7% | 1.27 | 1.49 | 1,080 s | 22 s | 104/104 |
| LJ chains (k 8-10) | 12.9% | | | 9.7% | 1.96 | 2.27 | 2,735 s | 1,043 s | 237/269 |

Counts identical to M0 for every method on every finished query. Scanned entries removed by M6's transfers: YouTube
75%, Orkut 77%, Pokec 78%, DBLP chains 92%, LJ chains 81% (31 queries all methods finished), against 28% (DBLP)
and 77% (LJ) on the mixed 1k samples; the transfer phase stays below 0.2% of M6's time everywhere (Orkut 4.4 s of
2,805 s). M8's regressions above the noise floor come from the ski rental: Orkut 46 regressions, 25 of them
switches to counting whose enumeration would have ended shortly after (median loss 3.9 ms, 7.7 s in total against
2,400 s saved), 21 enumerations (median loss 0.4 ms, i.e. noise). The v25 upfront path lost > 20% to M7 on 6 Orkut
queries (Finding 20; v26 fixes it, not adopted).

## Finding 24: the counting shortcut in Kùzu (2026-10-14, stage G, `kuzu_count_dblp300.csv`)

The same host core v4 path inside Kùzu 0.11.3 (`rptgTryCount`: a bare `count(*)` over a tree pattern, decided
from the zone-map estimates, adjacency index and predicate sets through a side connection, plan replaced by the
constant). DBLP-300, KNO/KR2/KRC interleaved, 3 reps, 10 s: geo 4.65 (transfers alone 2.04), total 268 -> 9 s
with failures at 10 s (87.7 -> 6.4 s on the 282 evaluated), 18/18 baseline failures finish (17 within 130 ms),
0 count mismatches, < 0.8x 3.5% against a noise floor of 7.1% (ten queries, nine below 35 ms, median loss 4.9 ms).
By baseline time: 0-20 ms geo 1.01 (10% regress), 20-100 ms 3.06, 100-1000 ms 9.94, > 1 s 48.5. Two things the
run taught: (1) the settings are per connection, so an interleaved runner must set `rptg_count` in every
configuration (a KRC configuration that inherited `rptg_count=false` from KR2 measured nothing); (2) the side
query must carry the exact literal: Kùzu prints doubles with six decimals, which changed 14 of 300 counts in a
first run, discarded. Kùzu's gain is smaller than PostgreSQL's (5.73) and DuckDB's (11.9) because its baseline is
the fastest on the sample (18 failures against 46 and 16); the headroom it reaches is the same, the output.

## Finding 25: RPT+ against RPT-G in DuckDB (2026-10-15, `duckdb300_rptplus.csv`)

Added after review. Six configurations on DuckDB 1.3.0 interleaved per query on DBLP-300 (official CLI; RPT+ fork
as-is and with filters dropped; our build off / RPT-G / RPT-G + counting), 1 warm-up + 3 reps, 8 threads, 10 s,
284 evaluated, 0 count mismatches. Each against its own binary's baseline (both builds are 6-10% slower than the
official one): RPT+ geo 1.03, 18.7% < 0.8x (noise 2.4%), by baseline time 0.85 / 1.13 / 1.36 / 1.14; RPT-G transfers
1.02, 2.8% < 0.8x (noise 2.8%), 1.01 / 1.02 / 1.04 / 1.03; RPT-G + counting 12.0, 0.4% < 0.8x, 16/16 timeouts, 99 -> 14 s.
Reading: RPT+'s Bloom filters inside the hash joins reach a third of the mid-sized queries' time, which RPT-G's
scan-level bitmaps under the plan-row budget do not claim in DuckDB (the budget admits 10 transfers in 300 queries);
the price is a fifth of the queries regressed, mostly below 20 ms. The headroom story of Finding 22 stands: the
output is where the time goes, and the counting join takes it.

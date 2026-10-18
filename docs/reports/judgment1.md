# Judgment 1 — does the regression problem exist on graphs?

Master plan, Part 12: implement M3 (Static-SemiMask) and M4 (Yannakakis-Bitmap), run Q-GEN 5,000,
look at the regression rate. If both are < 5%, the problem does not exist and the main line changes.

**Verdict: the problem exists, by a wide margin.** Static one-hop semi-masks regress 62% of the
queries on DBLP and 76% on LiveJournal; naive two-pass Yannakakis reduction regresses 80% / 88%.
RPT-G (M6, prototype v4) regresses 5.2% on DBLP and 14.1% on LiveJournal, in both cases at the
machine's noise floor (4.1% / 12.9%: the fraction of queries whose NoTransfer run is itself 10%
slower on its second repetition), with no regression below 0.5x on either graph.

## Setup

- Engine: standalone C++17 prototype (`prototype/`), single-threaded, CSR/CSC, dense bitmaps; all
  methods share the same join phase (left-deep connected DFS over CSR, bitmap probes) and the same
  host-like join order (smallest candidate set first, greedy by candidate size).
- Regression: per-query speedup over NoTransfer (M0) < 0.9, RPT+ convention. Baseline timeouts
  (10 s) excluded. 1 warm-up + 3 measured reps; from v3 on, reps are interleaved across methods.
- Workload: Q-GEN, 5,000 random tree patterns per graph (40% paths k=2..5, 30% stars k=3..5,
  30% random trees k=4..6), every vertex carries a predicate with p=0.5 (at least one), predicate
  selectivity log-uniform in [1e-5, 1] on a uniform property (70%), top-s hubs by degree (15%),
  ground-truth community label (15%). Homomorphism semantics, result = match count; counts are
  cross-checked across all methods and against DuckDB.
- Graphs: com-DBLP (317K / 2.1M, undirected), soc-LiveJournal1 (4.85M / 69M, directed).
- Machine: 40 cores, 93 GB, shared with other users' jobs; noise floor (M0 vs its own second rep
  below 0.9x): 4.1% on DBLP.

## Results — DBLP (v4 engine, mean of 3 interleaved reps, 4,914 queries)

| method | regr < 0.9 | < 0.5 | < 0.1 | geomean | P5 | P50 | P95 | max |
|---|---|---|---|---|---|---|---|---|
| M3 Static-SemiMask | 62.3% | 16.6% | 0.0% | 0.72 | 0.34 | 0.82 | 1.02 | 75 |
| M4 Yannakakis-Bitmap | 80.4% | 51.3% | 11.9% | 0.36 | 0.07 | 0.48 | 0.98 | 1040 |
| M6 RPT-G (v4) | **5.2%** | 0.2% | 0.0% | 0.99 | 0.90 | 0.98 | 1.10 | 1159 |

Total time over the workload: M0 724 s, M3 729 s, M4 814 s, M6 702 s; M6's transfer phase costs
0.76 s in total. Regressions of M6 by cause: 69 transfer-caused (1.4%), 115 join-time drift with
identical work (noise), rest mixed.

Percentile curve (RPT+ Figure 10 analog): `results/dblp_qgen_v4.png`.

Breakdown of M3 / M4 regression rate by minimum predicate selectivity: 60% / 74% even for the
most selective bucket (< 1e-4) and 65–68% / 89–91% for non-selective predicates. Shape and k
barely matter. The problem is not "non-selective predicates" only: on graphs the transfer cost is
governed by degree sums of the source set, which stays large whenever a predicate-less variable
or a hub-heavy set is the source.

## Results — LiveJournal (v3 engine, mean of 3 interleaved reps, 3,897 queries; 1,103 baseline timeouts excluded)

| method | regr < 0.9 | < 0.5 | < 0.1 | geomean | P5 | P50 | P95 | max |
|---|---|---|---|---|---|---|---|---|
| M3 Static-SemiMask | 76.8% | 28.5% | 0.3% | 0.63 | 0.22 | 0.74 | 1.06 | 10.7 |
| M4 Yannakakis-Bitmap | 87.8% | 60.4% | 18.2% | 0.30 | 0.05 | 0.36 | 0.98 | 9.0 |
| M6 RPT-G (v3, no budget) | 16.6% | 0.0% | 0.0% | 1.00 | 0.81 | 0.98 | 1.24 | 13.9 |

Noise floor on LJ is 10.2% (heavier queries drift more between reps). M6 v3 regressions: 288
transfer-caused (7.4%), 177 join-time drift. Total time: M0 1,819 s, M3 2,096 s, M4 3,143 s,
M6 1,727 s (transfer phase 18 s). 22% of the workload times out at 10 s under M0 (hub-driven
paths/stars); M6 finishes 13 of those within the limit, M3 11, M4 loses 12 more.
### LiveJournal, v4 engine (mean of 3 interleaved reps, 3,860 queries; 1,140 baseline timeouts excluded)

| method | regr < 0.9 | < 0.5 | < 0.1 | geomean | P5 | P50 | P95 | max |
|---|---|---|---|---|---|---|---|---|
| M3 Static-SemiMask | 75.6% | 27.8% | 0.2% | 0.63 | 0.22 | 0.74 | 1.08 | 10.3 |
| M4 Yannakakis-Bitmap | 87.7% | 60.3% | 18.2% | 0.30 | 0.05 | 0.36 | 1.01 | 7.6 |
| M6 RPT-G (v4) | **14.1%** (7.0% with min-of-reps) | 0.0% | 0.0% | 1.01 | 0.81 | 0.99 | 1.33 | 11.3 |

Noise floor 12.9%. M6 regressions by cause: 94 transfer-caused (2.4%), 306 join-time drift with
identical work. Totals: M0 1,905 s, M3 2,237 s, M4 3,430 s, M6 1,823 s (transfer phase 10.3 s).
Timeouts: M0 1,140; M6 turns 29 of them into successes (M3 22, M4 18) and adds 5 new ones.
Percentile curve: `results/lj_qgen_v4.png`.

## Why M3 and M4 regress (mechanisms, each with evidence)

1. Naive Yannakakis pushes from predicate-less variables: a transfer from a full candidate set
   costs the whole edge table (2M–69M adjacency entries) and prunes nothing (M4, every query with a
   predicate-less variable; e.g. DBLP test q5, join 27 ms, M4 transfer 45 ms).
2. Static semi-masks from non-selective predicates: pushing a 30% predicate set costs 30% of the
   edge table for a few percent of pruning (M3, DBLP test q8: +23 ms on a 28 ms query).
3. Transfer cost is not hidden by scans in a CSR-driven engine: even a "successful" transfer that
   removes 70% of B_y is wasted when the join touches a small part of B_y (LJ q2567, 47 ms transfer,
   join unchanged). This is the graph-specific point; see `docs/insights.md`.

## What RPT-G does about it (prototype v4)

- Source-skip (Lemma P5), density skip, exact push/pull costs from degree accumulators, random
  pilot with abort (Algorithm 2').
- Join-side probe elimination and plan-time usefulness pruning of transfers (new, exact given the
  host join order).
- Transfer budget: exact cost <= beta * estimated benefit, benefit from a closed-form survival
  estimate on the degree accumulators along the host join order, with the same-edge round-trip
  correction (new).

## Threats to validity

- Prototype join phase is lean (no host overhead); regressions here are the strictest measure.
  Against a DuckDB host, the same M6 v1 regressed 5.4% with a 4.4x geomean speedup (reference only).
- Single-threaded; multi-threaded and on-disk protocols (plan §8.10) not yet run.
- Timing drift on a shared machine (up to 1.6x on 5 s queries between reps); interleaving and the
  reported noise floor bound it.

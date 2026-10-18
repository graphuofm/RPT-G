# Judgment 2 — does "why graphs are different" hold?

Master plan, Part 12: run M2 (RPT+ as-is) and the ablation M6-acc. If RPT+ as-is regresses < 5%
on graph pattern queries AND M6-acc is indistinguishable from M6, the differentiation is weak and
the main line moves to theory (P2/P3) + cyclic patterns.

**Verdict: the differentiation holds, on condition (a); condition (b) fails and changes the story.**

## (a) RPT+ as-is on graph pattern queries — regresses 55%

- Setup: the same Q-GEN 5,000 DBLP workload as SQL self-joins over `E(src,dst)` and `V(id,pu,pd,label)`
  in DuckDB. M1 = vanilla DuckDB v1.3.0 CLI, M2 = the RPT+ fork (embryo-labs, on v1.3.0), both
  8 threads, 1 warm-up + 3 measured reps in one CLI process per query, 10 s timeout, ms timer
  resolution. Result counts agree on all 5,000 queries.
- 4,767 queries evaluated (233 M1 timeouts excluded; M2 turns 7 into successes and adds 11).

| | regr < 0.9 | < 0.5 | geomean | P5 | P50 | P95 | max |
|---|---|---|---|---|---|---|---|
| RPT+ over DuckDB 1.3.0, all | **55.0%** | 8.7% | 0.91 | 0.43 | 0.87 | 2.21 | 54 |
| M1 >= 20 ms (n=2,733) | 43.5% | | 1.04 | 0.48 | | | |
| M1 >= 100 ms (n=945) | 39.9% | | 1.15 | 0.55 | | | |
| M1 >= 1 s (n=376) | 43.9% | | 1.09 | 0.56 | | | |

Noise floor (M1 vs its own second rep below 0.9): 9.6%. Whole workload: M1 1,450 s, M2 1,519 s.
By minimum predicate selectivity: 50–54% regressions for selective predicates (< 1e-2), 69–70%
for non-selective ones; by pattern size: 66% at k=2 down to 48–54% at k>=5.
Percentile curve: `results/dblp_rptplus_vs_duckdb.png`.

Compare RPT+'s own numbers on relational workloads: 2.1% regressions on SQLStorm. On graph
pattern queries the same code regresses more than half of the queries. RPT-G's in-engine
counterpart (prototype v4) regresses at the noise floor (5.2% DBLP, 14.1% LJ, floors 4.1% / 12.9%).

Case study (q4955, path 3-0-1-2 with one 1.8% predicate on the end vertex; M1 134 ms, M2 424 ms
in the run, 164 ms vs 219 ms in an isolated EXPLAIN ANALYZE): the result has 27.1M rows and the
final hash join costs 0.7–0.8 s of CPU in both engines. RPT+ adds three CREATE_BF sinks (two on
2.1M-row copies of `E`, one on the 5.8K-row filtered `V`) and four USE_BF probes; the filters do
shrink the `E` scans (2.1M -> 568K rows) but the output-dominated join cannot shrink, so the
filters are pure overhead. The prototype's M6 skips every transfer of this query as useless
(zero transfer work): its usefulness/budget logic sees that the reduced bitmaps would never be
probed through another edge. RPT+'s ATP has no such notion — every `E` copy is a "bridge table"
and gets a filter. Every pattern edge being a copy of one large table is what makes graph
self-join chains a worst case for filter-per-table designs.

## (b) Exact accumulators vs sampled estimates — no measurable difference

- M6-acc replaces the exact degree sums by a sequential 1,000-member sample (RPT+-style streaming
  estimate) everywhere they are used (push/pull cost, budget/benefit estimate).
- DBLP 5,000: regressions 4.6% (sampled) vs 5.2% (exact), geomean 0.983 vs 0.989, op mix identical.
- LJ 1k subsample, paired per query (n=764): geomean ratio 1.000, regressions 11.0% vs 12.8%
  with a 12–16% noise floor.
- Conclusion: plan §3.2 ("estimates become exact") is not a differentiator; decisions have wide
  margins and the sample is good enough even with hubs. Keep it as an implementation detail (one
  in-order pass, no sampling code) and drop it from the contributions.

## What carries the differentiation instead (each with evidence in `docs/insights.md`)

1. Σdeg cost model with direction (push vs pull) — M4 vs M6 op mix; push/pull choice appears in
   ~20% of executed transfers.
2. Transfer cost is not hidden by scans in an index-driven join — the budget rule alone moves the
   327 hardest DBLP queries from 83% to 17% regressions and cuts the LJ transfer-caused
   regressions to 2.4%.
3. Plan-time usefulness pruning given the host join order — 64–73% of all candidate transfers are
   provably useless and skipped at zero cost.
4. Degree skew (hubs) — LJ timeouts (22% of Q-GEN under NoTransfer) and the pull-side abort.
5. Bitmaps instead of Bloom filters — exact, AND/popcount, random access (enables random-order pilots).

## Consequences for the plan

- Contributions (§1): replace "(2) exact-cost direction decision" by "(2) exact-cost, budgeted
  transfer decisions given the host join order: usefulness pruning, push/pull, budget with a
  closed-form benefit estimate, in-place abort".
- §3.2 shrinks to a paragraph inside §3.1; the microbenchmark M6-acc becomes a one-line ablation.
- §8.3 gains a bar: "RPT+ as-is" on graph queries (55% regressions) next to M3/M4/M6.

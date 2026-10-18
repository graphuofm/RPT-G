# Paper-relevant findings from the prototype (running log)

Each entry: observation -> evidence -> what it means for the paper.

## 2026-09-17

### Judgment 1 (does the regression problem exist on graphs?) — YES
- Q-GEN 5,000, regression = speedup < 0.9 vs NoTransfer (M0) with the same join order, v1 engine.
  DBLP: M3 (static semi-mask) 56%, M4 (naive Yannakakis-bitmap) 76%.
  LiveJournal: M3 72%, M4 85%. Restricted to queries with M0 >= 100 ms: still 71% / 83%.
- Noise floor (M0 vs itself across reps): ~5% below 0.9. So these rates are real.
- Far above the 5% bar in the master plan (Part 12). Proceed with the main line.

### Join-phase probe elimination (Lemma P5 on the join side)
- Naively probing every reduced bitmap during the CSR join made M6's join 10x slower than M0 on
  queries with large outputs: a probe of B_y while extending x->y is redundant whenever B_y's only
  information came through that same edge (u in N(B_x) holds by construction).
- Tracking `reduced_via` per bitmap removes it. Applies to all methods equally.

### Plan-time usefulness pruning of transfers
- Given the host's join order, a transfer x->y is useful iff its information is consumed: the join
  probes B_y entering through another edge (or y is the start variable), or a later effective
  transfer uses y as source. Effectiveness = plan-time simulation of the source-skip rule.
- Backward pushes into predicate-less leaves and all transfers in single-predicate queries are
  useless and are now skipped at zero cost. This subsumes RPT+'s "forward pass only from tables
  with predicates + bridges" heuristic and is exact rather than heuristic.

### Degree accumulators are not free
- "Accumulate while setting bits" costs one random access into the offset array per set bit
  (~30 ns/edge on a loaded machine) and dominated M6 overhead on small queries.
- Fix: recompute by one in-order pass over the new bitmap with compact degree arrays (monotone
  access, prefetch-friendly). Still exact. The paper should say "one extra sequential pass", not "zero".

### Transfer cost is not hidden by scans in graph engines  (candidate 5th point for Section 3)
- In DuckDB, the transfer phase piggybacks on table scans that happen anyway, so an O(N) filter
  build is nearly free relative to the join. In a CSR-driven engine the join is index-nested-loop:
  cost ~ intermediate results, which can be orders of magnitude smaller than |V| or |E|.
- Evidence (LJ q2567, v2 engine): PUSH 4->3 reduced B_3 from 4.8M to 1.48M (lambda 0.3, so RPT+'s
  rule builds it) at 47 ms; the join touched only a tiny part of B_3 and saved nothing
  (104 ms -> 107 ms). Net regression 1.38x from a "successful" transfer.
- Consequence: the benefit side of the decision must consider how much of B_y the join will actually
  probe (bounded by the degree sum of the entering variable's candidate set), not just lambda.
  Open design question — decide after the v2 full runs.

### gamma
- gamma = 100K (RPT+) never triggers on graph-sized candidate sets (|B_y| often < 100K) and a pilot
  of 10K vertices costs more than many whole queries. Random word-order sampling is unbiased, so
  2K is statistically sufficient; sweep it in the sensitivity section.

### Timeouts on LiveJournal
- 22% of Q-GEN queries exceed 10 s under NoTransfer (hubs of degree 22,889 in paths/stars).
  These are excluded per the RPT+ protocol; report them separately (they are where reduction can
  turn a timeout into a success — the "improvement tail").

### Cross-engine reference (not a paper number)
- DBLP Q-GEN, DuckDB 1.5.5 (8 threads, SQL self-joins) as baseline: single-threaded prototype
  M6 v1 is 4.4x faster (geomean) and regresses on 5.4% of queries; M4 1.8x / 25%; M3 3.4x / 12%.
- Shows the host's fixed per-query floor (~10 ms) hides most transfer overhead; the in-engine
  M0-relative numbers are the honest measure of transfer cost and are what the paper should use
  for the "eliminates regressions" claim (RPT+ compares against the same engine without RPT).

### Measurement protocol (lesson from the v2 runs)
- On a shared, loaded machine, running all reps of M0 and then all reps of M6 puts the two methods
  in different load windows: 78 "regressions" of M6 on DBLP queries >= 100 ms had zero transfer
  work and identical join work — pure timing drift (up to 1.6x on a 5 s query).
- Protocol from v3 on: rep-major interleaving (rep i runs every method back to back), 1 warm-up +
  3 measured reps, report geomean of per-rep speedups or min/median of reps; keep the noise floor
  (M0 vs itself) in the paper's Setup. This mirrors RPT+'s "geometric mean of five speedups, each
  relative to the corresponding baseline run".

### Transfer budget with accumulator-based benefit estimate (v4)
- Problem: Algorithm 2' admits a transfer whenever lambda looks good, but on CSR joins the join
  may touch only a tiny part of B_y; a 70% reduction can be worth nothing (see above).
- Rule: execute x->y only if exact cost (min(push, pull)) <= beta * estimated benefit.
  benefit = (1 - surv) * cap[y];  surv(x->y) = 1 - (1 - |B_x|/n)^{avgdeg(B_y toward x)};
  cap[y] = estimated join work from the level entering y onward, from the host join order with
  matches[y] = matches[x] * avgdeg(B_x toward y) * |B_y|/n (independence; exact aggregates from
  the degree accumulators, no sampling). Chain-consumed transfers inherit the benefit of the
  downstream op they feed. Estimated sizes propagate along the sequence.
- Round-trip correction: information does not compound over the same edge (B_x ∩ N(B_y) carries
  nothing new back to y beyond B_x itself), so the survival of y->x undoes the earlier x->y factor.
  Without it a hub-set round trip (DBLP q2861) is wrongly valued at ~50% pruning; measured 3%.
- Effect on the 327 transfer-caused DBLP regressions (min of 2 reps): 82.9% -> 30.3% regressed
  with the cap-only budget, -> 16.5% with survival + round-trip correction + count-only last level
  (geomean 0.815 -> 0.951, min 0.66). On 117 improved queries (speedup > 1.2 under v3): geomean
  1.64 (v3) -> 1.53 (cap-only) -> 1.65 (final v4), regressions 0.9%: no benefit given up.
  beta is a knob for the sensitivity section.
- Gives up the full-reduction guarantee exactly like RPT+'s selectivity abort does; state it.

### Ablation M6-acc on DBLP: no measurable difference
- Replacing the exact degree accumulators by a sequential 1,000-sample estimate (RPT+-style
  streaming estimate) changes nothing on DBLP: regressions 4.6% vs 5.2%, geomean 0.983 vs 0.989,
  op mix identical (64% SKIP-useless, 12% PUSH-A, 9% SKIP-budget, 8% PULL-B ...).
- Reason: DBLP's degree distribution is mild (max 686, mean 13) so a sample estimates degree sums
  well, and most decisions have wide margins. The exactness argument (plan §3.2) must be made on
  heavy-tailed graphs (LJ max degree 22,889; Orkut) — run the ablation there. If it still shows no
  difference, drop "exact estimates" as a headline claim and keep it as an implementation detail.

### beta sensitivity (DBLP 1k subsample, M0+M6, mean of 3 interleaved reps)
| beta | 0 (off) | 0.25 | 0.5 | 1 | 2 | 4 |
|---|---|---|---|---|---|---|
| regr < 0.9 | 8.8% | 1.4% | 2.0% | 2.8% | 8.8% | 6.9% |
| geomean | 0.988 | 1.009 | 1.003 | 0.997 | 1.004 | 0.999 |
| noise floor of that run | 1.9% | 1.8% | 2.5% | 3.5% | 6.7% | 5.2% |
- Any beta in [0.25, 1] puts M6 at the noise floor on DBLP; the budget matters (off = 8.8%).
- DBLP has few large improvements, so the cost of a small beta on the benefit side must be judged
  on LJ (pending sweep). Default stays beta = 1 until then.

### Ablation M6-acc on LiveJournal: still no difference  (Judgment 2, condition b)
- LJ 1k subsample, paired per query (n=764): geomean ratio exact/sampled = 1.000; exact better
  (>5%) on 28.9%, sampled better on 28.1%; regressions 12.8% vs 11.0% with a 12–16% noise floor.
  Op mix identical (65% SKIP-useless, 11–13% SKIP-budget, 7–8% PULL-B, 6% PUSH-A).
- Conclusion: exact accumulators are not a differentiator in practice; decisions have wide margins
  and a 1,000-sample estimate is good enough even with hubs. Plan §3.2 ("estimates become exact")
  drops from headline to implementation detail (still nice: one sequential pass, no sampling code).
- The differentiation must rest on: Σdeg cost model with direction (push vs pull), transfer cost
  not hidden by scans (budget + benefit model), plan-time usefulness pruning, degree skew, bitmaps.
  Condition (a) of Judgment 2 — RPT+ as-is regression rate on graphs — pending (M1/M2 DBLP runs).

### Judgment 1 final numbers (v4 engine, interleaved reps)
- DBLP: M3 62.3%, M4 80.4%, M6 5.2% (noise floor 4.1%); LJ: M3 75.6%, M4 87.7%, M6 14.1% (noise
  floor 12.9%; 7.0% with min-of-reps). No M6 regression below 0.5x on either graph.
- Transfer-caused M6 regressions: 1.4% (DBLP), 2.4% (LJ) — the honest "cost of RPT-G" number.
- Improvement side is thin on Q-GEN as generated: geomean 0.99 / 1.01. Q-GEN draws predicates
  uniformly, so most queries are already cheap under a good order; the improvement tail (up to
  1000x, 29 timeouts turned into successes on LJ) exists but is rare. The plan's Q-HUB / Q-CORR /
  random-join-order experiments (8.4) are where RPT-G's upside must be shown.

### Judgment 2 (2026-09-18): RPT+ as-is regresses 55% of graph pattern queries in DuckDB
- DBLP Q-GEN as SQL self-joins, RPT+ fork vs vanilla v1.3.0, 8 threads: 55.0% regressions
  (8.7% below 0.5x), geomean 0.91, noise floor 9.6%; 39.9% even for queries >= 100 ms. Counts agree.
- Combined with the M6-acc null result: the differentiation rests on the cost model / budget /
  usefulness pruning / skew / bitmaps, not on exactness. Report in docs/reports/judgment2.md.

### beta sensitivity on LJ 1k (M0+M6, mean of 3 interleaved reps; each beta is a separate run)
| beta | 0 (off) | 0.25 | 0.5 | 1 | 2 | 4 |
|---|---|---|---|---|---|---|
| regr < 0.9 | 17.2% | 5.2% | 2.6% | 12.8% | 6.5% | 6.2% |
| noise floor of that run | 14.1% | 6.2% | 4.8% | 16.4% | 4.6% | 2.2% |
| geomean (all / M0 >= 100 ms) | 0.993 / 1.043 | 1.012 / 1.048 | 1.014 / 1.054 | 1.004 / 1.044 | 1.001 / 1.052 | 0.997 / 1.054 |
| P95 | 1.26 | 1.15 | 1.16 | 1.27 | 1.13 | 1.07 |
- Regression rates track the noise floor of each run; the budget never hurts the improvement side
  (geomean on >= 100 ms queries is flat at ~1.05 for every beta). Combined with DBLP (0.25: 1.4%,
  0.5: 2.0%, 1: 2.8%), beta = 0.5 is the recommended default for the host integration; the v4
  headline numbers above were produced with beta = 1.

### Join-order robustness (plan 8.4) — first attempt was confounded by output size
- 100 DBLP queries x 50 random connected left-deep orders, M0 vs M6: robustness factor
  (max/min over orders) geomean 58 (M0) vs 40 (M6); per-pair M6 is 1.4x faster than M0 and worst-
  order total drops 587 s -> 520 s, but "any order is near-optimal" does not hold.
- Diagnosis: 99.9% of the bad-order time is the join phase with fully reduced bitmaps; the
  queries have huge outputs (10^8–10^9 matches). Under a good order the last level enters a
  predicate-less variable and the engine counts matches in O(1) per prefix; under a bad order the
  same output is enumerated explicitly. The factor measures the count shortcut, not join order.
  A real engine must produce every output tuple in either order.
- Fix: restrict the robustness workload to queries with output <= 10^6 (RPT's benchmarks also have
  modest outputs) and add M4 as the "full reduction, no budget" reference. Re-running.
- Remaining real (non-artifact) cost: a prefix ending at a hub scans the hub's whole adjacency to
  find its few surviving neighbours — O(sum deg) not O(OUT). The plan's BitmapEdgeScan
  (materialized filtered adjacency for reduced sources) is the fix if the re-run still shows it.

### Join-order robustness, output-bounded (DBLP, 100 queries with output <= 1e7, 50 random orders)
| | robustness factor geomean / median / P90 | queries with factor <= 2 | worst-order sum | median-order sum | best-order sum |
|---|---|---|---|---|---|
| M0 NoTransfer | 25.3 / 11.2 / 889 | 4 | 139.9 s | 37.2 s | 1.6 s |
| M4 Yannakakis-Bitmap | 3.27 / 1.70 / 40.5 | 59 | 26.9 s | 9.7 s | 2.4 s |
| M6 RPT-G v4 | 5.05 / 2.18 / 120 | 46 | 26.1 s | 9.0 s | 1.6 s |
- Per (query, order): M6 is 2.22x faster than M0 (2.3% regressions, 36% of pairs > 2x);
  M4 1.36x (40% regressions). M0 times out on 90 pairs, M4/M6 on none.
- M4 is more robust than M6 because M6's usefulness/budget skips give up reduction under bad
  orders; M6 wins on average because it never pays for useless transfers. RPT reports factors
  <= 2.8; we are not there yet: both M4 and M6 still have factors of 300–900 on some queries,
  which points at the join phase (see next entry).

### gamma / tau_sel sensitivity (LJ 1k, M0+M6, mean of 3 interleaved reps)
| setting | default (2000 / 0.35) | gamma 500 | gamma 10000 | tau_sel 0.2 | tau_sel 0.5 |
|---|---|---|---|---|---|
| regr < 0.9 | 12.8% | 1.8% | 3.3% | 3.4% | 3.7% |
| noise floor of run | 16.4% | 0.5% | 1.8% | 1.3% | 3.2% |
| geomean (all / >= 100 ms) | 1.004 / 1.044 | 1.006 / 1.048 | 1.008 / 1.054 | 1.004 / 1.052 | 1.006 / 1.055 |
- Insensitive: pilots and aborts are < 1% of executed operations once usefulness pruning and the
  budget are in place; regression rates simply track the noise of each run. One line + one figure
  in the sensitivity section, no more.

### BitmapEdgeScan makes the join phase output-sensitive (v5)
- After reduction the CSR join still scans a prefix's whole adjacency to find its few surviving
  neighbours: DBLP q3034 under a bad order did 441M scans for 5.2M results even with fully reduced
  bitmaps (M4). q1465: 665M scans for 7.4M results.
- v5 materializes, per join step whose target needs a probe, the filtered adjacency of the source
  candidate set (only neighbours in B_y), indexed by bitmap rank — the plan's BitmapEdgeScan. Cost
  = one adjacency pass over B_x (a push). Built only when the estimated number of prefixes that will
  visit x is >= scan_beta * |B_x| (each source vertex visited at least once on average), so the
  downside is bounded by one push per step. The join then walks surviving edges only.
- Prefix estimate bug found on the way: the number of visits of variable x at a step is the running
  number of partial matches along the left-deep order, not the candidate count of x (stars and
  forks). Fixed in both the budget estimate and the edge-scan criterion.
- Effect (50 random orders, no count shortcut): q3034 M6 max 1657 -> 114 ms (M0 6336 ms);
  q1465 M6 max 2678 -> 182 ms (M0 9818 ms). M6 and M4 now have identical worst-order join work;
  M6's max/min factor is larger only because its best case is 3x faster (no useless transfers).
- Report both the RPT-style factor (max/min) and the worst-order absolute time; the factor
  penalizes methods with a cheap best case.
- Also: the O(1) count at a probe-free last level (an artifact of counting instead of producing
  tuples) is disabled for join-order experiments (`--no-count-shortcut`), otherwise a good order
  gets the output for free and factors are meaningless.

### Join-order robustness, v5 (DBLP, 100 output-bounded queries x 50 random orders, no count shortcut)
| | factor geomean / median / P90 | queries <= 2 / <= 3 | worst-order sum | median-order sum | best-order sum |
|---|---|---|---|---|---|
| M0 NoTransfer | 20.3 / 10.9 / 612 | 8 / 16 | 159.3 s | 42.7 s | 2.1 s |
| M4 Yannakakis-Bitmap (+edge scan) | 3.01 / 2.24 / 16.5 | 45 / 64 | 24.0 s | 6.6 s | 2.9 s |
| M6 RPT-G v5 | 3.69 / 2.93 / 20.2 | 44 / 51 | 17.8 s | 4.9 s | 1.7 s |
- Per pair: M6 2.41x faster than M0 (7.1% regressions), M4 1.55x (38%). M0 times out on 103 pairs.
- geomean(M6 worst order / M0 best order) = 3.66 (M4 5.32). RPT reports factors <= 2.8 on JOB.
- Remaining outliers (q106: 9.7 ms best, 3.5 s worst, same for M4) are in the join phase; diagnosing.

### Edge-scan criterion needs semi-join-aware survival estimates (v5b)
- After reduction, candidate sets are correlated by construction: if x already carries y's
  information (sources(y) ⊆ sources(x)), every x-vertex has >= 1 surviving neighbour in B_y; if y
  carries x's, B_y ⊆ N(B_x) so its density among x's neighbours is |B_y| / min(n, D[x->y]), not
  |B_y| / n. The independence estimate was 13x too low per level on DBLP q106 and compounded, so
  edge scans were not built and the join scanned 850M entries for 9.2M results.
- With both rules the four worst robustness outliers drop to 47–225 ms worst order
  (M0: 1.8–6.8 s); per-level accounting (LEVELS(...) in ops) shows join work ~ prefixes at every
  level, i.e. the join is output-sensitive under any order.
- Paper: the transfer plan's provenance (sources) is not only for skipping transfers; it also
  gives the join-phase cardinality estimates that plain independence gets badly wrong.

### DBLP Q-GEN with BitmapEdgeScan (v5, beta = 1, mean of 3 interleaved reps, 4,905 queries)
| method | regr < 0.9 | < 0.5 | geomean | P5 | P95 | total time |
|---|---|---|---|---|---|---|
| M3 | 57.3% | 11.7% | 0.76 | 0.39 | 1.03 | 763 s |
| M4 (+edge scan) | 76.7% | 48.8% | 0.42 | 0.10 | 1.00 | 823 s |
| M6 v5 | **3.3%** | 0.1% | 1.01 | 0.92 | 1.11 | 696 s (M0: 760 s) |
- Noise floor 6.5%. Edge scans were built in 40% of the M6 runs and cost nothing measurable: the
  criterion (visits >= |B_x|) bounds the build by one adjacency pass the join would pay anyway.
- Under the host's default order the workload is 8% faster with M6; the real payoff is under
  bad orders (robustness section).

### Join-order robustness, final (v5b; DBLP, 100 output-bounded queries x 50 random orders, no count shortcut)
| | factor geomean / median / P90 / max | queries <= 2 / <= 3 | worst-order sum | median-order sum | best-order sum |
|---|---|---|---|---|---|
| M0 NoTransfer | 17.9 / 8.1 / 433 / 2112 | 7 / 21 | 147.0 s | 40.1 s | 2.1 s |
| M4 Yannakakis-Bitmap (+edge scan) | 1.75 / 1.32 / 4.3 / 15.5 | 73 / 83 | 4.8 s | 2.7 s | 1.9 s |
| M6 RPT-G v5b | 2.51 / 1.53 / 12.7 / 34.8 | 57 / 65 | 5.5 s | 2.4 s | 1.0 s |
- Per pair: M6 2.95x faster than M0 (5.3% regressions, 45% of pairs > 2x, 19% > 10x); M4 2.08x (35%).
- geomean(M6 worst order / M0 best order) = 2.26 (M4 2.71): under a random order RPT-G is within
  2.3x of the host's best order on average — the RPT claim (<= 2.8x) holds on graphs.
- M6's worst-order geomean 21.7 ms vs M0 172 ms. Remaining outliers (q4069: M6 784 ms, M4 100 ms)
  are budget/abort decisions that gave up reduction — the price of never paying for useless
  transfers; M4 is the guarantee-first reference. Figure: results/dblp_robustness.png.

### Final Q-GEN numbers with the full engine (edge scan on, beta = 1, mean of 3 interleaved reps)
| graph | engine | M3 regr | M4 regr | M6 regr (< 0.5) | M6 geomean | noise floor | total M0 / M4 / M6 |
|---|---|---|---|---|---|---|---|
| DBLP | v5b | 56.9% | 75.3% | 5.6% (0.7%) | 1.018 | 6.6% | 759 / 746 / 687 s |
| LiveJournal | v5 | 68.8% | 85.7% | 6.2% (0.0%) | 1.029 | 5.9% | 1,933 / 3,198 / 1,731 s |

### Join-order robustness on LiveJournal (v5b, 100 output-bounded queries x 50 random orders)
| | factor geomean / median / P90 / max | worst-order sum | median-order sum | best-order sum | timeouts |
|---|---|---|---|---|---|
| M0 | 22.4 / 21.1 / 138 / 527 | 337.6 s | 134.5 s | 8.5 s | 515 of 5,000 pairs |
| M4 | 2.22 / 2.30 / 3.1 / 4 | 46.6 s | 27.2 s | 21.0 s | 0 |
| M6 | 3.60 / 2.95 / 9.1 / 49 | 32.4 s | 12.4 s | 7.1 s | 0 |
- Per pair M6 is 3.23x faster than M0 (9.2% regressions, 22% of pairs > 10x); M4 1.51x (36%).
- geomean(M6 worst order / M0 best order) = 3.41. M4 has the tighter factor because its best case
  is 3x slower (21.0 s vs 7.1 s best-order sum); M6 wins every absolute column.

### Host estimates vs run-time exact sizes (Kùzu, 2026-09-21) — §3.2 comes back in a different form
- Kùzu 0.11.3 estimates every range predicate at a constant 10% selectivity: `pu < 0.001` (true 302
  rows) and `pu < 0.3` (true 95,031 rows) both get cardinality 31,708 of 317,080. Its static
  semi-mask rule ("the side has a filter") cannot do better with such estimates, and neither could a
  plan-time budget.
- In the prototype the M6-acc ablation showed no difference because a 1,000-member sample is already
  accurate. The meaningful contrast in a real host is not "exact vs sampled" but "host optimizer
  estimate vs what is known exactly at run time once the previous transfer finished": candidate-set
  sizes are mask cardinalities (free on a Roaring bitmap). That is the claim to make and to ablate
  (budget fed with Kùzu's estimates vs with run-time mask cardinalities).
- Kùzu's per-rep timing noise at 8 threads is ±10% for a quarter of the queries (median CV 9%); use
  median of 5 reps and report regressions at 0.8x / 0.5x next to the same-threshold noise floor
  (9.8% / 0.0% in the K0 attempt). Kùzu 0.11.3 also crashes after a buffer-pool-full exception;
  `run_kuzu.py` now supervises and restarts workers.
- K0 attempt 2 (3,191 queries, 3 procs x 8 threads): Kùzu semi-mask on vs off: < 0.8x 16.5% (noise
  9.8%), < 0.5x 4.8% (noise 0.0%), improved > 1.25x 20.7% (noise 9.2%), geomean 1.08; by minimum
  selectivity: < 1e-4 geomean 1.25 (42% improved), 1e-3..1e-1 geomean 0.87–0.94 (31–37% below 0.9);
  total time 757 s off vs 836 s on; queries >= 1 s: geomean 0.92, 15.6% below 0.5x.

### Degree sums matter in the host after all (Kùzu, 2026-09-21)
- With exact candidate-set sizes and an accurate plan-time pre-screen in place, the remaining RPT-G
  regressions in Kùzu all involve degree-correlated predicates: cost and survival computed from
  |B_x| and the table-average degree are off by 20–30x when B_x is a set of hubs. The right quantities
  are sum deg(B_x) (cost) and sum deg(B_x)/|E| (probability that a random neighbour lies in B_x).
- The prototype's M6-acc ablation missed this because its survival formula also used |B_x|/n; only
  the cost side used the accumulators there. Revisit the prototype's survival with D[x]/m and re-run
  the ablation on Q-GEN's `pd` (hub) predicates — that is where exact degree sums should separate
  from size-based estimates.

### Host masks may not be exact (Kùzu, 2026-09-21)
- In Kùzu 0.11.3 a semi mask on a node scan only skips whole 2,048-row vectors: the chunk scan resets
  the selection vector that the mask pass prepared. Any reduction below vector granularity is lost
  until a later join filters it. For SIP inside a hash join this is a mere inefficiency; for
  Yannakakis-style reduction it removes most of the benefit (the reduced candidate set never reaches
  the driving scan) while the transfer cost is paid in full.
- General lesson for the paper (§7, integration): predicate transfer needs the host's scan to honour
  the filter at tuple level (RPT+'s cascade has the BF for that; a bitmap host must apply the bitmap
  per row). Worth one paragraph and the before/after numbers.

### LadybugDB fixed the mask granularity independently (2026-09-22)
- LadybugDB (the maintained Kùzu fork, v0.20.4) re-applies the semi mask after the chunk scan with the
  comment "The chunk scan above resets the selection ... discarding the pre-check's subset. Intersect
  the mask with the surviving rows so only masked rows are materialized instead of the whole chunk" —
  the same fix as ours in Kùzu 0.11.3 (`applySemiMaskRowFilter`).
- Consequence for the evaluation: the stage-E comparison gives RPT-G exact masks while Kùzu's own
  semi-mask keeps vector granularity. Fair baseline = host semi-mask with exact masks too. Added a
  process-wide `CALL exact_semi_mask=true` switch (kuzu_dev tree) and will re-run the KSM baseline
  with it; report both "stock 0.11.3" and "exact" host baselines.
- Port target: LadybugDB. The hook points of the patch (`acc_hash_join_optimizer`, `semi_masker`,
  `plan_mapper`, `logical_plan`, `mask.h`, `node_group.cpp`) all still exist; the files changed by
  30–360 lines each since 0.11.3, namespace is `lbug`, CSR header type renamed `InMemChunkedCSRHeader`.

### Neo4j reference set up (2026-09-22)
- Neo4j 5.26 community in `ext/neo4j` (OpenJDK 21 from conda env `neo4j`), bolt 127.0.0.1:7697, auth off,
  8 GB heap + 8 GB page cache, `db.transaction.timeout=10s`; DBLP imported with neo4j-admin (9 s);
  range indexes on V(pu), V(pd), V(label). Runner `scripts/run_neo4j.py`: one MATCH clause per pattern
  edge (relationship uniqueness is per clause) gives homomorphism counts — all 8 test queries match.
- Per-call overhead ~5 ms; server-side time recorded from the result summary. Community edition runs a
  query single-threaded. 1-hop from 21K index hits: 40–70 ms; 1-hop from a 30% predicate: 630 ms
  (Kùzu 2–5 ms and ~140 ms respectively) — expect many 10 s timeouts on Q-GEN.
- Purpose: cross-system reference (plan §8.11) only; RPT-G is not integrated into Neo4j.

### Ablation M6-acc revisited with degree-sum survival (prototype v5d, 2026-09-22)
- Survival now uses sum deg(B_x)/|E| (the accumulator) instead of |B_x|/|V|. Exact accumulators vs a
  sequential 1,000-member sample, 1k subsamples, median of 3 interleaved reps, paired per query:
  DBLP all queries geomean ratio 1.025, hub-predicate queries (n=268) 1.033, exact better by > 5% on
  24% of hub queries, sampled better on 6%. LJ (n=770): all 1.014, hub queries (n=222) 1.034 (exact better
  on 26%, sampled better on 15%), non-hub 1.006; hub-query geomean speedup 1.103 (exact) vs 1.068 (sampled).
- Reading: with the right formula the accumulators do separate from sampling on hub predicates, but
  by a few percent — a supporting detail for §3.3 (degree skew), not a headline. In Kùzu the same
  quantity was decisive (hub sets have deg 88–193 vs table average 6.6) because there the alternative
  was the table average, not a sample.

### Neo4j runner incident (2026-09-22)
- The first reference run died after ~1,700 rows: a Bolt handshake timed out (60 s) while the server
  was stalled after queries with 10^8-row results (10 s transaction timeout, 8 GB heap). The runner now
  reconnects with backoff (6 attempts) and resumes from the recorded queries (`--resume`).

### Host estimates are bad in DuckDB too, in a different way (2026-09-22)
- DuckDB 1.3 pushes `FLOAT col < DOUBLE literal` into the scan as `CAST(col AS DOUBLE) < literal`
  whenever the literal cannot be narrowed to FLOAT; its cardinality estimate for such an expression
  filter is the 20% default. In Q-GEN this hits every selectivity below ~1e-4 — 112 of 300 DBLP
  queries, and exactly the predicates whose transfers pay off. RPT-G's first DuckDB run inherited the
  estimate through `table_filters` and dropped the best filters (geomean 0.997 vs RPT+ as-is 1.172
  against the no-filter fork). Reading the min/max zone map through the cast repairs it (q1747: 1.3 s
  -> 0.17 s). Same theme as Kùzu's 10%/table-average estimates: the graph-native decision needs its own
  selectivity path (zone maps + exact degree sums), not the host's numbers.

## 2026-09-29

### Kùzu on LiveJournal: the host's own semi-mask is a net loss, RPT-G halves total time
- Stage E, LJ Q-GEN, 3,746 evaluated, noise floor 3.5%: RPT-G < 0.8× 4.5%, < 0.5× 0.4%, geomean 2.19, total
  1,902 s vs 3,693 s without masks; Kùzu semi-mask 29.5% / 15.1% / 0.86 / 4,415 s. On queries ≥ 100 ms RPT-G is
  ~3× faster; 83 baseline failures (timeouts, full buffer pool) become successes, 3 new ones (q3321 re-run: 535 ms
  vs 904 ms, the recorded timeout was a machine stall). With DBLP (4.6% / 0.0% / 1.92) this is the host result.

### The fair host baseline (row-exact masks for Kùzu's semi-mask too) does not close the gap
- KSX = Kùzu semi-mask with `exact_semi_mask`: geomean 1.07 → 1.24 against no masks, regressions unchanged
  (15.7% below 0.8×, 4.8% below 0.5×, 25 new timeouts). RPT-G 1.92 / 4.6% / 0.0% / 0 new timeouts. Exact masks are
  necessary for RPT-G (§7) but not what makes it robust: the decision layer is.

### In Kùzu an extend costs per touched vector, not per source row (LJ q1108)
- Path v0 ← v1 → v2, v0 = top-0.04% degree (1,882 hubs, avg degree 1,163), v1 uniform 1.3% (60,935). RPT-G pushes
  hubs → v1 (2.19M adjacency entries, 75 ms): |B_v1| 60,935 → 5,940. The model predicted ~22K survivors with the
  table-average degree and ~317K extended rows per extend — the rows were right (329K; the survivors are the
  high-degree neighbours of hubs, and Jensen's gap on the survival cancels the friendship-paradox gap on their
  degree). But the extends' time did not follow the rows: SCAN_REL_TABLE CPU 42.8 → 44.2 ms and 29.6 → 40.9 ms for
  10× fewer sources and 2.6× fewer rows. Query 34 → 115 ms.
- Kùzu scans a rel table per 2,048-node vector of sources; 5,940 random sources still touch ~92% of LJ's 2,367
  vectors, so a reduction pays at the vector level only once |B| < n/2048 (DBLP: 155 nodes, LJ: 2,367). The
  model charges extends per produced row and masked scans per surviving row — both wrong for sparse sets. The
  host cost model needs a touched-vectors term V·(1 − (1 − |B|/n)^2048) per scan and per extend source, and a much
  smaller per-row weight for factorized extend output; calibrate from profiled plans like the transfer cost was
  (stage-E measurement). The transfer side is underestimated too: a hub push inserts at ~34 ns per entry, not the
  12.5 ns calibrated on DBLP.
- Same lesson as the vector-granular masks of Kùzu 0.11.3 (2026-09-21), one level up: the host's unit of work is
  the vector, and the decision model has to count in the host's unit.

### DuckDB: a plan-time decision layer cannot see what the host's scans do (q3978)
- Interleaved 4-way run (vanilla / RPT+ / fork without filters / RPT-G): against the no-filter fork RPT+
  26.2% < 0.8×, geomean 0.965, 87 s; RPT-G 24.5%, 1.004, 65 s (fork 74 s). The fork itself is 15% slower than
  vanilla. RPT-G cuts RPT+'s total time by 25% but not its small-query regressions.
- RPT+'s cascade filter pushes [min, max] of the build keys into the apply scan; E is in CSR order and graph ids
  have locality, so a few hundred co-author keys prune 70–90% of an E scan, and an empty key set prunes all of it
  (q3978: RPT+'s E scans read 0.73M rows, RPT-G's choice 4.0M). The model counts rows leaving scans with
  independence estimates; neither locality nor emptiness is visible before the build sides exist.
- The graph hosts do not have this problem because their decisions run at execution time on exact mask sizes.
  For §7: the decision layer belongs in the execution engine, not in the optimizer — the DuckDB plan-time port
  is the negative control.

### LadybugDB: per-thread operator setup dominates small queries
- In LadybugDB 0.21 every worker thread of a pipeline copies the operator tree under the task lock and
  initialises its own scan states before the sink runs; a rel-scan pipeline costs ~0.3 ms per thread. A skipped
  RPT-G transfer was therefore not free (~2.7 ms at 8 threads), and a transfer from 12 vertices took 3.4 ms on
  8 threads vs 0.5 ms on one. Fix: `Sink::participate()`, called before the per-thread copy; the RPT-G sink
  decides there, admits no thread to a skipped transfer and one thread per 16K adjacency entries to an executed
  one (skipped-transfer gap 2.7 → 0.2 ms on q780).
- The main plans of the small queries are themselves dominated by such fixed costs (q780: 3 rel scans spend
  10–15 ms of CPU each for 36–703 rows), which no reduction can remove; the model's tuple-proportional gain is
  an overestimate there.

### LadybugDB's wrong counts are upstream
- q293 / q790 / q4016 / q4511 return the same wrong counts in the unpatched build (`ext/ladybug_vanilla`, same
  commit) as in the patched one, in every configuration (q4511: 3,587,767 vs 265,279,967 in Kùzu, the prototype
  and Neo4j). Worth an upstream report with a minimal reproduction.

### Neo4j 5.26 reference on DBLP Q-GEN
- 5,000 queries, 2 reps, 10 s timeout, single-threaded (community edition), range indexes on pu/pd/label; 0 count
  mismatches against the prototype on 4,114 queries. 895 timeouts (Kùzu without masks 307, Kùzu + RPT-G 267).
- Where both finish (4,057), Neo4j vs Kùzu without masks: geomean time ratio 0.72 (Neo4j faster on 59%; 2.5×
  faster on 20–100 ms queries, where its index seek starts from the selective vertex); Kùzu + RPT-G is 1.43×
  faster than Neo4j. Cross-system numbers only (plan §8.11): different threading, plans and storage.

### Analysis bug fixed: failures in the warm-up disappeared from host tables
- The host runners stop running a config after its first failure; a failure in the warm-up is recorded as rep 0
  only, and `analyze_host.py` took the median over reps > 0 — so such queries dropped out of every table instead
  of counting as timeouts (and rep 0 was never used). Fixed: a config that failed in any rep is a timeout for that
  query, the median uses every recorded rep. The Kùzu stage-E DBLP numbers were computed correctly before and are
  unchanged; the LadybugDB 300-query stage-E table changes (LR2 < 0.8× 11.5% → 7.6%, geomean 1.190 → 1.211).

## Phase 2 (2026-09-29): hosts, cycles, and where the gains come from

### Gain = headroom that the host's estimates leave (docs/reports/gain_diagnosis.md)
- Same 1k samples, only the join order differs (prototype v8 `--order exact|est`; est = greedy on a constant
  10% selectivity per predicate, like Kùzu). All 1,000 queries, timeout = 10 s:
  DBLP M0 376 -> 490 s, RPT-G 358 -> 356 s; LJ M0 2,632 -> 2,993 s, RPT-G 2,367 -> 2,453 s.
  RPT-G geomean 1.035 / 1.079 (exact) vs 1.339 / 1.321 (estimate); under exact orders only 12-13% of the
  queries have >= 10% headroom even with a free full reduction.
- The paper's new thesis: predicate transfer on graphs removes the dependence on the estimates; it does not
  make good plans faster. Hosts with poor estimates (Kùzu, DuckDB) gain most, PG (histograms) least.

### Cycles
- Prototype v8: spanning tree + closing edges (both directions between the passes), provenance rule only on
  bridges, join checks closing edges by intersecting sorted adjacency lists. 1,000 cyclic queries (triangle,
  square, diamond, tailed triangle, pentagon, house, triangle with two tails), all 5 methods agree on counts.
  < 0.9x: static 49%, Yannakakis 71%, arc consistency (M5, subgraph-matching filter) 83%, RPT-G 7.5% (noise
  6.7%); under the 10%-estimate order RPT-G geomean 1.17, 4.5% < 0.9x.
- Kùzu closes cycles with multi-key hash joins (no INTERSECT in our plans); the integration needed only
  isConnected + closing edges + bridge-only provenance. PG and DuckDB integrations handle cycles as is.

### Host integrations: the benefit model must follow the host's join tree
- PG and DuckDB: bushy hash-join trees; reading a left-deep order off the leaf order made the core believe a
  bad plan started at a 4-vertex set (no transfer admitted, 187 ms). Host-plan mode: the core evaluates the
  host's join tree (node rows = sub-pattern matches under the candidate sets, configuration model with exact
  degree sums), excludes the root (the result) and nodes that already contain x and the edge; same query 97 ms.
- Filter cost matters in hash-join hosts: a bitmap test on each of 2.1M scanned rows can outweigh the saved
  probe rows (DuckDB q3: +15% before charging c_filter).
- PG: predicate sets are not sunk (index lookups on reached vertices only); first version geomean 0.73. Fixes:
  plan-time pre-screen on PG's own row estimates (create_upper_paths_hook), evaluate only needed predicates,
  c_pred per row. PG under its own plans: parity (0.96 geomean in the execution-time version).
- DuckDB: side-connection queries cost ~1.5 ms each; count(*) FILTER is slow (10 ms for 5 predicates);
  zone-map selectivity pre-screen needs no query. Our GCC-9 build is 10-30% slower than the official binary
  on some queries: the RPT-G effect is measured against our own build with RPTG_MODE=0.
- Kùzu: identifier predicates become PRIMARY_KEY_SCAN; treat as |B| = 1 and never register PK scans as mask
  consumers (KU_UNREACHABLE in map_semi_masker otherwise).

### LSQB-P in Kùzu (parameterized LSQB templates, SF1)
- q1 (8-vertex path) anchored at a country: 23.2 s -> 0.94 s; anchored at country and tag class: 23.9 s -> 0.25 s
  (Kùzu semi-mask 17-26 s); other templates at parity. Full 160-query run: results/kuzu_lsqbp_sf1.csv.

### LSQB-P in Kùzu (full run, results/kuzu_lsqbp_sf1.csv, 160 queries, SF1, 60 s timeout, noise 7.5%)
- RPT-G geomean 1.86 (KSM 1.26), total 510 -> 113 s (KSM 495 s), 1.9% < 0.8x; q1c x10.2, q1ct x13.4 (max x125).
- Missed: q2p (person-anchored 4-cycle) KSM x2.96, RPT-G x0.98; q6t KSM x1.55, RPT-G x0.97. Kùzu plans these with
  INTERSECT (WCOJ), which the integration did not recognize (added 2026-09-29: INTERSECT transparent, modelled as
  one hash join per build). Even recognized, RPT-G does not help q2p: the main plan reaches the reduced vertices
  through EXTENDs, and Kùzu 0.11.3 applies masks only to node scans (no neighbour masks, unlike LadybugDB); Kùzu's
  own semi-mask works through its hash-join SIP path instead. Host limitation for §7 / limitations.

### Final host results (2026-09-30, host core v3; pg_rptg v3; DuckDB pass v4)

| run | RPT-G | notes |
|---|---|---|
| Kùzu DBLP cycles (863 q) | 4.55x, 1.3% < 0.8x (noise 4.9%), 794 -> 397 s | semi-mask 2.30x; by shape 3.3-6.2x |
| Kùzu LSQB-P rerun (160 q) | 1.83x, 599 -> 118 s, max 121x | semi-mask 1.25x; q2p/q6t missed (INTERSECT/extend paths have no mask consumer) |
| PG random orders (1,918 pairs) | 4.83x per pair, 1.6% < 0.8x, 322/2 timeouts fixed/new | factor 43.2 -> 10.7; 131/142 remaining timeouts = 9 queries with 1-10M matches |
| DuckDB random orders (1,918 pairs) | 1.66x per pair, 2.9% < 0.8x, 50/0 | factor 6.73 -> 3.19; slowest-order sum 140 -> 19.8 s |
| PG own plans (300 q, 256 eval) | 1.03x, 9.4% < 0.8x (noise 8.2%), 146.6 -> 143.0 s | 0.1-1 s: 1.14x; short queries = PG planning time, RPT-G adds 0.05-0.2 ms |
| DuckDB own plans, forced transfers | -2% total | no headroom under its own plans |
| Prototype v8 trees | DBLP 1.04x / -15%, LJ 1.10x / -22% | regressions = noise (9.8% vs 9.2%, 12.8% vs 12.2%) |
| Prototype cycles, est order | DBLP 1.17x, LJ 1.28x | LJ: 38 timeouts fixed |

The story holds across hosts: gains = headroom the plan leaves. Relational hosts under their own plans: parity;
under random orders: large gains. The decisive relational-host fixes were in the benefit model (per-edge undo,
prescreen moments), exact predicate statistics (column index), self filters, and the empty short-circuit.
| PG cycles (813 q) | 1.05x, 0.9% < 0.8x (noise 1.7%), 675 -> 627 s, 8/2 | >= 1 s: 1.10x |
| DuckDB cycles (958 q) | 1.18x, 0.8% < 0.8x (noise 0.5%), 438 -> 340 s, 6/1 | 0.1-1 s: 1.71x, >= 1 s: 1.63x; cycles = two-key hash joins over big intermediates |
| DuckDB own plans v4 (284 q) | 1.00x, 78.0 -> 75.9 s | 10/300 admit (1.34x, none slower); 3.5% < 0.8x all on untouched plans |

## Counting inside the hosts (2026-10-06, host core v4)

| host, workload | configuration | < 0.8x | geo | total | timeouts fixed |
|---|---|---|---|---|---|
| PG19, DBLP-300 | transfers only (v3, `pg19_rptg_dblp300.csv`) | 9.4% | 1.03 | 146.6 -> 143.0 s | 2/44 |
| PG19, DBLP-300 | transfers + counting join (`pg19_count_dblp300.csv`) | 5.1% (noise 2.0%) | 5.73 | 606 -> 87 s (10 s cap) | 40/46 |

| DuckDB 1.3, DBLP-300 | transfers only (pass v4, `duckdb_rptg_dblp300.csv`) | 3.5% | 1.00 | 78.0 -> 75.9 s | 0/0 |
| DuckDB 1.3, DBLP-300 | transfers + counting join (`duckdb_count_dblp300.csv`) | 0.7% (noise 1.1%) | 11.9 (1 ms timer floor) | 255 -> 14 s (10 s cap) | 16/16 |

| Kùzu 0.11.3, DBLP-300 | transfers only (stage G, KR2 in `kuzu_count_dblp300.csv`) | 3.2% | 2.04 | 268 -> 234 s (10 s cap) | 3/18 |
| Kùzu 0.11.3, DBLP-300 | transfers + counting join (KRC, 2026-10-14) | 3.5% (noise 7.1%) | 4.65 | 268 -> 9 s (10 s cap) | 18/18 |

The regressions of the PG counting configuration are 13 queries below 20 ms (median loss 1.4 ms); DuckDB's are
two queries (13 and 16 ms lost); Kùzu's are ten, nine of them below 35 ms (median loss 4.9 ms) and one of 241 ms
(73 ms lost). Counts agree with the host on every finished query in all three. Kùzu's gain is the smallest of
the three because its baseline is the fastest on this sample (87.7 s evaluated, 18 failures, against 146.7 s / 46
for PostgreSQL and 89.3 s / 16 for DuckDB); queries above 1 s still run 49x faster (`docs/kuzu_integration.md`,
stage G).

## RPT-G against RPT+ in DuckDB (2026-10-15, `results/duckdb300_rptplus.csv`)

Added after review. Same 300-query DBLP sample, DuckDB 1.3.0 everywhere: the official CLI, the
RPT+ fork (embryo-labs/dynamic-predicate-transfer, head e5a5633) as-is and with every filter plan dropped
(`RPTG_MODE=1 RPTG_BETA=0`), and our build with RPT-G off / transfers only (`RPTG_COUNT=0`) / transfers + counting.
284 queries evaluated (16 baseline timeouts in every non-counting configuration), counts identical everywhere.
Both GCC builds are slower than the official binary (fork 0.90, ours 0.94 with RPT-G off), so each method is
compared with its own baseline:

| method (vs its own baseline) | < 0.8x | noise | > 1.25x | geomean | 0-20 ms | 20-100 | 100-1000 | > 1 s | total (284) | timeouts fixed |
|---|---|---|---|---|---|---|---|---|---|---|
| RPT+ vs fork without filters | 18.7% | 2.4% | 20.8% | 1.03 | 0.85 (29% regress) | 1.13 | 1.36 | 1.14 | 95.1 -> 88.8 s | 0/16 |
| RPT-G transfers vs our build off | 2.8% | 2.8% | 7.4% | 1.02 | 1.01 | 1.02 | 1.04 | 1.03 | 99.4 -> 98.6 s | 0/16 |
| RPT-G transfers + counting | 0.4% | 2.8% | 92.3% | 12.0 | 6.5 | 8.8 | 24 | 196 | 99.4 -> 14.0 s | 16/16 |

- RPT+ reaches more of the mid-sized queries than RPT-G's transfers (1.36 against 1.04 between 100 ms and 1 s):
  it filters inside every hash join with no budget. It pays on the small queries (53 regressions, median baseline
  15 ms, median loss 6 ms, worst 0.31x). RPT-G's budget keeps the regressions at the noise floor and admits few
  transfers in DuckDB (10 of 300, see "Final host results"), so its gain on this host is small; the counting join
  is 12x over either. Per query, RPT+'s ratio beats RPT-G's by more than 1.25x on 21% of the queries and loses by
  that margin on 22%.
- Against the official CLI: RPT+ 0.92 geomean (33.8% < 0.8x), RPT-G + counting 11.3 (0.7% < 0.8x).
- The earlier four-way run of 2026-09-22 (`duckdb300_4way.csv`) had RPT-G as a pruning layer inside the fork; this
  run is the first with RPT-G in vanilla 1.3.0 against the fork.

## Five graphs (2026-10-07, standalone engine, configuration of record v25)

RPT-G (M6) stays within the noise floor on every graph (YouTube 2.2% vs 4.7%, Orkut 2.4% vs 2.8%, Pokec 2.0% vs
3.0%) while the static semi-mask and the full reduction slow down 77-91% of the queries. The counting join cuts the
total time by 40x (YouTube), 3.7x (Orkut), and 11x (Pokec), and on long chains by 49x (DBLP) and 2.6x (LJ). Details:
`docs/reports/gain_diagnosis.md`, Finding 23; paper Table `tab:graphs`.

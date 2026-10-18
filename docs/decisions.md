# Decisions log (prototype phase)

Chronological record of the design and measurement decisions taken while building the prototype.
Host-integration decisions are recorded in `kuzu_integration.md` and `duckdb_integration.md`.

- 2026-09-17: measurement: rep-major interleaving of methods (rptg_v3 driver), see insights.md.
- 2026-09-17: prototype first, DuckDB/DuckPGQ integration after Judgments 1 and 2 (plan Part 12).
- γ = 10K instead of RPT+'s 100K: sampling is over a random word permutation (unbiased), so a
  smaller sample suffices; RPT+ needed 100K because sequential sampling is biased. Sensitivity sweep pending.
- Case C pilot is skipped (direct PUSH) when the pilot alone would cost more than the push.
- 2026-09-17: degree accumulators are recomputed by one in-order pass over the new bitmap after a
  PUSH (monotone access into compact `dout/din` arrays) instead of per-set-bit random lookups; the
  latter cost ~30 ns per adjacency entry and dominated M6's overhead on small queries.
- 2026-09-17: plan-time usefulness pruning (M6): given the host join order, a transfer x->y is
  executed only if its information is consumed — the join probes B_y entering through another edge
  (or y is the start variable), or a later effective transfer uses y as a source. Source-skip
  (Lemma P5) is simulated at plan time to decide effectiveness. Pushes into predicate-less leaves
  and single-predicate queries now do zero transfer work.
- 2026-09-17 (v4): transfer budget with accumulator-based benefit estimate and the same-edge
  round-trip correction; see insights.md. Driver binaries: rptg_v3 (interleaved reps),
  rptg_v4 (+budget, +init_ms column).
- 2026-09-18 (v5b): semi-join-aware survival estimates in the edge-scan criterion, LEVELS(...) per-level join accounting in ops. Driver binary rptg_v5b (final for robustness).
- 2026-09-18 (v5): BitmapEdgeScan (materialized filtered adjacency, rank-indexed) for M4/M6,
  running-prefix estimate fix, ORDER(...) logged in ops. Driver binary rptg_v5.
- γ = 2000 (was 10K): pilots on DBLP-size sets cost more than the queries they were meant to protect.


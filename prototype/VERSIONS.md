# Prototype binaries

`make` builds `bin/rptg` from `src/` (one translation unit, `-O3 -march=native`). The source in
`src/` is the latest version (a fresh build is byte-identical to `rptg_v8`). The older binaries are
kept in `bin/` (not versioned in git) because the historical CSVs in `results/` were produced with
them; every result file names its driver version in `results/README.md`.

| binary | date | what changed | used for |
|--------|------|--------------|----------|
| rptg_v1 | 2026-09-17 | M0/M3/M4/M6 with Algorithm 1'/2' (root + child order; push/pull/skip/abort) | first DBLP run (`dblp_qgen.csv`) |
| rptg_v2 | 2026-09-17 | join-side probe elimination (`reduced_via`), plan-time usefulness pruning, ordered degree accumulators | `dblp_qgen_v2.csv` |
| rptg_v3 | 2026-09-17 | rep-major interleaving of methods (required on the shared machine) | `*_v3.csv` |
| rptg_v4 | 2026-09-17 | transfer budget `--beta` with survival-based benefit, same-edge round-trip correction, `init_ms` column | Judgment 1 numbers, beta/gamma/tau sweeps |
| rptg_v5 | 2026-09-18 | BitmapEdgeScan (materialized filtered adjacency, rank-indexed) for M4/M6, `--edge-scan`, `--scan-beta`, `ORDER(...)` in ops | `dblp_qgen_v5.csv`, `lj_qgen_v5.csv` |
| rptg_v5b | 2026-09-18 | semi-join-aware survival in the edge-scan criterion, per-level join accounting (`LEVELS(...)`) | final Q-GEN (`dblp_qgen_v5b.csv`) and join-order robustness (`*_robust100*.csv`) |
| rptg_v5c | 2026-09-22 | predicate compare in double (3 count mismatches vs the hosts were float rounding) | count validation |
| rptg_v5d | 2026-09-22 | `--surv-deg`: survival from the degree sum Σdeg(B_x)/\|E\| instead of \|B_x\|/\|V\| | M6-acc ablation revisited (`abl_*1k_*.csv`) |
| rptg_v6 | 2026-09-29 | `--order est`: host-estimate join order (greedy on a constant selectivity per predicate, `--est-sel`, default 0.1 as in Kùzu) | `order_{exact,est}_*1k.csv` (headroom vs optimizer quality) |
| rptg_v7 | 2026-09-29 | cyclic patterns: closing edges checked by intersecting sorted adjacency lists (iterate the shortest), M5 arc consistency, RPT-G transfers along closing edges, provenance rule on bridges only | (superseded by v8 before any full run) |
| rptg_v8 | 2026-09-29 | online filtered adjacency (`--adaptive-scan 1`, default): a probing join step builds its BitmapEdgeScan as soon as its scanned entries reach the build cost (ski rental), independent of plan-time estimates | `order_*`, `cyc_*`, Q-GEN reruns |

Run any of them through `scripts/run_sharded.sh` with `RPTG_BIN=prototype/bin/rptg_vX`.
Flags are documented in the top-level README; `--methods` selects M0,M3,M4,M6.

## Host core (not a benchmark driver)

The source after v8 adds the host API (`src/rptg_api.h`, `src/rptg_c.{h,cpp}`) used by the PostgreSQL extension
and the DuckDB pass: `Engine::reduce` / `prescreen`, the host-plan benefit model (join tree of the host,
restriction-aware rows, configuration model with exact degree sums, second degree moments per candidate set,
parameterized inner scans, root and contained-node exclusion), and the pre-screen costs `pred_cost`,
`first_cost`, `filter_cost` with a two-level (optimistic / exact small-set) mode. With no host plan and these
costs at 0, M6 decides exactly as v8 (`tests/test_api.cpp` checks the API against the driver's M6).

Host core v3 (2026-09-30, used by pg_rptg v3 and the DuckDB pass v3): per-edge undo in the host-plan model (a
transfer x->y along edge e keeps the e-edges between B_x and B_y; the configuration model sees y's degree sum from
before transfers along e), filter cost of inner index scans = rows their join looks up and of a vertex scan with a
predicate = the predicate's rows, second moments of unconstrained vertices in `prescreen` (were 0), self filters
(`TOp{x,x,-1}`: a predicate vertex's own set on the host's scans that reach x before its predicate;
`rptg_self_filters`), predicate column index (`rptg_colindex_*`: exact size / degree sums / moments of a range
predicate by binary search), `rptg_set_trace` / `RPTG_TRACE` (host-plan rows per node to stderr). The standalone
driver's M6 (no host plan) is unchanged.

| rptg_v9 | 2026-10-01 | counting join for tree patterns (`C0` = no transfer, `M7` = RPT-G transfers): the forward pass over the counting semiring (cnt_x(v) = prod_children sum over neighbours), each edge in the cheaper direction, mod 2^64; ski rental: enumerate until the work reaches the exact counting cost | `count_{dblp,lj}1k.csv` |
| rptg_v10 | 2026-10-01 | `--col-index 1`: predicates from sorted column indexes with degree prefix sums (all methods, incl. M0); counting switch predicted from the plan estimate (`--count-far 8`, `--count-patience 4`); `--min-work 20000`: no transfer phase (and no plan-time edge scan) when the estimated join is below 20K entries | `count10_{dblp,lj}1k.csv` |
| rptg_v11 | 2026-10-01 | push computes size/degree sums/moments on the fly (no count + recompute passes); `--word-cost`: budget charges bitmap words per transfer | `count11_*` |
| rptg_v12/v13 | 2026-10-01 | plan-time edge scans only if saved scans >= build price (incl. words); online edge scans (`--extrapolate 1`) only if the rest of the level, extrapolated from the outer loop's progress and discounted by the observed hit rate, pays the price and each source vertex is visited once on average | `count13_*` |
| rptg_v14/v15 | 2026-10-01 | counting: unconstrained leaves contribute their degree (no pass); count arrays indexed by rank in B (O(|B|) memory, no page faults); counting cost = rank tables + 3 x entries (`--count-unit`) | `count15_*` |
| rptg_v16/v17 | 2026-10-05 | RPT+ mechanisms in graph form: `--cascade 1` coarse-to-fine membership tests (two-level word summary + [lo,hi] clamp, galloping over empty words) in push/pull/probe/edge scans/counting; `--push-abort 1` random-order push abandoned when the extrapolated survival exceeds tau_sel; `--reach-pilot 1` survival measured among join-reached vertices rescales the budget of expensive transfers; `--sibling-order 1` most selective child first; `M8` = upfront choice between counting and enumerating (`--count-far`) | `abl17_{dblp,lj}1k_{A,B,C,D}.csv` |
| rptg_v17b/v18 | 2026-10-05 | M8 without the patience rule and with the min_work guard (upfront decision never hurt: DBLP geo 1.50 vs M7 1.47, LJ 1.84 vs 1.75); v18 splits the join counter into `join_work` (entries scanned) and `join_out` (entries counted by the last-level shortcut, i.e. output) and writes `join_out` as the last CSV column | `abl17b_*`, `final18_{dblp,lj}1k.csv` |

Final configuration (2026-10-05): `--col-index 1 --min-work 20000 --word-cost 0.3 --extrapolate 1 --cascade 1 --count-far 8`,
methods M0/M3/M4/M6/M8 (`scripts/final_run_v18.sh`). Push abort, reach pilot, and sibling order stay available as flags;
the four-configuration runs (`abl17_*`) showed no measurable effect because the transfer phase is ~1% of RPT-G's time.
| v18c protocol | 2026-10-06 | `--warm-each 1` (every measured run preceded by a run of the same method) and two process groups: main = M0,M6,M7,M8, base = M0,M3,M4 (`scripts/final_run_v18c.sh G N main|base`); M4's memory churn widens the timing noise of later methods in the same process (M6 < 0.9x: 7.6% without M4 present vs 19.6% with it on the same queries, identical sums) | `final18c_{dblp,lj}1k_{main,base}.csv` |
| rptg_v19-v23 | 2026-10-06 | benefit model after the hub audit: `--deg-surv 1` degree-weighted survival (per-set log2-degree histograms `VarState::H`); push statistics by an ordered pass again (v21: the per-vertex random reads cost 73 ns/entry); cap counts only the levels after the one that enters y (v22); `skip_unit` 24 (a cascade jump costs ~100 ns); `--beta 0.25` (a transfer entry costs ~5x a join entry on LJ-size bitmaps); `--count-benefit 1` values a transfer also by the counting cost it removes, only when counting is plausible (v23: E >= C) | `final19_*`, `final20_*`, `final22_*`, `final23_*` |
| rptg_v24/v25 | 2026-10-06 | v24: histograms without random degree reads at init (Finding 18); v25: `--beta-count` (counting benefit at its own unit, default 1), `--beta auto` online calibration (not used: pooled unit costs admit too much, Finding 19), BETA(...) in the decision log. **Configuration of record**: `scripts/final_run_v25.sh` (`--deg-surv 1 --count-benefit 1 --beta 0.25 --beta-count 1`, protocol v18c) | `final24_*`, `final25_*` |
| rptg_v26 | 2026-10-06 | M8's upfront counting decision no longer skips the transfer phase: the transfers run under the counting benefit alone (`count_only`: a transfer is worth its reduction of the counting cost, at `beta_count`; the enumeration benefit is 0 because no enumeration follows), then the counting pass and the edge scans see reduced sets. v25 lost up to 20x against the ski rental on 8 of the 143 upfront queries (e.g. LJ q1648: M7 39 ms, M8 825 ms, 8.2e8-entry edge scan over unreduced sets). M0/M6/M7 unchanged; `test_api` 300/300 | `up_*` (upfront subsets, Finding 20); not adopted: the paper is frozen on v25 |

Host core v4 (2026-10-06, used by pg_rptg and the DuckDB pass; the standalone binaries are unaffected): the counting
join for hosts. `rptg_count_decide` (from plan-time estimates: count when C <= host_factor x E with E >= 20K, or
C <= count_floor, because E from degree sums under independence can be two orders of magnitude low on hub
neighbourhoods and a host has no ski rental), `rptg_count` (`Engine::count_host`: states from the host's bitmaps,
transfers under the counting benefit alone, `count_tree`). In counting mode the transfer phase skips the tiny guard
and treats every effective transfer as useful (a transfer along the entering edge shrinks the count arrays of an
unconstrained vertex from n to a few entries: DBLP q2825 3.5 ms against 350 ms for PostgreSQL's plan). Defaults:
factor 8, floor 2e6 (`RPTG_COUNT_HOST` / `RPTG_COUNT_FLOOR`, `rptg.count_host` / `rptg.count_floor`).
Kùzu (stage G, 2026-10-14): the same path in `rptg_transfer_optimizer.cpp` (`rptgTryCount`), with the adjacency
index and the predicate sets read through a side connection (bound filters rendered back to Cypher, doubles at full
precision); settings `rptg_count`, `rptg_count_host`, `rptg_count_floor` (per connection). DBLP-300: geo 4.65, 268 -> 9 s,
18/18 failures fixed, 3.5% < 0.8x against 7.1% noise, 0 count mismatches (`results/kuzu_count_dblp300.csv`).

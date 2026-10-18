# Results

Every CSV is one run of one query file. Prototype CSVs have one row per (query, method, rep); host
CSVs one row per (query, config, rep) with `status` in {ok, timeout, error}. Analyse with
`scripts/analyze.py` (prototype) or `scripts/analyze_cli.py` (host CLI runs). Shard directories
(`shards_*/`) are the raw per-process outputs and logs of a sharded run; they are merged into the CSV
named like the directory and can be deleted once the merge line appears in the `.log` file.

Planned once all runs have finished: move the files marked **final** to `final/`, the plots to
`figures/`, the rest to `archive/`, and delete `shards_*/`. Until then nothing in this directory is
moved because running jobs write here.

## Prototype (single-threaded, `prototype/bin/rptg_vX`)

| file | driver | workload | what it is |
|------|--------|----------|------------|
| `dblp_qgen_v5b.csv` (+`.png`) | v5b | `qgen_dblp.txt` | **final** DBLP Q-GEN, M0/M3/M4/M6, 3 interleaved reps |
| `lj_qgen_v5.csv` | v5 | `qgen_lj.txt` | **final** LiveJournal Q-GEN |
| `dblp_robust100d.csv`, `lj_robust100.csv` | v5b | `dblp_robust100b.txt`, `lj_robust100.txt` | **final** join-order robustness: 100 output-bounded queries × 50 random orders, `--no-count-shortcut` |
| `dblp_qgen_v4.csv`, `lj_qgen_v4.csv` | v4 | Q-GEN | Judgment 1 numbers (`docs/reports/judgment1.md`) |
| `abl_{dblp,lj}1k_{exact,acc}.csv` | v5d | `qgen_*_1k.txt` | M6-acc ablation with degree-sum survival (exact accumulators vs 1,000-member sample) |
| `dblp_qgen_v4_acc.csv`, `lj1k_{exact,acc}.csv` | v4 | Q-GEN / 1k | first M6-acc ablation (Judgment 2 condition b) |
| `sweep_beta_{0,0.25,0.5,1,2,4}.csv`, `sweep_beta_lj_*.csv` | v4 | 1k subsamples | β sensitivity |
| `sweep_lj_gamma{500,10k}.csv`, `sweep_lj_tausel{02,05}.csv` | v4 | `qgen_lj_1k.txt` | γ / τ_sel sensitivity |
| `dblp_robust100{,b,c}.csv` | v4/v5 | robustness sets | earlier robustness attempts (output-confounded, then v5) |
| `dblp_qgen{,_v2,_v3,_v5}.csv`, `lj_qgen{,_v3,_v5}.csv`, `subset_*.csv` | v1–v5 | various | history of the engine versions; `subset_*` are diagnosis subsets (improved / regressed queries) |

## DuckDB (vanilla 1.3.0 CLI, RPT+ fork, RPT-G decision layer)

| file | config | what it is |
|------|--------|------------|
| `dblp_qgen_duckdb130.csv`, `dblp_qgen_rptplus.csv` | vanilla / RPT+ as-is | **final** Judgment 2: RPT+ regresses 55% of DBLP Q-GEN (`docs/reports/judgment2.md`, `dblp_rptplus_vs_duckdb.png`) |
| `dblp_qgen_duckdb.csv` | DuckDB 1.5.5 python | first host reference (M1) used in Judgment 1 |
| `duckdb300_4way.csv` | vanilla / rptplus / fork / rptg interleaved per query (`scripts/duckdb_300_4way.sh`) | **final** RPT-G stage 1 (mode 1, β = 1) after the CAST-filter fix; `fork` = every filter dropped (RPTG_BETA=0), isolates the fork's hash-join change |
| `duckdb300_*_run2drift.csv` | back-to-back reruns | superseded: the passes saw very different machine loads (fork vs fork drifted) |
| `duckdb300_vanilla.csv`, `duckdb300_*_run1.csv` | first run | vanilla 1.3.0 CLI; `rptg_run1` = decisions with the 20% default for CAST-wrapped predicates (the bug documented in `docs/duckdb_integration.md`) |

## Kùzu 0.11.3 (patched, `hosts/kuzu/`)

| file | configs | what it is |
|------|---------|------------|
| `kuzu_dblp_3way_e.csv` (+`.png`) | KNO / KSM / KR2 | **final** stage E on DBLP Q-GEN: no mask, Kùzu semi-mask, RPT-G |
| `kuzu_dblp_ksx.csv` | KNO / KSX | **final** fair host baseline: Kùzu semi-mask with row-exact masks (`ext/kuzu_dev`) |
| `kuzu_lj_3way_e.csv` | KNO / KSM / KR2 | **final** stage E on LiveJournal Q-GEN |
| `kuzu_dblp_3way_d.csv`, `kuzu_dblp_4way.csv`, `kuzu_dblp300_*.csv` | earlier stages | stage D full run, stage B four-way run, 300-query stage C runs (`docs/kuzu_integration.md`) |
| `kuzu_dblp_qgen.csv`, `kuzu_dblp_qgen_noisy_partial.csv` | K0 | unpatched baseline runs |

## LadybugDB (patched, `hosts/ladybug/`)

| file | what it is |
|------|------------|
| `ladybug_dblp300.csv` | stage-E port, LNO / LSM / LR2 on `qgen_dblp_300.txt` (4 queries with wrong host counts — upstream bug — excluded) |
| `ladybug_dblp300_f.csv` | LNO / LSM / LR2E (stage E) / LR2 (stage F, neighbour masks) interleaved, one build with `Sink::participate` (`scripts/ladybug_300_f.sh`) |

## Neo4j 5.26 (cross-system reference, not integrated)

| file | what it is |
|------|------------|
| `neo4j_dblp_qgen.csv` | **final** DBLP Q-GEN, 2 reps, 10 s transaction timeout |

## Phase 2 final runs (2026-09-29/30; the paper's numbers, via `paper/figgen/data.py`)

| file | engine / version | what it is |
|------|------------------|------------|
| `dblp_qgen_v8.csv`, `lj_qgen_v8.csv` | prototype v8 | **final** tree workloads (LJ on `qgen_lj_ok.txt`, the 3,893 queries whose baseline finished in v5); M5 on DBLP only |
| `cyc_{dblp,lj}{,_est}.csv` | prototype v8 | 1,000 cyclic queries, exact-size / 10%-estimate join order, M0/M3/M4/M5/M6 |
| `order_{exact,est}_{dblp,lj,youtube}1k.csv` (+`.diag.csv`) | prototype v6/v8 | headroom vs optimizer quality (`scripts/diagnose_gain.py`) |
| `kuzu_dblp_cyc.csv` | Kùzu stage F (cycles, INTERSECT) | 1,000 cyclic DBLP queries, KNO/KSM/KR2 |
| `kuzu_lsqbp_sf1_intersect.csv` | Kùzu stage F | **final** LSQB-P (160 queries); `kuzu_lsqbp_sf1.csv` = first run before INTERSECT support |
| `pg19_dblp_robust.csv` | pg_rptg v3 | random join orders (1,918 pairs), PGNO/PGR |
| `pg19_rptg_dblp300.csv` | pg_rptg v3 | own plans, PGNO/PGR/PG1/PGR1 (1 = no parallel workers) |
| `pg19_dblp_cyc.csv` | pg_rptg v3 | 1,000 cyclic DBLP queries |
| `duckdb_dblp_robust.csv` | DuckDB pass v4 | random join orders (1,918 pairs), dk0/dkr |
| `duckdb_rptg_dblp300.csv` | DuckDB pass v4 | own plans, vanilla/dk0/dkr; `_v2_nosf` = pass v2 |
| `duckdb_force_dblp300.csv` | DuckDB pass v3 | headroom check: dkf = every useful transfer forced |
| `duckdb_dblp_cyc.csv` | DuckDB pass v4 | 1,000 cyclic DBLP queries |

Aborted runs (superseded model versions) are kept as `shards_*_aborted_*`; `pg19_rptg_dblp300_v1_execprescreen.csv` is v1.

## Prototype v9-v18 (counting join, RPT+ mechanisms; 2026-10-01/05, idle machine)

| file | driver | what it is |
|------|--------|------------|
| `count_{dblp,lj}1k.csv`, `count10_*`, `count11_*_f{0,8}`, `count13_*`, `count15_*` | v9-v15 | counting join development runs (`docs/reports/gain_diagnosis.md`, Findings 11-12); M7 = RPT-G + ski-rental switch to counting, C0 = counting switch without transfers |
| `abl17_{dblp,lj}1k_{A,B,C,D}.csv` | v17 | RPT+ mechanisms enabled one at a time (A base, B + cascade scans, C + push abort + reach pilot, D + sibling order); methods M0/M6/M7/M8 (M8 with the patience rule) |
| `abl17b_{dblp,lj}1k_D.csv` | v17b | M7 vs M8 after the M8 fixes (no patience rule, min_work guard) |
| `final18_{dblp,lj}1k.csv` | v18 | final configuration, M0/M3/M4/M6/M7/M8 with `join_out` split; tiny-query timings contaminated by method order (Finding 14) — use for operation counts only |
| `final18b_{dblp,lj}1k.csv` | v18b | same with sub-millisecond runs repeated in the harness (M6 still contaminated by M4 in the same process) |
| `final18c_{dblp,lj}1k.csv` | v18c | all six methods in one process with per-method warm runs; operation counts valid, M6/M7 regression rates inflated by M4's presence (Finding 14) |
| `final18c_{dblp,lj}1k_main.csv`, `_base.csv` | v18c | **final** protocol: main = M0,M6,M7,M8 and base = M0,M3,M4 in separate process groups, per-method warm runs (`scripts/final_run_v18c.sh`) |
- 2026-10-06: shard directories of merged runs deleted; aborted/orphan shard dirs archived in `results/archive/shards_aborted_and_orphans_2026-10-06.tgz`; intermediate prototype binaries v9-v18b removed (sources are in git history; v15, v18c kept).
| `final19_*_main.csv`, `final20_*_main.csv`, `final24_*_main.csv` | v19 / v20 / v24 | benefit-model audit steps (`docs/reports/gain_diagnosis.md`, Findings 15-19): degree-weighted survival; + counting benefit; + histogram init fix, cap over later levels, skip_unit 24, beta 0.25. v19-v20 timings carry the 900 ms init of Finding 18 (ratios of small queries compressed) |
| `final25_{dblp,lj}1k_main.csv` | v25 | **configuration of record** for the prototype main group (`scripts/final_run_v25.sh`); base group M3/M4 remains `final18c_*_base.csv` |
| `final25_{dblp,lj}1k_base.csv` | v25 | base group M0/M3/M4 under the v25 binary (same work accounting as the main group): source of the M3/M4 rows of the operation-count table; run on a loaded machine (LJ noise floor 22%), so Table proto's M3/M4 timings stay with `final18c_*_base.csv` |
| `chain25_{dblp,lj}_main.csv` | v25 | long-chain workloads `queries/qgen_{dblp,lj}_chain.txt` (paths of 8-10 vertices, 300 each), main group, 4 shards on a loaded machine |
| `pg19_count_dblp300.csv` | pg_rptg + host core v4 | counting shortcut (decide from estimates, factor 8, floor 2e6, count mode transfers): PGNO/PGR; `_f8` = materialize-first variant, `_f1` = decide-first with factor 1 and no floor |
| `duckdb_count_dblp300.csv` | DuckDB pass + host core v4 | counting shortcut, dk0/dkr |
| `duckdb300_rptplus.csv` | official 1.3.0 CLI / RPT+ fork (as-is, filters dropped) / our build (off, RPT-G, RPT-G + counting) | **final** RPT-G against RPT+ (2026-10-15, `scripts/duckdb_300_rptplus.sh`): six configurations interleaved per query on `qgen_dblp_300.txt`, 1 warm-up + 3 reps, 8 threads, 10 s, 3 shards; analysis `scripts/analyze_cli.py fork=... rptplus=...` and `dk0=... rptg=... rptgc=...` (each against its own binary's baseline) |
| `kuzu_count_dblp300.csv` | Kùzu stage G + host core v4 | counting shortcut in Kùzu 0.11.3 (2026-10-14): KNO / KR2 (`rptg_count=false`) / KRC, `qgen_dblp_300.txt`, 1 warm-up + 3 reps, 8 threads, 10 s, 2 shards (`scripts/kuzu_count_300.sh`); a first run with rounded double literals in the side queries (14 wrong counts) was discarded |
| `final25_youtube1k_{main,base}.csv`, `final25_{orkut,pokec}1k_{main,base}.csv` | v25 | additional graphs (YouTube 1.1M/6.0M, Orkut 3.1M/117M undirected, Pokec 1.6M/30.6M directed), `queries/qgen_<g>_1k.txt` (`qgen.py --n 1000 --seed 7`) |

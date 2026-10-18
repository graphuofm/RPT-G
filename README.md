# RPT-G: Robust Predicate Transfer for Graph Pattern Queries (artifact)

Anonymous artifact for the SIGMOD 2027 submission. Paths in the scripts use `$RPTG_ROOT` for the repository root;
`python` is Python 3.11+ with numpy and pandas.

- `prototype/`: the standalone engine (C++17, single translation unit; `make` builds `bin/rptg`), the C interface
  shared by the hosts (`src/rptg_c.*`), `VERSIONS.md` (every version and the configuration of record, v25).
- `hosts/kuzu`, `hosts/pg19`, `hosts/duckdb`: the integrations (patches against Kùzu 0.11.3, the PostgreSQL 19
  extension `pg_rptg`, the DuckDB 1.3.0 optimizer pass) with build and run notes; the counting shortcut runs in
  all three (`scripts/kuzu_count_300.sh`; the PostgreSQL and DuckDB runs are described in `hosts/pg19/README.md` and `hosts/duckdb/README.md`).
- `scripts/`: workload generator (`qgen.py`), runners, the configuration-of-record scripts (`final_run_v25.sh`),
  analysis (`analyze*.py`); `queries/`: every workload used in the paper (manifest in `queries/README.md`).
- `results/`: the recorded runs behind every number in the paper (manifest in `results/README.md`);
  `paper/figgen/`: the scripts that turn them into the paper's numbers and figures.
- `docs/`: integration notes, the two go/no-go reports, and the diagnosis report (`docs/reports/gain_diagnosis.md`, Findings 1–24).

Graphs: SNAP com-DBLP, soc-LiveJournal1, com-YouTube, com-Orkut, soc-Pokec, converted with `scripts/prep_snap.py`.

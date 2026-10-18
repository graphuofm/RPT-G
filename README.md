# RPT-G: Robust Predicate Transfer for Graph Pattern Queries (artifact)

Anonymous artifact for the SIGMOD 2027 submission.

## Layout

- `prototype/`: the standalone engine (C++17, single translation unit; `make` builds `bin/rptg`), the C interface
  shared by the hosts (`src/rptg_c.*`), `VERSIONS.md` (every version and the configuration of record, v25).
- `hosts/kuzu`, `hosts/pg19`, `hosts/duckdb`: the integrations (patches against Kùzu 0.11.3, the PostgreSQL 19
  extension `pg_rptg`, the DuckDB 1.3.0 optimizer pass) with build and run notes; the counting shortcut runs in
  all three. `hosts/ladybug` and `hosts/neo4j` are exploratory and not in the paper.
- `scripts/`: workload generator (`qgen.py`), runners, the configuration-of-record scripts (`final_run_v25.sh`),
  analysis (`analyze*.py`); `queries/`: every workload used in the paper (manifest in `queries/README.md`).
- `results/`: the recorded runs behind every number in the paper (manifest in `results/README.md`);
  `paper/figgen/`: the scripts that turn them into the paper's numbers and figures; `paper/experiments/`: one
  folder per experiment with the question it answers, the result files, and the captured analysis output.
- `docs/`: integration notes, the two go/no-go reports, and the diagnosis report (`docs/reports/gain_diagnosis.md`).

## Setup

- `export RPTG_ROOT=/path/to/this/clone`; the shell scripts refer to the repository root as `$RPTG_ROOT`.
- `python` is Python 3.11 or newer with numpy, pandas, and matplotlib (figures).
- The engine needs a C++17 compiler (GCC 11 or newer); the host builds need cmake and ninja.
- Upstream sources are cloned by you into `ext/` (`ext/kuzu` at tag v0.11.3, `ext/duckdb_rptg` at v1.3.0,
  `ext/pg19` = PostgreSQL 19); the host READMEs assume these paths.
- Graphs come from SNAP (com-DBLP, soc-LiveJournal1, com-YouTube, com-Orkut, soc-Pokec) and are converted with
  `scripts/prep_snap.py` into `data/bin/<graph>/`.

## Quick start (about one minute, DBLP)

```
export RPTG_ROOT=$(pwd)
make -C prototype                                                   # -> prototype/bin/rptg
curl -L -O https://snap.stanford.edu/data/bigdata/communities/com-dblp.ungraph.txt.gz
curl -L -O https://snap.stanford.edu/data/bigdata/communities/com-dblp.all.cmty.txt.gz
python scripts/prep_snap.py com-dblp.ungraph.txt.gz data/bin/dblp --undirected --cmty com-dblp.all.cmty.txt.gz
head -30 queries/qgen_dblp_300.txt > /tmp/q30.txt
prototype/bin/rptg --graph data/bin/dblp --queries /tmp/q30.txt --methods M0,M6,M8 --reps 3 --warm 1 --timeout 10 \
    --extrapolate 1 --cascade 1 --count-far 8 --warm-each 1 --deg-surv 1 --count-benefit 1 --beta 0.25 --beta-count 1 \
    --out /tmp/q30.csv                                              # the flags of the configuration of record (v25)
python scripts/analyze.py /tmp/q30.csv --base M0                    # regressions, geometric mean, totals
```

Methods: M0 no transfer, M3 static semi-mask, M4 Yannakakis bitmap, M5 arc consistency, M6 RPT-G, M8 RPT-G with the
counting join. The recorded runs are analysed the same way, for example
`python scripts/analyze_host.py results/kuzu_count_dblp300.csv --base KNO`; the paper's figures are regenerated with
`cd paper/figgen && python make_figures.py && python make_explain.py && python make_eval.py`.

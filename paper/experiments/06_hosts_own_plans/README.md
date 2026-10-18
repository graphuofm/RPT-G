# 06_hosts_own_plans

**Paper:** Table 3 (transfer rows), Section 5.5

**Question:** What does RPT-G gain inside each host under the host's own plan, against the host without transfer and against its own sideways information passing?

**Configurations:** Kuzu DBLP and LiveJournal (full 5,000-query workloads), Kuzu cyclic DBLP, Kuzu with row-exact semi-masks (KSX, fairness check), LSQB-P (160 queries, 60 s timeout), PostgreSQL 19 and DuckDB 1.3 on the 300-query DBLP sample. Regression threshold 0.8x, median of 3 reps.

**Result files:** `results/duckdb_dblp_cyc.csv`, `results/duckdb_rptg_dblp300.csv`, `results/kuzu_dblp_3way_e.csv`, `results/kuzu_dblp_cyc.csv`, `results/kuzu_dblp_ksx.csv`, `results/kuzu_lj_3way_e.csv`, `results/kuzu_lsqbp_sf1_intersect.csv`, `results/pg19_dblp_cyc.csv`, `results/pg19_rptg_dblp300.csv`

**Analysis:** see `analysis.txt` (the commands are printed above each block).

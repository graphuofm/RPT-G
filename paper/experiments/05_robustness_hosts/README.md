# 05_robustness_hosts

**Paper:** Table 2 (host rows), Section 5.4

**Question:** The same question inside the hosts: the DBLP queries under 1,918 random (query, order) pairs forced in Kuzu, PostgreSQL and DuckDB.

**Configurations:** Kuzu: KNO no mask, KSM semi-mask, KR2 RPT-G. PostgreSQL: PGNO / PGR. DuckDB: dk0 / dkr (our build off / on).

**Result files:** `results/duckdb_dblp_robust.csv`, `results/kuzu_dblp_robust.csv`, `results/pg19_dblp_robust.csv`

**Analysis:** see `analysis.txt` (the commands are printed above each block).

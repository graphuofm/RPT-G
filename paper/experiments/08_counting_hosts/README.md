# 08_counting_hosts

**Paper:** Table 3 (counting rows), Figure 9, Section 5.6 "Counting in the hosts"

**Question:** Does the counting shortcut work inside the hosts? 300-query DBLP sample, PostgreSQL 19 (PGNO / PGR), DuckDB 1.3 (dk0 / dkr), Kuzu 0.11.3 (KNO / KR2 transfers only / KRC transfers + counting).

**Configurations:** The decision is made from plan-time estimates (count if the counting cost is at most 8x the enumeration estimate, or below 2e6 adjacency entries).

**Result files:** `results/duckdb_count_dblp300.csv`, `results/kuzu_count_dblp300.csv`, `results/pg19_count_dblp300.csv`

**Analysis:** see `analysis.txt` (the commands are printed above each block).

# 10_rptplus_as_is_judgment2

**Paper:** Section 2.3 motivation (RPT+ as-is on graph queries); not a table of the paper

**Question:** What happens when RPT+ is run unchanged on the 5,000-query DBLP workload in DuckDB (the original Judgment 2 of the project)?

**Configurations:** RPT+ fork against the official DuckDB 1.3.0 CLI, one configuration per pass (not interleaved), so machine load differs between the two; used only for the regression share.

**Result files:** `results/dblp_qgen_duckdb130.csv`, `results/dblp_qgen_rptplus.csv`

**Analysis:** see `analysis.txt` (the commands are printed above each block).

# 09_rptplus_vs_rptg_duckdb

**Paper:** Table 3 (RPT+ rows), Section 5.5

**Question:** How does RPT-G compare with RPT+ (the authors' implementation on DuckDB 1.3.0) on the same queries?

**Configurations:** Six configurations interleaved per query: vanilla = official 1.3.0 CLI; rptplus = RPT+ fork as-is; fork = the fork with every filter plan dropped (its own baseline); dk0 = our build with RPT-G off; rptg = RPT-G transfers; rptgc = RPT-G transfers + counting. Each method is compared with its own binary's baseline because both builds are 6-10% slower than the official one.

**Result files:** `results/duckdb300_rptplus.csv`

**Analysis:** see `analysis.txt` (the commands are printed above each block).

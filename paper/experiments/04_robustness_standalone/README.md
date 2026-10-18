# 04_robustness_standalone

**Paper:** Table 2 (standalone rows), Section 5.4

**Question:** Does RPT-G make the join robust to its order? 100 queries per graph under 50 random connected left-deep orders; robustness factor = slowest / fastest order per query.

**Configurations:** M0 = no transfer, M4 = full reduction, M6 = RPT-G.

**Result files:** `results/dblp_robust100d.csv`, `results/lj_robust100.csv`

**Analysis:** see `analysis.txt` (the commands are printed above each block).

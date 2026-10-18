# 01_standalone_trees

**Paper:** Table 4 (standalone engine, 1,000-query samples), Figure 1 (tree part), Figure 8 (operation counts on five graphs), Section 5.2

**Question:** Do the three transfer schemes of graph systems slow queries down, and does RPT-G avoid it under a host-like join order? What does counting add?

**Configurations:** M0 = no transfer, M3 = static one-hop semi-mask, M4 = Yannakakis bitmap (full two-pass reduction), M6 = RPT-G, M8 = RPT-G with the counting join. Regression threshold 0.9x, mean over 3 reps after 1 warm-up, 10 s timeout. The base group (M0/M3/M4) and the main group (M0/M6/M8) ran in separate processes (Section 5.1, Protocol).

**Result files:** `results/final25_dblp1k_base.csv`, `results/final25_dblp1k_main.csv`, `results/final25_lj1k_base.csv`, `results/final25_lj1k_main.csv`

**Analysis:** see `analysis.txt` (the commands are printed above each block).

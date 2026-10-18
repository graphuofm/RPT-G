# 07_counting_standalone

**Paper:** Table 4 (counting rows), Figure 9 (totals of every workload), Section 5.6: five graphs and long chains

**Question:** What does counting instead of enumerating add in the standalone engine, on five graphs and on paths of 8-10 vertices?

**Configurations:** M6 = RPT-G, M8 = RPT-G with counting; YouTube, Orkut, Pokec 1,000-query samples; chain workloads of 300 paths on DBLP and LiveJournal.

**Result files:** `results/chain25_dblp_main.csv`, `results/chain25_lj_main.csv`, `results/final25_orkut1k_base.csv`, `results/final25_orkut1k_main.csv`, `results/final25_pokec1k_base.csv`, `results/final25_pokec1k_main.csv`, `results/final25_youtube1k_base.csv`, `results/final25_youtube1k_main.csv`

**Analysis:** see `analysis.txt` (the commands are printed above each block).

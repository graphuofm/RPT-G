# 12_rptplus_mechanisms_in_graph_engine

**Paper:** Mentioned in Section 3.3 (comparison with RPT+); not a table of the paper

**Question:** Do RPT+'s mechanisms (cascade scans, push abort with reach pilot, sibling order) change anything when ported to the graph engine?

**Configurations:** abl17: A = base, B = + cascade, C = + push abort + reach pilot, D = + sibling order; methods M0/M6/M7/M8. Finding: no measurable effect on M6, because the transfer phase is about 1% of RPT-G's time.

**Result files:** `results/abl17_dblp1k_A.csv`, `results/abl17_dblp1k_B.csv`, `results/abl17_dblp1k_C.csv`, `results/abl17_dblp1k_D.csv`, `results/abl17_lj1k_A.csv`, `results/abl17_lj1k_B.csv`, `results/abl17_lj1k_C.csv`, `results/abl17_lj1k_D.csv`

**Analysis:** see `analysis.txt` (the commands are printed above each block).

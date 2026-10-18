# 03_headroom

**Paper:** Section 5.3

**Question:** Where do the gains come from? How much could any reduction gain under a join order built from exact sizes (order_exact) and under one built from a constant 10% selectivity, as Kuzu assumes (order_est)?

**Configurations:** M4 = full reduction for free (headroom), M6 = RPT-G, on the same 1,000-query samples under the two orders.

**Result files:** `results/order_est_dblp1k.csv`, `results/order_est_lj1k.csv`, `results/order_est_youtube1k.csv`, `results/order_exact_dblp1k.csv`, `results/order_exact_lj1k.csv`, `results/order_exact_youtube1k.csv`

**Analysis:** see `analysis.txt` (the commands are printed above each block).

# Experiments behind the paper

One folder per experiment. Each `README.md` states the question the experiment answers, where its numbers appear in the paper, the configurations, the result files (`results/` in the artifact), and the command that produced `analysis.txt`. `numbers.json` holds the slice of `paper/figgen/numbers.json` that the figure scripts use. The raw per-query CSVs are in `results/` (manifest: `results/README.md`); the protocol (warm-up, repetitions, noise floor) is Section 5.1 of the paper. `extra_figures/` holds plots that were generated but are not in the paper.

| folder | paper | question |
|---|---|---|
| `01_standalone_trees` | Table 4 (standalone engine, 1,000-query samples), Figure 1 (tree part), Figure 8 (operation counts on five graphs), Section 5.2 | Do the three transfer schemes of graph systems slow queries down, and does RPT-G avoid it under a host-like join order? What does counting add? |
| `02_standalone_cyclic` | Figure 1 (cyclic part), Section 5.2 | Does the picture hold on cyclic patterns, including arc consistency (M5), the filter that subgraph matchers use? |
| `03_headroom` | Section 5.3 | Where do the gains come from? How much could any reduction gain under a join order built from exact sizes (order_exact) and under one built from a constant 10% selectivity, as Kuzu assumes (order_est)? |
| `04_robustness_standalone` | Table 2 (standalone rows), Section 5.4 | Does RPT-G make the join robust to its order? 100 queries per graph under 50 random connected left-deep orders; robustness factor = slowest / fastest order per query. |
| `05_robustness_hosts` | Table 2 (host rows), Section 5.4 | The same question inside the hosts: the DBLP queries under 1,918 random (query, order) pairs forced in Kuzu, PostgreSQL and DuckDB. |
| `06_hosts_own_plans` | Table 3 (transfer rows), Section 5.5 | What does RPT-G gain inside each host under the host's own plan, against the host without transfer and against its own sideways information passing? |
| `07_counting_standalone` | Table 4 (counting rows), Figure 9 (totals of every workload), Section 5.6: five graphs and long chains | What does counting instead of enumerating add in the standalone engine, on five graphs and on paths of 8-10 vertices? |
| `08_counting_hosts` | Table 3 (counting rows), Figure 9, Section 5.6 "Counting in the hosts" | Does the counting shortcut work inside the hosts? 300-query DBLP sample, PostgreSQL 19 (PGNO / PGR), DuckDB 1.3 (dk0 / dkr), Kuzu 0.11.3 (KNO / KR2 transfers only / KRC transfers + counting). |
| `09_rptplus_vs_rptg_duckdb` | Table 3 (RPT+ rows), Section 5.5 | How does RPT-G compare with RPT+ (the authors' implementation on DuckDB 1.3.0) on the same queries? |
| `10_rptplus_as_is_judgment2` | Section 2.3 motivation (RPT+ as-is on graph queries); not a table of the paper | What happens when RPT+ is run unchanged on the 5,000-query DBLP workload in DuckDB (the original Judgment 2 of the project)? |
| `11_mechanisms_and_sweeps` | Section 5.7 | How much does each part of the decision contribute (Kuzu stages), is the budget necessary, and how sensitive are the results to beta, gamma and tau_sel? |
| `12_rptplus_mechanisms_in_graph_engine` | Mentioned in Section 3.3 (comparison with RPT+); not a table of the paper | Do RPT+'s mechanisms (cascade scans, push abort with reach pilot, sibling order) change anything when ported to the graph engine? |
| `extra_figures` | not in the paper | plots generated during the work, for reference |

# 11_mechanisms_and_sweeps

**Paper:** Section 5.7

**Question:** How much does each part of the decision contribute (Kuzu stages), is the budget necessary, and how sensitive are the results to beta, gamma and tau_sel?

**Configurations:** Kuzu stages: every useful transfer -> budget on constant estimates -> work model on exact mask sizes -> degree sums + measured cost + row-exact masks. Sweeps: M6 against M0 on 1,000-query samples with beta in {0, 0.25, 0.5, 1, 2, 4}, gamma in {500, 10,000}, tau_sel in {0.2, 0.5}.

**Result files:** `results/sweep_beta_0.25.csv`, `results/sweep_beta_0.5.csv`, `results/sweep_beta_0.csv`, `results/sweep_beta_1.csv`, `results/sweep_beta_2.csv`, `results/sweep_beta_4.csv`, `results/sweep_beta_lj_0.25.csv`, `results/sweep_beta_lj_0.5.csv`, `results/sweep_beta_lj_0.csv`, `results/sweep_beta_lj_1.csv`, `results/sweep_beta_lj_2.csv`, `results/sweep_beta_lj_4.csv`, `results/sweep_lj_gamma10k.csv`, `results/sweep_lj_gamma500.csv`, `results/sweep_lj_tausel02.csv`, `results/sweep_lj_tausel05.csv`

**Analysis:** see `analysis.txt` (the commands are printed above each block).

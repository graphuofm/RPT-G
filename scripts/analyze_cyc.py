#!/usr/bin/env python
"""Cyclic-pattern runs of the prototype (M0 WCOJ-style join without transfer, M3, M4, M5 arc consistency,
M6 RPT-G): regressions (< 0.9x), geomean, totals, count agreement, per shape. usage: analyze_cyc.py RUN.csv META.csv"""
import sys
import numpy as np, pandas as pd
d = pd.read_csv(sys.argv[1], usecols=['qid', 'method', 'rep', 'status', 'total_ms', 'count'], on_bad_lines='skip')
d['total_ms'] = pd.to_numeric(d.total_ms, errors='coerce')
d = d.dropna(subset=['total_ms'])
d.loc[d.status != 'ok', 'total_ms'] = 10000
ms = d.groupby(['qid', 'method']).total_ms.mean().unstack()
tmo = d.groupby(['qid', 'method']).status.apply(lambda s: (s != 'ok').any()).unstack().astype(bool)
cnt = d[d.status == 'ok'].groupby(['qid', 'method'])['count'].first().unstack()
meta = pd.read_csv(sys.argv[2]).set_index('qid')
methods = [m for m in ['M3', 'M4', 'M5', 'M6'] if m in ms.columns]
bad = {m: int(((cnt['M0'] != cnt[m]) & cnt[m].notna() & cnt['M0'].notna()).sum()) for m in methods}
keep = ~tmo['M0'] & ms[['M0'] + methods].notna().all(axis=1)
w = ms[keep]
r = d[d.method == 'M0'].pivot_table(index='qid', columns='rep', values='total_ms')
nz = (r[0] / r[1]).reindex(w.index).dropna()
gm = lambda s: float(np.exp(np.log(s).mean()))
print(f'{sys.argv[1]}: {len(ms)} queries, {len(w)} evaluated, count mismatches {bad}, noise < 0.9: {100 * np.mean(nz < 0.9):.1f}%')
for m in methods:
    sp = w.M0 / w[m]
    print(f'  {m}: <0.9 {100 * np.mean(sp < 0.9):5.1f}%  <0.5 {100 * np.mean(sp < 0.5):5.1f}%  >2 {100 * np.mean(sp > 2):5.1f}%  '
          f'geomean {gm(sp):.3f}  total {w[m].sum() / 1e3:.0f} s (M0 {w.M0.sum() / 1e3:.0f} s)  timeouts fixed {int((tmo.M0 & ~tmo[m]).sum())}')
print('  by shape (geomean):')
for sh, g in w.join(meta).groupby('shape'):
    print(f'    {sh:20s} n={len(g):4d}  ' + '  '.join(f'{m} {gm(g.M0 / g[m]):.2f}' for m in methods) + f'   M6 <0.9 {100 * np.mean(g.M0 / g.M6 < 0.9):.0f}%')

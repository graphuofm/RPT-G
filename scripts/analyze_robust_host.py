#!/usr/bin/env python
"""Join-order robustness inside a host: CSV qid,method,order,rep,status,total_ms,count with every query run
under several forced join orders (scripts/kuzu_robust.sh, run_pg.py --orders, run_duckdb_cli.py --orders).

Per (query, order, config): median over reps; any failed rep = timeout (10 s). Only (query, order) pairs that
every config finished or timed out on are used. Reports per config: robustness factor (slowest / fastest order
per query), sums over queries of the slowest / median / fastest order, the slowest order relative to the
baseline's fastest order, and per (query, order) speedups over the baseline; count agreement.
usage: analyze_robust_host.py RUN.csv --base KNO [--timeout 10]"""
import argparse
import numpy as np, pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument('csv')
ap.add_argument('--base', required=True)
ap.add_argument('--timeout', type=float, default=10)
a = ap.parse_args()
T = a.timeout * 1000
d = pd.read_csv(a.csv)
d = d[d.method != 'CRASH']
d['ms'] = np.where(d.status == 'ok', d.total_ms, T).clip(max=T)
g = d.groupby(['qid', 'method', 'order'])
fail = g.status.apply(lambda s: (s != 'ok').any())
med = g.ms.median().where(~fail, T).reset_index()
p = med.pivot_table(index=['qid', 'order'], columns='method', values='ms').dropna()
cnt = d[d.status == 'ok'].groupby(['qid', 'order', 'method'])['count'].first().unstack()
configs = list(p.columns)
mism = {c: int(((cnt[c] != cnt[a.base]) & cnt[c].notna() & cnt[a.base].notna()).sum()) for c in configs if c != a.base}
nq = p.index.get_level_values(0).nunique()
gm = lambda s: float(np.exp(np.log(np.asarray(s, float)).mean()))
print(f'{a.csv}: {nq} queries, {len(p)} (query, order) pairs, configs {configs}, count mismatches vs {a.base}: {mism}')
best_base = p[a.base].groupby(level=0).min()
print(f'{"config":6s} {"factor geo":>10s} {"med":>6s} {"P90":>6s} {"max":>7s} {"worst sum":>10s} {"median sum":>10s} '
      f'{"best sum":>9s} {"worst/base-best":>15s} {"timeouts":>8s}')
for c in configs:
    q = p[c].groupby(level=0).agg(['max', 'min', 'median'])
    f = q['max'] / q['min']
    print(f'{c:6s} {gm(f):10.2f} {f.median():6.2f} {f.quantile(.9):6.1f} {f.max():7.1f} {q["max"].sum() / 1e3:9.1f}s '
          f'{q["median"].sum() / 1e3:9.1f}s {q["min"].sum() / 1e3:8.1f}s {gm(q["max"] / best_base):15.2f} {int((p[c] >= T).sum()):8d}')
for c in configs:
    if c == a.base:
        continue
    s = p[a.base] / p[c]
    print(f'{c} per (query, order) vs {a.base}: geomean {gm(s):.2f}, < 0.8x {100 * np.mean(s < 0.8):.1f}%, '
          f'> 2x {100 * np.mean(s > 2):.1f}%, > 10x {100 * np.mean(s > 10):.1f}%, timeouts fixed '
          f'{int(((p[a.base] >= T) & (p[c] < T)).sum())} / new {int(((p[a.base] < T) & (p[c] >= T)).sum())}')

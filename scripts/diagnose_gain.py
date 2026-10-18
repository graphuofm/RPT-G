#!/usr/bin/env python
"""Where do the gains go? Headroom / capture analysis of a prototype run (M0, M4, M6 with phase times).

Per query (mean over measured reps):
  floor    = init_ms of M0: predicate scans + planning, paid by every method (Amdahl floor)
  ideal    = floor + min(join_ms of M0, join_ms of M4): the query with full reduction delivered for free
  headroom = M0 total / ideal          (what any transfer scheme could gain at most)
  achieved = M0 total / M6 total       (what RPT-G gained)
  capture  = log(achieved) / log(headroom) for queries with headroom >= 1.1
Classes of queries with headroom >= 1.1:
  captured : achieved >= sqrt(headroom)
  eaten    : M6 transfer time >= half of the headroom gap (M0 - ideal) -> transfer cost ate the gain
  missed   : otherwise -> M6's join stayed slow (a profitable transfer was skipped or aborted)
usage: diagnose_gain.py RUN.csv [--meta META.csv]
"""
import argparse
import numpy as np, pandas as pd

ap = argparse.ArgumentParser(); ap.add_argument('csv'); ap.add_argument('--meta'); ap.add_argument('--timeout', type=float, default=10)
a = ap.parse_args()
d = pd.read_csv(a.csv, usecols=['qid', 'method', 'rep', 'status', 'total_ms', 'transfer_ms', 'join_ms', 'init_ms'], on_bad_lines='skip')
for c in ['total_ms', 'transfer_ms', 'join_ms', 'init_ms']:
    d[c] = pd.to_numeric(d[c], errors='coerce')
d = d.dropna(subset=['total_ms'])
bad = d[d.status != 'ok'].groupby(['qid', 'method']).size().unstack().fillna(0)
d = d[d.status == 'ok']
g = d.groupby(['qid', 'method'])[['total_ms', 'transfer_ms', 'join_ms', 'init_ms']].mean().unstack()
keep = g['total_ms'][['M0', 'M4', 'M6']].notna().all(axis=1)
keep &= ~g.index.isin(bad.index[(bad.sum(axis=1) > 0)])
g = g[keep]
T, J, X, I = g['total_ms'], g['join_ms'], g['transfer_ms'], g['init_ms']
floor = I['M0']
ideal = floor + np.minimum(J['M0'], J['M4'])
H = (T['M0'] / ideal).clip(lower=1.0)
S = T['M0'] / T['M6']
n = len(g)
print(f'{a.csv}: {n} queries (all methods finished)')
print(f'time shares under M0: predicate scans/planning {floor.sum() / T["M0"].sum() * 100:.1f}%, join {J["M0"].sum() / T["M0"].sum() * 100:.1f}%')
print(f'sum of times: M0 {T["M0"].sum() / 1e3:.0f} s | ideal {ideal.sum() / 1e3:.0f} s | M6 {T["M6"].sum() / 1e3:.0f} s | M4 {T["M4"].sum() / 1e3:.0f} s')
print(f'  of which floor {floor.sum() / 1e3:.0f} s; M6 transfer {X["M6"].sum() / 1e3:.1f} s; M6 join {J["M6"].sum() / 1e3:.0f} s; ideal join {np.minimum(J["M0"], J["M4"]).sum() / 1e3:.0f} s')
gm = lambda s: float(np.exp(np.log(s).mean()))
print(f'geomean headroom {gm(H):.3f}   geomean achieved {gm(S):.3f}   geomean ideal-if-floor-free {gm(T["M0"] / np.minimum(J["M0"], J["M4"]).clip(lower=1e-3)):.1f}')
for lo, hi in [(1.0, 1.1), (1.1, 1.5), (1.5, 3), (3, 10), (10, 1e9)]:
    m = (H >= lo) & (H < hi)
    if m.sum() == 0:
        continue
    print(f'  headroom [{lo:g},{hi:g}): {m.sum():5d} queries ({m.mean() * 100:4.1f}%)  achieved geomean {gm(S[m]):.2f}  '
          f'floor share {float((floor[m] / T["M0"][m]).median()) * 100:.0f}% (median)')
big = H >= 1.1
gap = T['M0'] - ideal
captured = big & (S >= np.sqrt(H))
eaten = big & ~captured & (X['M6'] >= 0.5 * gap)
missed = big & ~captured & ~eaten
print(f'queries with headroom >= 1.1: {big.sum()} ({big.mean() * 100:.1f}%): captured {captured.sum()}, eaten by transfer cost {eaten.sum()}, missed {missed.sum()}')
cap = np.log(S[big].clip(lower=1e-9)) / np.log(H[big])
print(f'  capture (log achieved / log headroom): median {cap.median():.2f}, mean {cap.mean():.2f}')
print(f'  time: headroom gap {gap[big].sum() / 1e3:.0f} s, achieved gain {(T["M0"] - T["M6"])[big].sum() / 1e3:.0f} s, '
      f'lost in missed {(T["M6"] - ideal)[missed].sum() / 1e3:.0f} s, lost in eaten {(T["M6"] - ideal)[eaten].sum() / 1e3:.0f} s, '
      f'lost in captured {(T["M6"] - ideal)[captured].sum() / 1e3:.0f} s')
if a.meta:
    meta = pd.read_csv(a.meta).set_index('qid').reindex(g.index)
    bins = pd.cut(meta.min_sel, [0, 1e-4, 1e-3, 1e-2, 1e-1, 1.0001], labels=['<1e-4', '<1e-3', '<1e-2', '<0.1', '<=1'])
    print('by min selectivity: n, share with headroom>=1.1, geomean headroom, geomean achieved, missed, eaten')
    for k, grp in g.groupby(bins, observed=True):
        idx = grp.index
        print(f'  {k:6s} {len(idx):5d}  {big[idx].mean() * 100:5.1f}%  {gm(H[idx]):6.2f}  {gm(S[idx]):6.2f}  {missed[idx].sum():4d}  {eaten[idx].sum():4d}')
    print('by shape:')
    for k, grp in g.groupby(meta['shape']):
        idx = grp.index
        print(f'  {k:6s} {len(idx):5d}  {big[idx].mean() * 100:5.1f}%  {gm(H[idx]):6.2f}  {gm(S[idx]):6.2f}  {missed[idx].sum():4d}  {eaten[idx].sum():4d}')
out = pd.DataFrame({'headroom': H, 'achieved': S, 'floor_ms': floor, 'ideal_ms': ideal, 'm0_ms': T['M0'], 'm6_ms': T['M6'],
                    'm6_transfer_ms': X['M6'], 'm6_join_ms': J['M6'], 'm0_join_ms': J['M0'], 'm4_join_ms': J['M4'],
                    'cls': np.select([~big, captured, eaten, missed], ['none', 'captured', 'eaten', 'missed'], default='none')})
out.to_csv(a.csv.replace('.csv', '.diag.csv'))

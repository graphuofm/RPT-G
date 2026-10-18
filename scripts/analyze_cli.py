#!/usr/bin/env python
"""Compare several CLI-driver runs (one CSV per configuration, same query file) against a baseline.

Per query: median over measured reps; timeout -> timeout*1000 ms. Speedup = baseline / config.
Reports the share below 0.8x / 0.5x and above 1.25x / 2x next to the same-threshold noise floor
(baseline rep0 vs rep1), geomean, percentiles, totals, and breakdowns by baseline time.
"""
import argparse
import numpy as np
import pandas as pd


def load(path, timeout, name=None):
    d = pd.read_csv(path, dtype={'count': str})
    if name is not None and 'method' in d.columns and name in set(d.method):
        d = d[d.method == name]   # one CSV holding several interleaved configurations
    d.loc[d.status != 'ok', 'total_ms'] = timeout * 1000
    ok = d[d.status == 'ok']
    med = d.groupby('qid').total_ms.median()
    tmo = d.groupby('qid').status.apply(lambda s: (s != 'ok').any())
    cnt = ok.groupby('qid')['count'].first()
    reps = ok.pivot_table(index='qid', columns='rep', values='total_ms')
    return med, tmo, cnt, reps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csvs', nargs='+', help='name=path ... (first one is the baseline)')
    ap.add_argument('--timeout', type=float, default=10)
    ap.add_argument('--meta', default=None)
    a = ap.parse_args()
    runs = {}
    for spec in a.csvs:
        name, path = spec.split('=', 1)
        runs[name] = load(path, a.timeout, name)
    base = a.csvs[0].split('=')[0]
    bmed, btmo, bcnt, breps = runs[base]
    idx = bmed.index
    for name, (med, tmo, cnt, reps) in runs.items():
        idx = idx.intersection(med.index)
    keep = idx[~btmo[idx]]
    nz = (breps[0] / breps[1]).dropna()
    print(f'baseline {base}: {len(keep)} queries evaluated ({int(btmo[idx].sum())} baseline timeouts excluded of {len(idx)} common)')
    print(f'noise floor ({base} rep0/rep1): <0.8 {np.mean(nz<0.8)*100:.1f}%  <0.5 {np.mean(nz<0.5)*100:.1f}%  >1.25 {np.mean(nz>1.25)*100:.1f}%  >2 {np.mean(nz>2)*100:.1f}%')
    print(f'{"config":16s} {"<0.8":>6s} {"<0.5":>6s} {">1.25":>6s} {">2":>6s} {"geomean":>8s} {"P5":>6s} {"P50":>6s} {"P95":>6s} {"total s":>8s} {"tmo fixed/new":>14s} {"count mismatch":>15s}')
    print(f'{base:16s} {"":>52s} {bmed[keep].sum()/1000:8.0f}')
    for name, (med, tmo, cnt, reps) in runs.items():
        if name == base:
            continue
        sp = bmed[keep] / med[keep]
        both = keep[~tmo[keep]]
        mism = int((bcnt.reindex(both) != cnt.reindex(both)).sum())
        print(f'{name:16s} {np.mean(sp<0.8)*100:5.1f}% {np.mean(sp<0.5)*100:5.1f}% {np.mean(sp>1.25)*100:5.1f}% {np.mean(sp>2)*100:5.1f}% {np.exp(np.log(sp).mean()):8.3f} {sp.quantile(.05):6.2f} {sp.quantile(.5):6.2f} {sp.quantile(.95):6.2f} {med[keep].sum()/1000:8.0f} {int((btmo[idx] & ~tmo[idx]).sum()):>6d}/{int((~btmo[idx] & tmo[idx]).sum()):<7d} {mism:>15d}')
    print('by baseline time (geomean, share <0.8x):')
    for lo, hi in [(0, 20), (20, 100), (100, 1000), (1000, 1e9)]:
        g = keep[(bmed[keep] >= lo) & (bmed[keep] < hi)]
        if len(g) == 0:
            continue
        cells = []
        for name, (med, tmo, cnt, reps) in runs.items():
            if name == base:
                continue
            sp = bmed[g] / med[g]
            cells.append(f'{name}: {np.exp(np.log(sp).mean()):.2f} ({np.mean(sp<0.8)*100:.0f}%)')
        print(f'  {lo:>5}-{hi if hi < 1e9 else "inf":<6} ms n={len(g):4d}  ' + '   '.join(cells))
    if a.meta:
        meta = pd.read_csv(a.meta).set_index('qid')
        for col in ['has_pd']:
            for key, g in meta.loc[keep].groupby(col):
                cells = []
                for name, (med, tmo, cnt, reps) in runs.items():
                    if name == base:
                        continue
                    sp = bmed[g.index] / med[g.index]
                    cells.append(f'{name}: {np.exp(np.log(sp).mean()):.2f} ({np.mean(sp<0.8)*100:.0f}%)')
                print(f'  {col}={key} n={len(g):4d}  ' + '   '.join(cells))


if __name__ == '__main__':
    main()

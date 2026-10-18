#!/usr/bin/env python
"""Regression / speedup analysis for one workload.

Input: prototype CSV (M0/M3/M4/M6, several reps per query) and optionally the DuckDB CSV (M1).
Per query and method: mean time over measured reps; timeout -> time = timeout.
Speedup of method X on query q = t_base(q) / t_X(q). Regression = speedup < 0.9 (RPT+ convention).
Outputs a text report and a percentile plot.
"""
import argparse, sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

COLORS = {'M0': '#7f7f7f', 'M1': '#7f7f7f', 'M2': '#9467bd', 'M3': '#d62728', 'M4': '#2ca02c', 'M6': '#1f77b4'}


AGG = 'mean'


def load(path, timeout):
    df = pd.read_csv(path, usecols=lambda c: c != 'ops', on_bad_lines='skip', dtype={'count': str})
    for c in ['total_ms', 'transfer_ms', 'join_ms']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['total_ms'])   # truncated rows from shards still being written
    # a "timeout" far beyond the deadline means the process was stalled (swap / oversubscription),
    # not that the query was slow: drop such rows so they are re-run rather than counted
    anom = (df.status != 'ok') & (df.total_ms > 1.5 * timeout * 1000)
    if anom.any():
        print(f'dropping {int(anom.sum())} stalled rows (timeout status with time > 1.5x deadline)')
        df = df[~anom]
    df.loc[df.status != 'ok', 'total_ms'] = timeout * 1000
    agg = df.groupby(['qid', 'method']).agg(ms=('total_ms', AGG), timeout=('status', lambda s: (s != 'ok').any())).reset_index()
    cnt = df[df.status == 'ok'].groupby(['qid', 'method'])['count'].first().rename('count').reset_index()
    return agg.merge(cnt, on=['qid', 'method'], how='left')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv')
    ap.add_argument('--duckdb', default=None)
    ap.add_argument('--meta', default=None)
    ap.add_argument('--base', default='M0')
    ap.add_argument('--timeout', type=float, default=10)
    ap.add_argument('--plot', default=None)
    ap.add_argument('--min-ms', type=float, default=0.0, help='drop queries whose baseline is faster than this')
    ap.add_argument('--agg', default='mean', choices=['mean', 'min', 'median'], help='how to combine reps per query')
    a = ap.parse_args()
    global AGG
    AGG = a.agg

    agg = load(a.csv, a.timeout)
    if a.duckdb:
        d = pd.read_csv(a.duckdb, dtype={'count': str})
        d.loc[d.status != 'ok', 'total_ms'] = a.timeout * 1000
        dc = d[d.status == 'ok'].groupby(['qid', 'method'])['count'].first().rename('count').reset_index()
        d = d.groupby(['qid', 'method']).agg(ms=('total_ms', AGG), timeout=('status', lambda s: (s != 'ok').any())).reset_index()
        d = d.merge(dc, on=['qid', 'method'], how='left')
        agg = pd.concat([agg, d], ignore_index=True)
    wide = agg.pivot(index='qid', columns='method', values='ms')
    tmo = agg.pivot(index='qid', columns='method', values='timeout').fillna(False).astype(bool)
    methods = [m for m in ['M1', 'M3', 'M4', 'M6'] if m in wide.columns and m != a.base]
    print(f'queries: {len(wide)}   baseline: {a.base}   timeouts per method:', {m: int(tmo[m].sum()) for m in tmo.columns})

    # count consistency check between methods (only where both finished)
    cnt = agg.pivot(index='qid', columns='method', values='count')
    for m in methods:
        both = ~tmo[a.base] & ~tmo[m] & cnt[a.base].notna() & cnt[m].notna()
        bad = (cnt.loc[both, a.base] != cnt.loc[both, m]).sum()
        if bad:
            print(f'!! {m}: {bad} queries with a result count different from {a.base}')

    # exclude queries where the baseline timed out (RPT+ protocol) and optionally trivially fast ones
    keep = ~tmo[a.base] & (wide[a.base] >= a.min_ms) & wide[[a.base] + methods].notna().all(axis=1)
    missing = int((~wide[[a.base] + methods].notna().all(axis=1)).sum())
    if missing:
        print(f'{missing} queries lack rows for some method (stalled/partial) and are excluded')
    w = wide[keep]
    print(f'evaluated: {keep.sum()} queries (baseline timeouts excluded: {int(tmo[a.base].sum())}, below min-ms: {int((wide[a.base] < a.min_ms).sum())})')
    print()
    hdr = f'{"method":8s} {"regr<0.9":>9s} {"<0.5":>6s} {"<0.1":>6s} {"geomean":>8s} {"P5":>7s} {"P50":>7s} {"P95":>7s} {"max":>8s} {"min":>8s} {"tmo":>4s}'
    print(hdr)
    for m in methods:
        sp = (w[a.base] / w[m]).values
        print(f'{m:8s} {np.mean(sp < 0.9)*100:8.1f}% {np.mean(sp < 0.5)*100:5.1f}% {np.mean(sp < 0.1)*100:5.1f}% '
              f'{np.exp(np.mean(np.log(sp))):8.3f} {np.percentile(sp, 5):7.3f} {np.percentile(sp, 50):7.3f} {np.percentile(sp, 95):7.3f} '
              f'{sp.max():8.1f} {sp.min():8.4f} {int(tmo.loc[keep, m].sum()):4d}')

    if a.meta:
        meta = pd.read_csv(a.meta).set_index('qid')
        w2 = w.join(meta)
        print('\nregression rate by shape / k / min predicate selectivity bucket:')
        w2['selb'] = pd.cut(w2['min_sel'], [0, 1e-4, 1e-3, 1e-2, 1e-1, 1.0001], labels=['<1e-4', '<1e-3', '<1e-2', '<0.1', '<=1'])
        for col in ['shape', 'k', 'selb']:
            rows = []
            for key, grp in w2.groupby(col, observed=True):
                r = {col: key, 'n': len(grp)}
                for m in methods:
                    sp = grp[a.base] / grp[m]
                    r[m] = f'{np.mean(sp < 0.9)*100:5.1f}%'
                rows.append(r)
            print(pd.DataFrame(rows).to_string(index=False))
            print()

    if a.plot:
        fig, ax = plt.subplots(figsize=(6, 3.5))
        for m in methods:
            sp = np.sort((w[a.base] / w[m]).values)
            ax.plot(np.linspace(0, 100, len(sp)), sp, label=m, color=COLORS.get(m))
        ax.axhline(1, color='red', ls='--', lw=0.8)
        ax.set_yscale('log'); ax.set_xlabel('query percentile'); ax.set_ylabel(f'speedup over {a.base}')
        ax.legend(); ax.grid(alpha=0.3)
        fig.tight_layout(); fig.savefig(a.plot, dpi=150)
        print('plot ->', a.plot)


if __name__ == '__main__':
    main()

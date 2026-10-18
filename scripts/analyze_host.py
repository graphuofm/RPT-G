#!/usr/bin/env python
"""Regression / speedup analysis for one host run (Kùzu, LadybugDB): CSV with columns
qid,method,order,rep,status,total_ms,count and several configurations interleaved rep-major.
Per query and configuration: median over the recorded reps (the host runners never write warm-up
reps; rep 0 is measured). A configuration that failed in any rep (timeout, error such as a full buffer
pool) counts as the timeout for that query; the runners stop running a configuration after its first
failure, often in the warm-up, which is then recorded as rep 0 only. Queries whose baseline failed are
excluded; queries missing a configuration entirely (worker crash) are reported and excluded. Speedup = baseline / config. Baseline = --base or the
configuration whose name ends in "NO" (no mask, no transfer).
usage: analyze_host.py RUN.csv [--base LNO] [--timeout 10] [--qids OTHER.csv] [--meta META.csv]"""
import argparse, sys
import numpy as np, pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument('csv'); ap.add_argument('--base', default=None)
ap.add_argument('--timeout', type=float, default=10)
ap.add_argument('--qids', default=None, help='restrict to the qids present in this CSV')
ap.add_argument('--meta', default=None)
a = ap.parse_args()
tmo = a.timeout * 1000
d = pd.read_csv(a.csv)
d = d[~d.method.isin(['CRASH'])]
if a.qids:
    d = d[d.qid.isin(set(pd.read_csv(a.qids).qid))]
d['ms'] = np.minimum(np.where(d.status == 'ok', d.total_ms, tmo), tmo)
g = d.groupby(['qid', 'method'])
fail = g.status.apply(lambda s: (s != 'ok').any()).unstack().fillna(False).astype(bool)
piv = g.ms.median().unstack().where(~fail, tmo)
nall = len(piv); piv = piv.dropna()
m = d
base = a.base or next(c for c in piv.columns if c.endswith('NO'))
cnt = d[d.status == 'ok'].groupby(['qid', 'method'])['count'].first().unstack()
mism = {c: int(((cnt[c] != cnt[base]) & cnt[c].notna() & cnt[base].notna()).sum()) for c in cnt.columns if c != base}
print(f"{a.csv}: {len(piv)} queries with all configs ({nall - len(piv)} missing a config: crash); status counts:")
print(d.groupby(['method', 'status']).size().unstack(fill_value=0).to_string())
print("count mismatches vs", base, ":", mism)
ok = piv[piv[base] < tmo]
print(f"baseline {base}: {len(ok)} evaluated ({(piv[base] >= tmo).sum()} baseline timeouts excluded)")
r = m[m.method == base].pivot_table(index='qid', columns='rep', values='ms')
if r.shape[1] >= 2:
    f = (r.iloc[:, 0] / r.iloc[:, 1])[r.iloc[:, 1] < tmo]
    print(f"noise floor ({base} rep vs rep): <0.8 {(f < 0.8).mean() * 100:.1f}%  <0.5 {(f < 0.5).mean() * 100:.1f}%  "
          f">1.25 {(f > 1.25).mean() * 100:.1f}%  >2 {(f > 2).mean() * 100:.1f}%")
print(f"{'config':8s} {'<0.8':>6s} {'<0.5':>6s} {'>1.25':>6s} {'>2':>6s} {'geomean':>8s} {'P5':>6s} {'P50':>6s} {'P95':>6s} {'total s':>8s} {'tmo':>4s} {'fixed/new':>9s}")
for c in piv.columns:
    s = ok[base] / ok[c]
    print(f"{c:8s} {(s < 0.8).mean() * 100:5.1f}% {(s < 0.5).mean() * 100:5.1f}% {(s > 1.25).mean() * 100:5.1f}% "
          f"{(s > 2).mean() * 100:5.1f}% {np.exp(np.log(s).mean()):8.3f} {s.quantile(.05):6.2f} {s.quantile(.5):6.2f} "
          f"{s.quantile(.95):6.2f} {ok[c].sum() / 1000:8.1f} {(piv[c] >= tmo).sum():4d} "
          f"{((piv[base] >= tmo) & (piv[c] < tmo)).sum():4d}/{((piv[base] < tmo) & (piv[c] >= tmo)).sum():<4d}")
print("by baseline time (geomean, share < 0.8x):")
for lo, hi in [(0, 20), (20, 100), (100, 1000), (1000, 1e9)]:
    b = ok[(ok[base] >= lo) & (ok[base] < hi)]
    if len(b) == 0:
        continue
    print(f"  {lo:>5.0f}-{hi if hi < 1e9 else 'inf':>5} ms n={len(b):4d}  " +
          "  ".join(f"{c}: {np.exp(np.log(b[base] / b[c]).mean()):.2f} ({((b[base] / b[c]) < 0.8).mean() * 100:.0f}%)"
                    for c in piv.columns if c != base))
if a.meta:
    meta = pd.read_csv(a.meta); meta = meta.set_index('id' if 'id' in meta.columns else 'qid')
    for col in [c for c in ('has_pd', 'shape', 'npred') if c in meta.columns]:
        for v, g in ok.groupby(meta.reindex(ok.index)[col]):
            print(f"  {col}={v} n={len(g):4d}  " + "  ".join(
                f"{c}: {np.exp(np.log(g[base] / g[c]).mean()):.2f} ({((g[base] / g[c]) < 0.8).mean() * 100:.0f}%)"
                for c in piv.columns if c != base))
main = [c for c in piv.columns if c.endswith('R2')] or [c for c in piv.columns if c != base]
w = (ok[base] / ok[main[0]]).sort_values().head(8)
print(f"worst {main[0]} queries (speedup):")
print(pd.concat([ok.loc[w.index].round(1), w.rename('speedup').round(2)], axis=1).to_string())

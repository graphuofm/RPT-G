"""Every number and per-query series the paper uses, recomputed from the raw run CSVs in results/.

Run `python data.py` from this directory: it prints a report and writes numbers.json (summary
statistics quoted in main.tex) and series.pkl (per-query speedups and robustness factors for the plots).

Conventions (the same as scripts/analyze.py and scripts/analyze_host.py):
- prototype runs: mean over the measured reps; a regression is a speedup below 0.9x (RPT+'s threshold);
- host runs: median over the reps (host timings have outliers); a regression is a speedup below 0.8x,
  because a quarter of the host queries move by +-10% between reps;
- a timeout or error counts as the 10 s timeout; queries whose baseline timed out are excluded;
- noise floor = share of queries whose baseline run differs from itself (rep 0 vs rep 1) by the same
  threshold.
"""
import json, os, pickle
import numpy as np
import pandas as pd

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'results')
TMO = 10_000.0


def gm(s):
    return float(np.exp(np.mean(np.log(np.asarray(s, dtype=float)))))


def summary(sp, thr):
    sp = np.asarray(sp, dtype=float)
    return {'n': int(len(sp)), 'regr': float(np.mean(sp < thr) * 100), 'lt05': float(np.mean(sp < 0.5) * 100),
            'gt125': float(np.mean(sp > 1.25) * 100), 'gt2': float(np.mean(sp > 2) * 100),
            'geomean': gm(sp), 'p5': float(np.percentile(sp, 5)), 'p50': float(np.percentile(sp, 50)),
            'p95': float(np.percentile(sp, 95))}


# ---------------------------------------------------------------- prototype (M0/M3/M4/M6)
def load_proto(path):
    d = pd.read_csv(path, usecols=['qid', 'method', 'order', 'rep', 'status', 'total_ms', 'init_ms'],
                    on_bad_lines='skip')
    d['total_ms'] = pd.to_numeric(d.total_ms, errors='coerce')
    d = d.dropna(subset=['total_ms'])
    d = d[~((d.status != 'ok') & (d.total_ms > 1.5 * TMO))]      # stalled rows (see analyze.py)
    d.loc[d.status != 'ok', 'total_ms'] = TMO
    return d


def proto(path, methods=('M3', 'M4', 'M6'), base='M0'):
    d = load_proto(path)
    g = d.groupby(['qid', 'method'])
    ms = g.total_ms.mean().unstack()
    tmo = g.status.apply(lambda s: (s != 'ok').any()).unstack().fillna(False).astype(bool)
    cols = [base] + list(methods)
    keep = ~tmo[base] & ms[cols].notna().all(axis=1)
    w = ms[keep]
    r = d[d.method == base].pivot_table(index='qid', columns='rep', values='total_ms')
    nz = (r[0] / r[1]).reindex(w.index).dropna()
    out = {'n_queries': int(len(ms)), 'baseline_timeouts': int(tmo[base].sum()),
           'noise': float(np.mean(nz < 0.9) * 100), 'noise_lt05': float(np.mean(nz < 0.5) * 100),
           'total_s': {c: float(w[c].sum() / 1000) for c in cols}}
    sp = {m: (w[base] / w[m]).values for m in methods}
    for m in methods:
        out[m] = summary(sp[m], 0.9)
    return out, sp


# ---------------------------------------------------------------- host runs (Kuzu, LadybugDB)
def host(path, base, configs, qids=None, tmo=None):
    TMO = tmo or globals()['TMO']
    d = pd.read_csv(path)
    d = d[d.method != 'CRASH']
    if qids is not None:
        d = d[d.qid.isin(qids)]
    d['ms'] = np.minimum(np.where(d.status == 'ok', d.total_ms, TMO), TMO)
    g = d.groupby(['qid', 'method'])
    fail = g.status.apply(lambda s: (s != 'ok').any()).unstack().fillna(False).astype(bool)
    piv = g.ms.median().unstack().where(~fail, TMO).dropna()
    ok = piv[piv[base] < TMO]
    r = d[d.method == base].pivot_table(index='qid', columns='rep', values='ms')
    f = (r.iloc[:, 0] / r.iloc[:, 1])[r.iloc[:, 1] < TMO]
    out = {'n': int(len(ok)), 'baseline_timeouts': int((piv[base] >= TMO).sum()),
           'noise': float(np.mean(f < 0.8) * 100), 'noise_lt05': float(np.mean(f < 0.5) * 100),
           'total_s': {c: float(ok[c].sum() / 1000) for c in [base] + list(configs)}}
    sp = {}
    for c in configs:
        s = ok[base] / ok[c]
        sp[c] = s.values
        out[c] = summary(s, 0.8)
        out[c]['timeouts_fixed'] = int(((piv[base] >= TMO) & (piv[c] < TMO)).sum())
        out[c]['timeouts_new'] = int(((piv[base] < TMO) & (piv[c] >= TMO)).sum())
        buckets = {}
        for lo, hi in [(0, 20), (20, 100), (100, 1000), (1000, 1e12)]:
            b = ok[(ok[base] >= lo) & (ok[base] < hi)]
            bs = b[base] / b[c]
            buckets[f'{lo}-{hi if hi < 1e12 else "inf"}'] = {'n': int(len(b)), 'geomean': gm(bs),
                                                              'regr': float(np.mean(bs < 0.8) * 100)}
        out[c]['by_time'] = buckets
    return out, sp, ok


def by_selectivity(ok, base, configs, meta):
    m = pd.read_csv(meta).set_index('qid').reindex(ok.index)
    bins = pd.cut(m.min_sel, [0, 1e-4, 1e-3, 1e-2, 1e-1, 1.0001], labels=['<1e-4', '<1e-3', '<1e-2', '<0.1', '<=1'])
    res = {}
    for key, grp in ok.groupby(bins, observed=True):
        res[str(key)] = {'n': int(len(grp))}
        for c in configs:
            s = grp[base] / grp[c]
            res[str(key)][c] = {'geomean': gm(s), 'regr': float(np.mean(s < 0.8) * 100)}
    hub = {}
    for key, grp in ok.groupby(m.has_pd):
        hub[int(key)] = {'n': int(len(grp))}
        for c in configs:
            s = grp[base] / grp[c]
            hub[int(key)][c] = {'geomean': gm(s), 'regr': float(np.mean(s < 0.8) * 100)}
    return res, hub


# ---------------------------------------------------------------- DuckDB CLI runs (one CSV, 4 configs)
def duck(path, base, configs):
    d = pd.read_csv(path, dtype={'count': str})
    d.loc[d.status != 'ok', 'total_ms'] = TMO
    med = d.groupby(['qid', 'method']).total_ms.median().unstack()
    tmo = d.groupby(['qid', 'method']).status.apply(lambda s: (s != 'ok').any()).unstack()
    keep = med.index[~tmo[base].astype(bool) & med[[base] + list(configs)].notna().all(axis=1)]
    r = d[d.method == base].pivot_table(index='qid', columns='rep', values='total_ms')
    nz = (r[0] / r[1]).dropna()
    out = {'n': int(len(keep)), 'baseline_timeouts': int(tmo[base].astype(bool).sum()),
           'noise': float(np.mean(nz < 0.8) * 100), 'noise_lt05': float(np.mean(nz < 0.5) * 100),
           'total_s': {c: float(med.loc[keep, c].sum() / 1000) for c in [base] + list(configs)}}
    sp = {}
    for c in configs:
        s = med.loc[keep, base] / med.loc[keep, c]
        sp[c] = s.values
        out[c] = summary(s, 0.8)
        buckets = {}
        for lo, hi in [(0, 20), (20, 100), (100, 1000), (1000, 1e12)]:
            g = keep[(med.loc[keep, base] >= lo) & (med.loc[keep, base] < hi)]
            bs = med.loc[g, base] / med.loc[g, c]
            buckets[f'{lo}-{hi if hi < 1e12 else "inf"}'] = {'n': int(len(g)), 'geomean': gm(bs),
                                                              'regr': float(np.mean(bs < 0.8) * 100)}
        out[c]['by_time'] = buckets
    return out, sp


def duck_judgment2():
    """RPT+ as-is vs vanilla DuckDB 1.3.0 on the full DBLP Q-GEN (two separate CSVs, mean of reps)."""
    runs = {}
    for name, f in [('vanilla', 'dblp_qgen_duckdb130.csv'), ('rptplus', 'dblp_qgen_rptplus.csv')]:
        d = pd.read_csv(os.path.join(R, f), dtype={'count': str})
        d.loc[d.status != 'ok', 'total_ms'] = TMO
        runs[name] = (d.groupby('qid').total_ms.mean(), d.groupby('qid').status.apply(lambda s: (s != 'ok').any()),
                      d.pivot_table(index='qid', columns='rep', values='total_ms'))
    vb, vt, vr = runs['vanilla']
    rb, rt, _ = runs['rptplus']
    idx = vb.index.intersection(rb.index)
    idx = idx[~vt[idx].astype(bool)]
    sp = vb[idx] / rb[idx]
    nz = (vr.iloc[:, 0] / vr.iloc[:, 1]).dropna()
    out = summary(sp, 0.9)
    out['noise'] = float(np.mean(nz < 0.9) * 100)
    out['ge100ms_regr'] = float(np.mean(sp[vb[idx] >= 100] < 0.9) * 100)
    return out, sp.values


# ---------------------------------------------------------------- join-order robustness
def robustness(path):
    d = load_proto(path)
    d['net_ms'] = np.where(d.status == 'ok', d.total_ms - d.init_ms, TMO)
    m = d.groupby(['qid', 'method', 'order'])[['total_ms', 'net_ms']].mean().reset_index()
    out, fac = {}, {}
    for meth, g in m.groupby('method'):
        a = g.groupby('qid').total_ms.agg(['max', 'min', 'median'])
        f = (a['max'] / a['min']).values
        fn = (g.groupby('qid').net_ms.max() / g.groupby('qid').net_ms.min()).values
        fac[meth] = f
        out[meth] = {'geomean': gm(f), 'median': float(np.median(f)), 'p90': float(np.percentile(f, 90)),
                     'max': float(f.max()), 'le2': int(np.sum(f <= 2)), 'le3': int(np.sum(f <= 3)),
                     'worst_sum_s': float(a['max'].sum() / 1000), 'median_sum_s': float(a['median'].sum() / 1000),
                     'best_sum_s': float(a['min'].sum() / 1000), 'net_geomean': gm(fn),
                     'timeouts': int((d[(d.method == meth)].status != 'ok').sum()),
                     'worst_geomean_ms': gm(a['max'].values)}
    # per (query, order) pair speedups over M0 and worst order vs M0's best order
    p = m.pivot_table(index=['qid', 'order'], columns='method', values='total_ms')
    best0 = m[m.method == 'M0'].groupby('qid').total_ms.min()
    for meth in ('M4', 'M6'):
        s = p['M0'] / p[meth]
        out[meth]['pair_geomean'] = gm(s)
        out[meth]['pair_regr'] = float(np.mean(s < 0.9) * 100)
        out[meth]['pair_gt2'] = float(np.mean(s > 2) * 100)
        out[meth]['pair_gt10'] = float(np.mean(s > 10) * 100)
        worst = m[m.method == meth].groupby('qid').total_ms.max()
        out[meth]['worst_vs_best0'] = gm(worst / best0)
    return out, fac


# ---------------------------------------------------------------- sensitivity sweeps (M0 + M6, 1k subsamples)
def sweep(path):
    o, _ = proto(path, methods=('M6',))
    return {'regr': o['M6']['regr'], 'noise': o['noise'], 'geomean': o['M6']['geomean'], 'p95': o['M6']['p95']}


def main():
    N, S = {}, {}
    N['proto_dblp'], S['proto_dblp'] = proto(os.path.join(R, 'dblp_qgen_v8.csv'))   # final prototype (v8)
    N['proto_lj'], S['proto_lj'] = proto(os.path.join(R, 'lj_qgen_v8.csv'))   # v8, 3,893 queries whose baseline finished in v5
    N['j2_duckdb'], S['j2_duckdb'] = duck_judgment2()
    N['robust_dblp'], S['robust_dblp'] = robustness(os.path.join(R, 'dblp_robust100d.csv'))
    N['robust_lj'], S['robust_lj'] = robustness(os.path.join(R, 'lj_robust100.csv'))

    N['kuzu_dblp'], S['kuzu_dblp'], ok = host(os.path.join(R, 'kuzu_dblp_3way_e.csv'), 'KNO', ['KSM', 'KR2'])
    N['kuzu_dblp_sel'], N['kuzu_dblp_hub'] = by_selectivity(ok, 'KNO', ['KSM', 'KR2'],
                                                            os.path.join(R, '..', 'queries', 'qgen_dblp.txt.meta.csv'))
    N['kuzu_lj'], S['kuzu_lj'], ok = host(os.path.join(R, 'kuzu_lj_3way_e.csv'), 'KNO', ['KSM', 'KR2'])
    N['kuzu_lj_sel'], N['kuzu_lj_hub'] = by_selectivity(ok, 'KNO', ['KSM', 'KR2'],
                                                        os.path.join(R, '..', 'queries', 'qgen_lj.txt.meta.csv'))
    N['kuzu_dblp_ksx'], S['kuzu_dblp_ksx'], _ = host(os.path.join(R, 'kuzu_dblp_ksx.csv'), 'KNO', ['KSX'])
    # progression of the Kuzu integration on the same workload: stage B run (KR1 = no budget,
    # KR2 = budget on host estimates), stage D run (run-time work model + plan-time pre-screen)
    st = {}
    o, _, _ = host(os.path.join(R, 'kuzu_dblp_4way.csv'), 'KNO', ['KR1', 'KR2'])
    st['A_nobudget'], st['B_hostest'] = o['KR1'], o['KR2']
    o, _, _ = host(os.path.join(R, 'kuzu_dblp_3way_d.csv'), 'KNO', ['KR2'])
    st['D_prescreen'] = o['KR2']
    st['E_final'] = N['kuzu_dblp']['KR2']
    N['kuzu_dblp_stages'] = st
    # LadybugDB: the four queries LadybugDB answers wrongly in every configuration are excluded
    bad = {293, 790, 4016, 4511}
    lq = set(pd.read_csv(os.path.join(R, 'ladybug_dblp300.csv')).qid) - bad
    N['ladybug'], S['ladybug'], _ = host(os.path.join(R, 'ladybug_dblp300.csv'), 'LNO', ['LSM', 'LR2'], qids=lq)
    fF = os.path.join(R, 'ladybug_dblp300_f.csv')
    if os.path.exists(fF):
        N['ladybug_f'], S['ladybug_f'], _ = host(fF, 'LNO', ['LSM', 'LR2E', 'LR2'], qids=lq)
    N['duckdb'], S['duckdb'] = duck(os.path.join(R, 'duckdb300_4way.csv'), 'fork', ['rptplus', 'rptg', 'vanilla'])
    N['duckdb_vs_vanilla'], _ = duck(os.path.join(R, 'duckdb300_4way.csv'), 'vanilla', ['rptplus', 'rptg', 'fork'])

    sw = {}
    for g, pre in [('dblp', 'sweep_beta_'), ('lj', 'sweep_beta_lj_')]:
        sw[g] = {}
        for b in ['0', '0.25', '0.5', '1', '2', '4']:
            sw[g][b] = sweep(os.path.join(R, f'{pre}{b}.csv'))
    sw['lj_other'] = {k: sweep(os.path.join(R, f)) for k, f in
                      [('gamma500', 'sweep_lj_gamma500.csv'), ('gamma10k', 'sweep_lj_gamma10k.csv'),
                       ('tausel0.2', 'sweep_lj_tausel02.csv'), ('tausel0.5', 'sweep_lj_tausel05.csv')]}
    N['sweeps'] = sw

    # M6-acc ablation (exact degree accumulators vs a 1,000-member sample), paired per query
    ab = {}
    for g in ['dblp', 'lj']:
        o_e, s_e = proto(os.path.join(R, f'abl_{g}1k_exact.csv'), methods=('M6',))
        o_a, s_a = proto(os.path.join(R, f'abl_{g}1k_acc.csv'), methods=('M6',))
        ab[g] = {'exact': o_e['M6'], 'sampled': o_a['M6']}
    N['ablation_acc'] = ab

    # Neo4j 5.26 reference against Kuzu (queries both finish)
    n4 = pd.read_csv(os.path.join(R, 'neo4j_dblp_qgen.csv'))
    k = pd.read_csv(os.path.join(R, 'kuzu_dblp_3way_e.csv'))
    k = k[k.status == 'ok']
    neo = n4[n4.status == 'ok'].groupby('qid').total_ms.median()
    kn = k[k.method == 'KNO'].groupby('qid').total_ms.median()
    kr = k[k.method == 'KR2'].groupby('qid').total_ms.median()
    c = neo.index.intersection(kn.index).intersection(kr.index)
    N['neo4j'] = {'queries': int(n4.qid.nunique()), 'timeout_queries': int(n4[n4.status != 'ok'].qid.nunique()),
                  'common': int(len(c)), 'kno_over_neo': gm(kn[c] / neo[c]), 'kr2_over_neo': gm(kr[c] / neo[c])}

    # ---- phase 2 (2026-09-29): headroom vs optimizer quality, cyclic patterns, in-host robustness
    oq = {}
    for g in ['dblp', 'lj', 'youtube']:
        for o in ['exact', 'est']:
            f = os.path.join(R, f'order_{o}_{g}1k.csv')
            if not os.path.exists(f):
                continue
            d = load_proto(f)
            tm = d.groupby(['qid', 'method']).total_ms.mean().unstack()
            tmo = d.groupby(['qid', 'method']).status.apply(lambda s: (s != 'ok').any()).unstack().astype(bool)
            keep = ~tmo['M0'] & tm[['M0', 'M4', 'M6']].notna().all(axis=1)
            dg = pd.read_csv(f.replace('.csv', '.diag.csv'), index_col=0) if os.path.exists(f.replace('.csv', '.diag.csv')) else None
            o_, sp = proto(f, methods=('M4', 'M6'))
            # totals over every query of the sample, a timeout counted as 10 s, so that both orders are
            # compared on the same queries
            oq[f'{g}_{o}'] = {'M6': o_['M6'], 'M4': o_['M4'], 'noise': o_['noise'],
                              'total_s': {m: float(tm[m].sum() / 1e3) for m in ['M0', 'M4', 'M6']},
                              'timeouts': {m: int(tmo[m].sum()) for m in ['M0', 'M4', 'M6']},
                              'ideal_s': float(dg.ideal_ms.sum() / 1e3) if dg is not None else None,
                              'headroom_geo': gm(dg.headroom) if dg is not None else None,
                              'headroom_ge11': float((dg.headroom >= 1.1).mean() * 100) if dg is not None else None}
            S[f'order_{g}_{o}'] = sp
    N['order_quality'] = oq
    cy = {}
    for f in ['cyc_dblp', 'cyc_dblp_est', 'cyc_lj', 'cyc_lj_est']:
        if os.path.exists(os.path.join(R, f + '.csv')):
            o_, sp = proto(os.path.join(R, f + '.csv'), methods=('M3', 'M4', 'M5', 'M6'))
            cy[f] = o_
            S[f] = sp
    N['cyclic'] = cy
    # final prototype configuration (v18c, 2026-10-05): counting join (M7 ski rental, M8 upfront), column indexes,
    # per-method warm runs; operation counts per phase (adjacency entries) over the queries every method finished
    fin = {}
    for g in ['dblp', 'lj']:
        # protocol of record: main (M0,M6,M7,M8) and base (M0,M3,M4) process groups; the single-process file
        # (all six methods) is the fallback, valid for operation counts only
        # main group: the configuration of record (final25) when present, else the v18c protocol run
        fm, fb, f1 = [os.path.join(R, f'final18c_{g}1k{suf}.csv') for suf in ('_main', '_base', '')]
        have = lambda f: os.path.exists(f) and os.path.getsize(f) > 0
        fb_ops = fb                                            # operation counts: the base group under the same binary
        for v in ('25', '26'):                                 # the latest configuration of record that has run
            fm_v, fb_v = [os.path.join(R, f'final{v}_{g}1k_{grp}.csv') for grp in ('main', 'base')]
            if have(fm_v):
                fm = fm_v
            if have(fb_v):                                     # (same work accounting); timings of M3/M4 stay with the
                fb_ops = fb_v                                  # v18c base group, run on a quiet machine
        if not (have(fm) or have(f1)):
            continue
        meths = ('M3', 'M4', 'M6', 'M7', 'M8')
        if have(fm):
            o_, sp = proto(fm, methods=('M6', 'M7', 'M8'))
            if have(fb):
                ob, spb = proto(fb, methods=('M3', 'M4'))
                for m in ('M3', 'M4'):
                    o_[m] = ob[m]; sp[m] = spb[m]
                o_['base_noise'] = ob['noise']; o_['total_s'].update({m: ob['total_s'][m] for m in ('M0b', ) if m in ob['total_s']})
                o_['total_s_base'] = ob['total_s']
            f = fm
        else:
            o_, sp = proto(f1, methods=meths)
            f = f1
        d = pd.read_csv(f)                                    # every column (operation counts) of the v18 CSV
        gq = d.groupby(['qid', 'method'])
        tmo = gq.status.apply(lambda s_: (s_ != 'ok').any()).unstack().fillna(False).astype(bool)
        for m in meths:
            if m in tmo.columns:
                o_[m]['timeouts_fixed'] = int((tmo['M0'] & ~tmo[m]).sum())
            elif have(fb):                                    # M3/M4 from the base-group file
                db = pd.read_csv(fb)
                tb = db.groupby(['qid', 'method']).status.apply(lambda s_: (s_ != 'ok').any()).unstack().fillna(False).astype(bool)
                o_[m]['timeouts_fixed'] = int((tb['M0'] & ~tb[m]).sum())
                o_['base_timeouts'] = int(tb['M0'].sum())
        okd = d[d.status == 'ok']
        agg = okd.groupby(['qid', 'method'])[['total_ms', 'init_ms', 'transfer_ms', 'join_ms', 'transfer_work',
                                              'join_work', 'join_out', 'count']].mean()
        if f != f1 and (have(fb_ops) or have(f1)):            # M3/M4 operation counts: the base group's file (or the
            d1 = pd.read_csv(fb_ops if have(fb_ops) else f1)  # single-process file with all six methods), restricted
            tmo1 = d1.groupby(['qid', 'method']).status.apply(lambda s_: (s_ != 'ok').any()).unstack().fillna(False).astype(bool)
            agg1 = d1[d1.status == 'ok'].groupby(['qid', 'method'])[['total_ms', 'init_ms', 'transfer_ms', 'join_ms', 'transfer_work',
                                                                    'join_work', 'join_out', 'count']].mean()
            for m in ('M3', 'M4'):                            # to the queries that every method finished
                if m in tmo1.columns:
                    tmo[m] = tmo1[m].reindex(tmo.index).fillna(True)
            agg = pd.concat([agg, agg1[agg1.index.get_level_values(1).isin(['M3', 'M4'])]]).sort_index()
        present = [m for m in meths if m in tmo.columns]
        common = [q for q in tmo.index if not tmo.loc[q, ['M0'] + present].any()]
        ops = {'queries': len(common), 'output': float(agg.xs('M0', level=1).loc[common]['count'].sum())}
        for m in ('M0',) + tuple(present):
            x = agg.xs(m, level=1).loc[common]
            ops[m] = {'pred_ms': float(x.init_ms.sum()), 'transfer_entries': float(x.transfer_work.sum()),
                      'transfer_ms': float(x.transfer_ms.sum()), 'scanned': float(x.join_work.sum()),
                      'counted': float(x.join_out.sum()), 'join_ms': float(x.join_ms.sum()), 'total_ms': float(x.total_ms.sum())}
        o_['ops'] = ops
        fin[g] = o_
        S[f'final_{g}'] = sp
    N['final'] = fin
    # more graphs and long chains under the configuration of record (v25): main group M0,M6,M7,M8 and, for the
    # graphs, the base group M0,M3,M4 in its own process group
    more = {}
    for key, fm_, fb_ in [('youtube', 'final25_youtube1k_main.csv', 'final25_youtube1k_base.csv'),
                          ('orkut', 'final25_orkut1k_main.csv', 'final25_orkut1k_base.csv'),
                          ('pokec', 'final25_pokec1k_main.csv', 'final25_pokec1k_base.csv'),
                          ('dblp_chain', 'chain25_dblp_main.csv', None),
                          ('lj_chain', 'chain25_lj_main.csv', None)]:
        pm = os.path.join(R, fm_)
        if not (os.path.exists(pm) and os.path.getsize(pm) > 0):
            continue
        o_, _ = proto(pm, methods=('M6', 'M7', 'M8'))
        d = pd.read_csv(pm)
        tm = d.groupby(['qid', 'method']).status.apply(lambda s_: (s_ != 'ok').any()).unstack().fillna(False).astype(bool)
        ms_ = d.assign(ms=np.minimum(np.where(d.status == 'ok', d.total_ms, TMO), TMO)).groupby(['qid', 'method']).ms.mean().unstack()
        o_['total_all_s'] = {m: float(ms_[m].sum() / 1000) for m in ('M0', 'M6', 'M7', 'M8')}   # timeouts as 10 s
        for m in ('M6', 'M7', 'M8'):
            o_[m]['timeouts_fixed'] = int((tm['M0'] & ~tm[m]).sum())
        common = [q for q in tm.index if not tm.loc[q, ['M0', 'M6', 'M7', 'M8']].any()]
        agg = d[d.status == 'ok'].groupby(['qid', 'method'])[['transfer_ms', 'join_ms', 'transfer_work', 'join_work', 'join_out', 'count']].mean()
        o_['ops'] = {'queries': len(common), 'output': float(agg.xs('M0', level=1).loc[common]['count'].sum())}
        for m in ('M0', 'M6', 'M7', 'M8'):
            x = agg.xs(m, level=1).loc[common]
            o_['ops'][m] = {'transfer_entries': float(x.transfer_work.sum()), 'transfer_ms': float(x.transfer_ms.sum()),
                            'scanned': float(x.join_work.sum()), 'counted': float(x.join_out.sum()), 'join_ms': float(x.join_ms.sum())}
        if fb_:
            pb = os.path.join(R, fb_)
            ob, _ = proto(pb, methods=('M3', 'M4'))
            for m in ('M3', 'M4'):
                o_[m] = ob[m]
            o_['base_noise'] = ob['noise']
        more[key] = o_
    N['more'] = more
    rb = {}
    for f, base in [('kuzu_dblp_robust', 'KNO'), ('pg19_dblp_robust', 'PGNO'), ('duckdb_dblp_robust', 'dk0')]:
        path = os.path.join(R, f + '.csv')
        if not os.path.exists(path):
            continue
        d = pd.read_csv(path)
        d = d[d.method != 'CRASH']
        d['ms'] = np.where(d.status == 'ok', d.total_ms, TMO).clip(max=TMO)
        g = d.groupby(['qid', 'method', 'order'])
        med = g.ms.median().where(~g.status.apply(lambda s: (s != 'ok').any()), TMO).reset_index()
        pv = med.pivot_table(index=['qid', 'order'], columns='method', values='ms').dropna()
        res = {'pairs': int(len(pv)), 'queries': int(pv.index.get_level_values(0).nunique())}
        best_base = pv[base].groupby(level=0).min()
        for c in pv.columns:
            q_ = pv[c].groupby(level=0).agg(['max', 'min', 'median'])
            res[c] = {'factor_geo': gm(q_['max'] / q_['min']), 'worst_sum_s': float(q_['max'].sum() / 1e3),
                      'median_sum_s': float(q_['median'].sum() / 1e3), 'best_sum_s': float(q_['min'].sum() / 1e3),
                      'worst_vs_base_best': gm(q_['max'] / best_base), 'timeouts': int((pv[c] >= TMO).sum())}
            if c != base:
                sp = (pv[base] / pv[c]).values
                res[c].update({'pair_geo': gm(sp), 'pair_lt08': float(np.mean(sp < 0.8) * 100),
                               'pair_gt2': float(np.mean(sp > 2) * 100), 'pair_gt10': float(np.mean(sp > 10) * 100)})
                S[f + '_' + c] = sp
        rb[f] = res
    N['host_robust'] = rb

    # LSQB-P: the rerun with INTERSECT support in the Kuzu integration replaces the first run once it exists
    LSQBP = 'kuzu_lsqbp_sf1_intersect.csv' if os.path.exists(os.path.join(R, 'kuzu_lsqbp_sf1_intersect.csv')) else 'kuzu_lsqbp_sf1.csv'
    # hosts under their own plans (phase 2): PostgreSQL 19, vanilla DuckDB 1.3, LSQB-P in Kuzu
    for key, f, base, cfgs, tmo in [('pg19', 'pg19_rptg_dblp300.csv', 'PGNO', ['PGR'], None),
                                     ('pg19_1', 'pg19_rptg_dblp300.csv', 'PG1', ['PGR1'], None),
                                     ('duckdb_v', 'duckdb_rptg_dblp300.csv', 'dk0', ['dkr'], None),
                                     ('lsqbp', LSQBP, 'KNO', ['KSM', 'KR2'], 60_000.0),
                                     ('kuzu_cyc', 'kuzu_dblp_cyc.csv', 'KNO', ['KSM', 'KR2'], None),
                                     ('pg19_cyc', 'pg19_dblp_cyc.csv', 'PGNO', ['PGR'], None),
                                     ('duckdb_cyc', 'duckdb_dblp_cyc.csv', 'dk0', ['dkr'], None)]:
        path = os.path.join(R, f)
        if os.path.exists(path) and os.path.getsize(path) > 0:   # a run in progress writes its CSV at the end
            try:
                N[key], S[key], _ = host(path, base, cfgs, tmo=tmo)
            except KeyError:
                pass

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, 'numbers.json'), 'w') as f:
        json.dump(N, f, indent=1, sort_keys=True)
    with open(os.path.join(here, 'series.pkl'), 'wb') as f:
        pickle.dump(S, f)
    print(json.dumps(N, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()

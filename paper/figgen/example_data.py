"""Numbers for the explanatory figures: the running example on DBLP (pattern v0-v1-v2-v3), the degree-weighted
survival on LiveJournal, two pulls with their running survival rate, the host-plan rows of the example, and the
per-phase time breakdown of three LiveJournal queries. Writes example.json. No new experiment: everything is
computed from the graphs and from recorded runs."""
import json, os
import numpy as np, pandas as pd

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
def load(g):
    d = os.path.join(R, 'data', 'bin', g)
    off = np.fromfile(os.path.join(d, 'out_off.bin'), dtype=np.uint64)
    nbr = np.fromfile(os.path.join(d, 'out_nbr.bin'), dtype=np.uint32)
    pu = np.fromfile(os.path.join(d, 'pu.bin'), dtype=np.float32)
    pdg = np.fromfile(os.path.join(d, 'pd.bin'), dtype=np.float32)
    return off, nbr, pu, pdg
off, nbr, pu, pdg = load('dblp')
n = len(pu); deg = np.diff(off).astype(np.int64); m = int(deg.sum())
def nbrs_of(vs):
    """concatenated adjacency of the vertex set vs (sorted ids)"""
    return np.concatenate([nbr[off[v]:off[v + 1]] for v in vs]) if len(vs) else np.array([], dtype=np.uint32)
def count_in(vs, mask):
    """per vertex in vs: number of neighbours with mask set"""
    return np.array([int(mask[nbr[off[v]:off[v + 1]]].sum()) for v in vs])
B0 = np.nonzero(pu < 1e-3)[0]; B3 = np.nonzero(pdg < 0.01)[0]
m0 = np.zeros(n, bool); m0[B0] = True
m3 = np.zeros(n, bool); m3[B3] = True
D0, D3 = int(deg[B0].sum()), int(deg[B3].sum())
B1 = np.unique(nbrs_of(B0))                       # after the push v0 -> v1
D1 = int(deg[B1].sum())
hit3 = count_in(B1, m3)                          # pull v3 -> v1: neighbours in B3 per member of B1
B1b = B1[hit3 > 0]; D1b = int(deg[B1b].sum())
ex = {'n': n, 'm': m, 'B0': len(B0), 'D0': D0, 'B3': len(B3), 'D3': D3, 'B1': len(B1), 'D1': D1,
      'B1_after_v3': len(B1b), 'D1_after_v3': D1b, 'survival_v3_to_v1': len(B1b) / len(B1),
      'survival_degsum_v3_to_v1': D1b / D1}
# the join from v0: entries scanned per level, partial matches per level (output counted at the last level)
hit1b = count_in(B0, np.isin(np.arange(n), B1b))   # v1 candidates after both transfers, reached from each v0
pm01 = int(hit1b.sum())                            # (v0, v1) partial matches with v1 in B1'
ex['join'] = {'scan_v1': D0, 'pm_v0v1_unreduced': D0, 'pm_v0v1_reduced': pm01}
# counting on the example, rooted at v1 with children v0 (c=1 on B0), v2 (degree), v3 (c=1 on B3)
c0 = count_in(B1b, m0); c3 = hit3[hit3 > 0]; dg = deg[B1b]
c1 = c0 * dg * c3
ex['count'] = {'total': int(c1.sum()), 'members_B1': len(B1b),
               'examples': [{'v': int(v), 'in_B0': int(a), 'deg': int(d), 'in_B3': int(b), 'c': int(a * d * b)}
                            for v, a, d, b in sorted(zip(B1b, c0, dg, c3), key=lambda t: -t[1] * t[2] * t[3])[:3]],
               'C': int((len(B0) + min(D0, D1b)) + (len(B3) + min(D3, D1b))),   # unconstrained leaf v2: degree lookup
               'E_scanned': int(D0 + pm01 * 0 + 0)}
# enumeration: after v1, the join scans deg(v1) for v2 and deg(v1) for v3 per partial match (output at the last level)
pm = []  # per (v0,v1) pair with v1 in B1': v2 count = deg(v1), v3 count = hit3
tot_v2 = int(sum(int(deg[v]) * int(a) for v, a in zip(B1b, c0)))         # (v0,v1,v2) partial matches
ex['count']['E_scanned'] = int(D0 + tot_v2 + int((c0 * dg).sum()))      # scans: v1 lists for v2 and v3 levels
ex['count']['output'] = int(c1.sum())
# host plan rows (bushy hash joins): E01 join V0, then join E13 (v3 side), then E12
rows01 = D0; rows01_t = pm01
rows013 = int((count_in(B0, np.isin(np.arange(n), B1)) * 0).sum())  # placeholder replaced below
r013 = 0; r013_t = 0
for u in B0:
    for v in nbr[off[u]:off[u + 1]]:
        h = int(m3[nbr[off[v]:off[v + 1]]].sum())
        r013 += h
        if h > 0: r013_t += h
ex['host_rows'] = {'E01_V0': rows01, 'E01_V0_after_transfer': rows01_t, 'E01_V0_E13_V3': r013,
                   'after_transfer': r013_t, 'E13_V3_alone': D3, 'E12_alone': m}
# two pulls with running survival in random word order (the engine's rule): (a) v3 -> v1, (b) a 30% set -> v1
rng = np.random.default_rng(7)
def pull_curve(target, src_mask, gamma=2000, tau_sel=0.35, tau_prog=0.6):
    words = np.unique(target // 64); rng.shuffle(words)
    rank = {w: i for i, w in enumerate(words)}
    order = target[np.argsort([rank[v // 64] for v in target], kind='stable')]
    keep = count_in(order, src_mask) > 0
    run = np.cumsum(keep) / np.arange(1, len(order) + 1)
    ks = np.unique(np.concatenate([np.arange(1, 200, 5), np.geomspace(200, len(order), 60).astype(int)]))
    ks = ks[ks <= len(order)]
    abort = None
    for k in range(gamma, len(order)):
        if k / len(order) >= tau_prog: break
        if run[k - 1] > tau_sel: abort = k; break
    return {'n': int(len(order)), 'k': [int(k) for k in ks], 'rate': [float(run[k - 1]) for k in ks],
            'final': float(keep.mean()), 'abort_at': abort}
mbig = pu < 0.3
ex['pull_v3'] = pull_curve(B1, m3)
ex['pull_30pct'] = pull_curve(B1, mbig)
ex['pull_30pct']['D_src'] = int(deg[mbig].sum())
# LiveJournal: degree-weighted survival of a push from a 10% set into the full vertex set
offl = np.fromfile(os.path.join(R, 'data', 'bin', 'lj', 'out_off.bin'), dtype=np.uint64)
degl = np.diff(offl).astype(np.int64); ml = int(degl.sum()); nl = len(degl)
bins = np.floor(np.log2(np.maximum(degl, 1))).astype(int)
rho = 0.1
hist = []
sv_v, sv_d = 0.0, 0.0
for b in range(int(bins.max()) + 1):
    sel = bins == b
    cnt, dsum = int(sel.sum()), int(degl[sel].sum())
    if cnt == 0: continue
    drep = 1.5 * 2 ** b if b > 0 else 1.0
    s = 1 - (1 - rho) ** drep
    hist.append({'bin': b, 'deg_lo': int(2 ** b), 'count_share': cnt / nl, 'degsum_share': dsum / ml, 'survival': s})
    sv_v += cnt / nl * s; sv_d += dsum / ml * s
ex['lj_survival'] = {'rho': rho, 'vertices': sv_v, 'degree_sum': sv_d, 'hist': hist, 'n': nl, 'm': ml}
# time breakdown of three LiveJournal queries (one process, all methods: final18c_lj1k.csv)
d = pd.read_csv(os.path.join(R, 'results', 'final18c_lj1k.csv'))
d = d[d.status == 'ok']
agg = d.groupby(['qid', 'method'])[['init_ms', 'transfer_ms', 'join_ms', 'total_ms']].mean()
piv = agg.unstack()
ok = piv.dropna(subset=[('total_ms', 'M0'), ('total_ms', 'M4'), ('total_ms', 'M6'), ('total_ms', 'M3')])
cand = pd.DataFrame({'M0': ok[('total_ms', 'M0')], 'M3': ok[('total_ms', 'M3')], 'M4': ok[('total_ms', 'M4')], 'M6': ok[('total_ms', 'M6')],
                     'M4_tr': ok[('transfer_ms', 'M4')], 'M4_join': ok[('join_ms', 'M4')], 'M0_join': ok[('join_ms', 'M0')], 'M6_tr': ok[('transfer_ms', 'M6')], 'M6_join': ok[('join_ms', 'M6')]})
cand['M4_ratio'] = cand.M4 / cand.M0; cand['M6_ratio'] = cand.M6 / cand.M0
ex['breakdown_candidates'] = {
    'transfer_dominates': cand[(cand.M0 > 50) & (cand.M4_join > 0.6 * cand.M0_join)].sort_values('M4_ratio', ascending=False).head(5).round(1).reset_index().to_dict('records'),
    'reduction_helps_but_costs': cand[(cand.M0 > 200) & (cand.M4_join < 0.3 * cand.M0_join)].sort_values('M4_ratio', ascending=False).head(5).round(1).reset_index().to_dict('records'),
    'rptg_gains': cand[(cand.M0 > 200) & (cand.M6_ratio < 0.5)].sort_values('M6_ratio').head(5).round(1).reset_index().to_dict('records')}
def rows_for(qids):
    out = {}
    for q in qids:
        out[int(q)] = {mth: {k: float(agg.loc[(q, mth), k]) for k in ['init_ms', 'transfer_ms', 'join_ms', 'total_ms']} for mth in ['M0', 'M3', 'M4', 'M6']}
    return out
ex['breakdown_rows'] = rows_for([r['qid'] for key in ex['breakdown_candidates'] for r in ex['breakdown_candidates'][key][:2]])
json.dump(ex, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'example.json'), 'w'), indent=1)
print(json.dumps({k: v for k, v in ex.items() if k not in ('pull_v3', 'pull_30pct', 'lj_survival', 'breakdown_rows')}, indent=1)[:3000])
print('pull_v3: n', ex['pull_v3']['n'], 'final', round(ex['pull_v3']['final'], 3), 'abort', ex['pull_v3']['abort_at'])
print('pull_30pct: n', ex['pull_30pct']['n'], 'final', round(ex['pull_30pct']['final'], 3), 'abort', ex['pull_30pct']['abort_at'], 'D_src', ex['pull_30pct']['D_src'])
print('LJ survival rho=0.1: vertices %.3f degree-sum %.3f' % (ex['lj_survival']['vertices'], ex['lj_survival']['degree_sum']))

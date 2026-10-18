"""Evaluation figures: operation counts on five graphs (replaces the former Table 2) and total times of the
counting join over every workload. Usage: python make_eval.py  (reads numbers.json and ops5.json)."""
import json, os
from dio import Fig, Plot, legend
from make_figures import C, out, N

HERE = os.path.dirname(os.path.abspath(__file__))
OPS = json.load(open(os.path.join(HERE, 'ops5.json')))
INK, MUT, GRID = C['ink'], C['muted'], C['grid']
COL = {'transfer': '#a9bdd6', 'scanned': '#1f6fd0', 'counted': '#8a8a8a'}
GRAPHS = [('dblp', 'DBLP'), ('lj', 'LiveJournal'), ('youtube', 'YouTube'), ('orkut', 'Orkut'), ('pokec', 'Pokec')]
METHODS = [('M0', 'no transfer'), ('M3', 'static semi-mask'), ('M4', 'Yannakakis bitmap'), ('M6', 'RPT-G'), ('M8', 'RPT-G, counting')]


def fig_ops():
    W, H = 506, 128
    f = Fig(W, H)
    x0, pw, gap, top, bh, mg = 96, 74, 9, 30, 3.4, 4.5          # label column, panel width, gap, top margin, bar height, method gap
    ph = len(METHODS) * (3 * bh + mg) - mg
    lo, hi = 1e6, 1e14
    for gi, (g, name) in enumerate(GRAPHS):
        px = x0 + gi * (pw + gap)
        p = Plot(f, px, top, pw, ph, (lo, hi), (0, 1), xlog=True)
        for e in range(6, 15, 2):
            X = p.X(10 ** e)
            f.line([(X, top), (X, top + ph)], color=GRID, sw=0.4)
            if e < 14:
                f.text(X, top + ph + 3, f'$10^{{{e}}}$', fs=5.6, va='top', color=MUT)
        f.line([(px, top), (px, top + ph)], color=INK, sw=0.6)
        f.line([(px, top + ph), (px + pw, top + ph)], color=INK, sw=0.6)
        f.text(px + pw / 2, top - 3, name, fs=6.6, va='bottom', bold=True)
        y = top
        for m, mname in METHODS:
            o = OPS[g][m]
            for key in ('transfer', 'scanned', 'counted'):
                v = o[key]
                if v >= lo:
                    f.rect(px, y, p.X(v) - px, bh, fill=COL[key], stroke='none')
                y += bh
            y += mg
    y = top
    for m, mname in METHODS:
        f.text(x0 - 4, y + 1.5 * bh, mname, fs=6.2, ha='right', color=INK)
        y += 3 * bh + mg
    f.text(x0 + (5 * pw + 4 * gap) / 2, H - 3, 'adjacency entries over the queries that every method finished: 979 (DBLP), 753, 853, 714, 861 (log scale)', fs=6.2, va='bottom', color=INK)
    legend(f, 4, 7, [('visited by the transfers', COL['transfer'], 'bar', None), ('scanned by the join', COL['scanned'], 'bar', None),
                     ('counted as output, not scanned', COL['counted'], 'bar', None)], fs=6.2, row=9, sample=9, col_w=[0, 112, 214], ncol=3)
    f.save(out('fig_ops'))
    print('wrote fig_ops')


def fig_totals():
    # evaluated queries only, as in the tables: standalone engine (five graphs, two chain workloads) and the counting runs in the hosts
    rows = []
    for g, name in [('dblp', 'DBLP'), ('lj', 'LiveJournal')]:
        t = N['final'][g]['total_s']; rows.append((name, t['M0'], t['M6'], t['M8']))
    for g, name in [('youtube', 'YouTube'), ('orkut', 'Orkut'), ('pokec', 'Pokec'), ('dblp_chain', 'DBLP, 8-10 vertices'), ('lj_chain', 'LiveJournal, 8-10 vertices')]:
        t = N['more'][g]['total_s']; rows.append((name, t['M0'], t['M6'], t['M8']))
    hosts = [('Kùzu, DBLP-300', 87.7, 66.8, 6.4), ('PostgreSQL, DBLP-300', 146.7, None, 26.1), ('DuckDB, DBLP-300', 89.3, None, 13.8)]
    W = 241
    bh, mg, top, x0, pw = 3.6, 4.0, 16, 92, 118
    groups = rows + hosts
    H = top + len(groups) * (3 * bh + mg) + 30
    f = Fig(W, H)
    p = Plot(f, x0, top, pw, H - top - 30, (1, 1000), (0, 1), xlog=True)
    for e in (1, 10, 100, 1000):
        X = p.X(e)
        f.line([(X, top - 2), (X, H - 30)], color=GRID, sw=0.4)
        f.text(X, H - 27, f'{e:,}', fs=6, va='top', color=MUT)
    f.text(x0 + pw / 2, H - 17, 'total time of the evaluated queries (s, log scale)', fs=6.4, va='top', color=INK)
    y = top
    for name, b, r, c in groups:
        if name == hosts[0][0]:
            f.line([(4, y - mg / 2), (W - 4, y - mg / 2)], color=GRID, sw=0.6)
        vals = [(b, C['base']), (r, '#a9bdd6'), (c, C['rptg'])]
        for v, col in vals:
            if v is not None:
                f.rect(x0, y, max(p.X(v) - x0, 0.5), bh, fill=col, stroke='none')
                f.text(p.X(v) + 2, y + bh / 2, f'{v:.0f}' if v >= 10 else f'{v:.1f}', fs=5.4, ha='left', color=INK)
            y += bh
        f.text(x0 - 4, y - 1.5 * bh, name, fs=6.0, ha='right', color=INK)
        y += mg
    f.line([(x0, top - 2), (x0, H - 30)], color=INK, sw=0.6)
    legend(f, 4, 6, [('no transfer', C['base'], 'bar', None), ('RPT-G', '#a9bdd6', 'bar', None), ('RPT-G, counting', C['rptg'], 'bar', None)],
           fs=6.2, row=9, sample=9, col_w=[0, 62, 112], ncol=3)
    f.save(out('fig_totals'))
    print('wrote fig_totals')


if __name__ == '__main__':
    fig_ops(); fig_totals()

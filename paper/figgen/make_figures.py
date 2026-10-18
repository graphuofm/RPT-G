"""Generate every figure of the paper as ../figures/<name>.pdf plus an editable ../figures/<name>.drawio.

Usage: python data.py && python make_figures.py      (data.py writes numbers.json and series.pkl)
Widths: 241 units = one ACM column, 506 units = full text width (1 unit = 1 pt).
"""
import json
import os
import pickle

import numpy as np

from dio import Fig, Plot, legend

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'figures')
N = json.load(open(os.path.join(HERE, 'numbers.json')))
S = pickle.load(open(os.path.join(HERE, 'series.pkl'), 'rb'))

# one colour per method family, the same in every figure (validated with the dataviz palette checker)
C = {'rptg': '#1f6fd0', 'static': '#a9bdd6', 'yann': '#5b7fae', 'rptplus': '#1b3a6b', 'exact': '#d3dce8',
     'base': '#8a8a8a', 'ink': '#222222', 'muted': '#666666', 'grid': '#e3e3e3'}
DASH = {'rptg': None, 'static': (4, 1.5), 'yann': (1.2, 1.4), 'rptplus': (5, 1.5, 1.2, 1.5), 'exact': (2.5, 1.5),
        'base': (1, 1)}


def out(name):
    return os.path.join(OUT, name)


def pct_curve(sp, n=160):
    s = np.sort(np.asarray(sp, dtype=float))
    idx = np.unique(np.linspace(0, len(s) - 1, n).round().astype(int))
    return idx / (len(s) - 1) * 100, s[idx]


# ============================================================ Figure 1: regressions of existing transfer schemes
def fig_motivation():
    P, K = N['proto_dblp'], N['proto_lj']
    groups = [
        ('DBLP trees', '0.9x', P['noise'], [('static', P['M3']['regr']), ('yann', P['M4']['regr']), ('rptg', P['M6']['regr'])]),
        ('LJ trees', '0.9x', K['noise'], [('static', K['M3']['regr']), ('yann', K['M4']['regr']), ('rptg', K['M6']['regr'])]),
    ]
    for key, name in [('cyc_dblp', 'DBLP cycles'), ('cyc_lj', 'LJ cycles')]:
        cy = N.get('cyclic', {}).get(key)
        if cy:
            groups.append((name, '0.9x', cy['noise'], [('static', cy['M3']['regr']), ('yann', cy['M4']['regr']),
                                                       ('exact', cy['M5']['regr']), ('rptg', cy['M6']['regr'])]))
    bh, gap, ggap = 5.2, 1.1, 7.0
    top = 30
    nb = sum(len(g[3]) for g in groups)
    H = top + nb * (bh + gap) + len(groups) * ggap + 22
    f = Fig(241, H)
    x0, pw = 84, 146
    p = Plot(f, x0, top, pw, H - top - 22, (0, 100), (0, 1))
    for v in (0, 25, 50, 75, 100):
        X = p.X(v)
        f.line([(X, top - 2), (X, H - 22)], color=C['grid'], sw=0.4)
        f.line([(X, H - 22), (X, H - 20)], color=C['ink'], sw=0.5)
        f.text(X, H - 19, f'{v}%', fs=6.5, va='top')
    f.text(x0 + pw / 2, H - 10, 'share of queries slower than the baseline', fs=7, va='top')
    y = top + 3
    for name, thr, noise, bars in groups:
        gy0 = y
        for key, v in bars:
            f.rect(x0, y, max(p.X(v) - x0, 0.6), bh, fill=C[key], stroke='none')
            lx = p.X(v) + 2
            if p.X(noise) - 1 <= lx + 9 and p.X(noise) >= p.X(v) - 1:   # the label would cross the noise marker
                lx = max(p.X(v), p.X(noise)) + 2.5
            f.text(lx, y + bh / 2, f'{v:.0f}%', fs=6, ha='left', color=C['ink'])
            y += bh + gap
        gy1 = y - gap
        f.text(x0 - 4, (gy0 + gy1) / 2 - 3.5, name, fs=6.6, ha='right', color=C['ink'])
        f.text(x0 - 4, (gy0 + gy1) / 2 + 4, f'threshold {thr}', fs=6, ha='right', color=C['muted'])
        X = p.X(noise)
        f.line([(X, gy0 - 1.5), (X, gy1 + 1.5)], color=C['ink'], sw=0.9)
        y += ggap
    f.line([(x0, top - 2), (x0, H - 22)], color=C['ink'], sw=0.6)
    items = [('static semi-mask', C['static'], 'bar', None), ('Yannakakis bitmap', C['yann'], 'bar', None),
             ('arc consistency', C['exact'], 'bar', None), ('RPT-G', C['rptg'], 'bar', None)]
    legend(f, 4, 7, items, fs=6.5, row=9, sample=10, col_w=[0, 78, 160], ncol=3)
    f.line([(163, 16), (163, 22)], color=C['ink'], sw=0.9)
    f.text(170, 19, 'noise floor', fs=6.5, ha='left')
    f.save(out('fig_motivation'))


# ============================================================ Figure 2: running example
def fig_example():
    f = Fig(241, 158)
    # (a) pattern
    f.text(4, 6, '(a) pattern, join order', fs=7, ha='left', bold=True)
    pos = {0: (20, 40), 1: (50, 76), 2: (20, 112), 3: (84, 112)}
    fills = {0: '#d9e7f8', 1: '#ffffff', 2: '#ffffff', 3: '#d9e7f8'}
    for a, b in [(0, 1), (1, 2), (1, 3)]:
        f.line([pos[a], pos[b]], color=C['ink'], sw=0.9)
    for v, (x, y) in pos.items():
        f.ellipse(x, y, 9, 9, fill=fills[v], stroke=C['ink'], sw=0.8, label=f'$v_{v}$', fs=8)
    f.text(32, 26, '$pu < 10^{-3}$', fs=6.5, ha='left')
    f.text(32, 34, '$|B_0| = 302$', fs=6.5, ha='left', color=C['muted'])
    f.text(84, 126, 'top-1% degree', fs=6.5)
    f.text(84, 134, '$|B_3| = 3{,}171$', fs=6.5, color=C['muted'])
    f.text(2, 126, 'no predicate', fs=6.5, ha='left', color=C['muted'])
    f.text(62, 76, 'no predicate', fs=6.5, ha='left', color=C['muted'])
    f.text(4, 154, 'join: start $v_0$; then $v_1$, $v_2$, $v_3$', fs=6.5, ha='left', va='bottom')
    # (b) transfer schedule with decisions
    x0 = 118
    f.text(x0, 6, '(b) transfers, root $v_1$', fs=7, ha='left', bold=True)
    tag = {'PUSH': ('#2a78d6', '#ffffff'), 'PULL': ('#2a78d6', '#ffffff'), 'SKIP': ('#e9e9e9', '#222222')}
    rows = [('$v_0 \\to v_1$', 'PUSH', 'push $\\Sigma\\mathrm{deg}(B_0)$ = 2.3K'),
            ('$v_2 \\to v_1$', 'SKIP', 'sources($v_2$) = $\\emptyset$'),
            ('$v_3 \\to v_1$', 'PULL', 'push 238K > pull $\\leq$ 63K'),
            ('$v_1 \\to v_0$', 'PULL', 'join starts at $v_0$'),
            ('$v_1 \\to v_2$', 'SKIP', 'no consumer of $B_2$'),
            ('$v_1 \\to v_3$', 'SKIP', 'no consumer of $B_3$')]
    y = 22
    f.text(x0, y - 4, 'forward', fs=6.3, ha='left', color=C['muted'], va='bottom')
    for i, (t, d, why) in enumerate(rows):
        if i == 3:
            y += 7
            f.text(x0, y - 4, 'backward', fs=6.3, ha='left', color=C['muted'], va='bottom')
        f.text(x0, y + 5, t, fs=7, ha='left')
        bg, fg = tag[d]
        f.rect(x0 + 38, y, 25, 10, fill=bg, stroke='none', r=2, label=d, fs=6.3, color=fg, bold=True)
        f.text(x0 + 38, y + 15, why, fs=6.1, ha='left', color=C['muted'])
        y += 20
    f.line([(110, 14), (110, 154)], color=C['grid'], sw=0.6)
    f.save(out('fig_example'))


# ============================================================ Figure 3: architecture
def fig_overview():
    ink, mut = C['ink'], C['muted']
    host_fill, rptg_fill = '#f2f2f2', '#e6f0fb'
    blocks = [('Host optimizer', ['join order, join methods, plan tree'], host_fill, 'plan'),
              ('RPT-G glue  (plan time)',
               ['1  recover the pattern and the host\'s join tree',
                '2  plan: spanning tree, closing edges, two passes',
                '3  prune: provenance (bridges), consumption',
                '4  pre-screen on estimated sizes'], rptg_fill, 'admitted transfers'),
              ('RPT-G core  (run time)',
               ['exact $|B_x|$ and $\\Sigma\\mathrm{deg}(B_x)$ from bitmaps',
                'admit iff $\\min(\\mathrm{push}, \\mathrm{pull}) \\leq \\beta \\cdot$ plan work removed',
                'then PUSH, PULL (may abort), or SKIP'], rptg_fill, 'candidate bitmaps $B_v$'),
              ('Host main plan',
               ['scans filtered by $B_v$ (row-exact)',
                'filtered adjacency, neighbour masks',
                'join operators and order unchanged'], host_fill, None)]
    heights = [16 + 8.6 * len(b[1]) for b in blocks]
    H = sum(heights) + 12 * (len(blocks) - 1) + 20
    f = Fig(241, H)
    y, ys = 4, []
    for (title, lines, fill, arrow), h in zip(blocks, heights):
        f.rect(4, y, 158, h, fill=fill, stroke='#9aa7b4' if fill == rptg_fill else '#b5b5b5', sw=0.7, r=3)
        f.text(9, y + 7.5, title, fs=7.2, ha='left', bold=True)
        for i, s_ in enumerate(lines):
            f.text(11, y + 17.5 + i * 8.6, s_, fs=6.3, ha='left', color=ink)
        ys.append((y, h))
        if arrow:
            f.line([(83, y + h), (83, y + h + 12)], color=ink, sw=0.8, arrow='end', head=4)
            f.text(87, y + h + 6, arrow, fs=6.1, ha='left', color=mut)
        y += h + 12
    cy, ch = ys[2]
    f.rect(168, cy - 4, 69, ch + 8, fill='#ffffff', stroke='#9aa7b4', sw=0.7, r=3, dash=(2, 1.5))
    f.text(202.5, cy + 3.5, 'per pattern vertex $v$', fs=6.3, bold=True)
    for i, s_ in enumerate(['bitmap $B_v$', 'size $|B_v|$', 'degree sums', 'sources($v$)']):
        f.text(172, cy + 14 + i * 8.2, s_, fs=6.2, ha='left')
    f.line([(168, cy + ch / 2), (162, cy + ch / 2)], color=mut, sw=0.6, dash=(2, 1.5), arrow='both', head=3)
    gy, gh = ys[1]
    f.rect(168, gy, 69, gh, fill='#ffffff', stroke='#b5b5b5', sw=0.6, r=3)
    f.text(202.5, gy + 7.5, 'glue per host', fs=6.3, bold=True)
    for i, s_ in enumerate(['K\u00f9zu: optimizer rule,', '  side pipelines', 'PostgreSQL: planner,', '  executor hooks', 'DuckDB: optimizer pass']):
        f.text(172, gy + 17 + i * 7.6, s_, fs=5.8, ha='left', color=ink)
    f.text(4, H - 6, 'The core is the standalone engine; all three hosts share it through a C interface.', fs=6.1,
           ha='left', color=mut)
    f.save(out('fig_overview'))


# ============================================================ Figure 4: prototype speedup distributions
def fig_proto_speedups():
    f = Fig(506, 158)
    specs = [('proto_dblp', 'DBLP (4,693 queries)'), ('proto_lj', 'LiveJournal')]
    for i, (k, title) in enumerate(specs):
        n = len(S[k]['M6'])
        title = f'{"DBLP" if i == 0 else "LiveJournal"} ({n:,} queries)'
        p = Plot(f, 42 + i * 240, 16, 205, 100, (0, 100), (0.02, 50), ylog=True)
        p.yticks([0.02, 0.1, 0.5, 1, 2, 10, 50], ['0.02', '0.1', '0.5', '1', '2', '10', '50'])
        p.xticks([0, 25, 50, 75, 100], ['0', '25', '50', '75', '100'])
        p.hline(1.0, color='#444444', sw=0.6, dash=(3, 2))
        for m, key in [('M3', 'static'), ('M4', 'yann'), ('M6', 'rptg')]:
            xs, ys = pct_curve(S[k][m])
            p.curve(xs, ys, C[key], sw=1.3, dash=DASH[key])
        p.frame()
        p.title(title)
        p.xlabel('query percentile (sorted by speedup)')
        if i == 0:
            p.ylabel('speedup over no transfer', dx=24)
    legend(f, 100, 150, [('static semi-mask (M3)', C['static'], DASH['static'], None),
                         ('Yannakakis bitmap (M4)', C['yann'], DASH['yann'], None),
                         ('RPT-G (M6)', C['rptg'], None, None)], fs=7, sample=16, col_w=120, ncol=3)
    f.save(out('fig_proto_speedups'))


# ============================================================ Figure 5: join-order robustness
def fig_robustness():
    f = Fig(241, 146)
    for i, (k, title) in enumerate([('robust_dblp', 'DBLP'), ('robust_lj', 'LiveJournal')]):
        p = Plot(f, 30 + i * 108, 14, 92, 88, (1, 3000), (0, 100), xlog=True)
        p.xticks([1, 10, 100, 1000], ['1', '10', '100', '1K'])
        p.yticks([0, 25, 50, 75, 100], ['0', '25', '50', '75', '100'] if i == 0 else [''] * 5)
        p.vline(2.8, color='#444444', sw=0.6, dash=(3, 2))
        for m, key in [('M0', 'base'), ('M4', 'yann'), ('M6', 'rptg')]:
            fac = np.sort(S[k][m])
            ys = np.arange(1, len(fac) + 1) / len(fac) * 100
            xs = np.concatenate([[1], np.repeat(fac, 2)])
            yy = np.concatenate([[0, 0], np.repeat(ys, 2)])[:len(xs)]
            p.curve(xs, yy, C[key], sw=1.3, dash=DASH[key])
        p.frame()
        p.title(title)
        p.xlabel('robustness factor (max / min)', dy=11)
        if i == 0:
            p.ylabel('% of queries', dx=17)
    legend(f, 12, 131, [('no transfer (M0)', C['base'], DASH['base'], None), ('Yannakakis (M4)', C['yann'], DASH['yann'], None),
                        ('RPT-G (M6)', C['rptg'], None, None), ("RPT's largest factor (2.8)", '#444444', (3, 2), None)],
           fs=6.5, row=9, sample=12, col_w=[0, 110], ncol=2)
    f.save(out('fig_robustness'))


# ============================================================ Figure 6: speedups inside the hosts
def fig_hosts():
    f = Fig(506, 150)
    lab = {'KSM': 'static', 'KSX': 'exact', 'KR2': 'rptg', 'PGR': 'rptg', 'dkr': 'rptg'}
    panels = [('K\u00f9zu, DBLP', [('kuzu_dblp', 'KSM'), ('kuzu_dblp_ksx', 'KSX'), ('kuzu_dblp', 'KR2')]),
              ('K\u00f9zu, LiveJournal', [('kuzu_lj', 'KSM'), ('kuzu_lj', 'KR2')]),
              ('K\u00f9zu, DBLP cycles', [('kuzu_cyc', 'KSM'), ('kuzu_cyc', 'KR2')]),
              ('K\u00f9zu, LSQB-P', [('lsqbp', 'KSM'), ('lsqbp', 'KR2')]),
              ]   # PostgreSQL and DuckDB stay at 1 under their own plans: see Table hosts and fig_host_robust
    panels = [(t, [(k, c) for k, c in ser if k in S and c in S[k]]) for t, ser in panels]
    panels = [(t, ser) for t, ser in panels if ser]
    n = len(panels)
    gap = 12
    pw = (506 - 36 - gap * (n - 1) - 4) / n
    for i, (title, series) in enumerate(panels):
        p = Plot(f, 36 + i * (pw + gap), 16, pw, 94, (0, 100), (0.1, 30), ylog=True)
        p.yticks([0.1, 0.5, 1, 2, 10, 30], ['0.1', '0.5', '1', '2', '10', '30'] if i == 0 else [''] * 6)
        p.xticks([0, 50, 100])
        p.hline(1.0, color='#444444', sw=0.6, dash=(3, 2))
        for k, c in series:
            xs, ys = pct_curve(S[k][c])
            key = lab[c]
            p.curve(xs, ys, C[key], sw=1.3, dash=DASH[key])
        p.frame()
        p.title(title, fs=6.8)
        p.xlabel('query percentile', dy=11)
        if i == 0:
            p.ylabel('speedup over no transfer', dx=21)
    legend(f, 60, 143, [('host semi-mask (K\u00f9zu)', C['static'], DASH['static'], None),
                        ('K\u00f9zu semi-mask, row-exact masks', C['exact'], DASH['exact'], None),
                        ('RPT-G', C['rptg'], None, None)],
           fs=7, sample=16, col_w=[0, 150, 330], ncol=3)
    f.save(out('fig_hosts'))


# ============================================================ join-order robustness inside the hosts
def fig_host_robust():
    rb = [(k, lab, key) for k, lab, key in [('kuzu_dblp_robust_KR2', 'K\u00f9zu, RPT-G', 'rptg'),
                                              ('kuzu_dblp_robust_KSM', 'K\u00f9zu semi-mask', 'static'),
                                              ('pg19_dblp_robust_PGR', 'PostgreSQL, RPT-G', 'rptplus'),
                                              ('duckdb_dblp_robust_dkr', 'DuckDB, RPT-G', 'yann')] if k in S]
    if not rb:
        return
    f = Fig(241, 136)
    p = Plot(f, 30, 8, 204, 82, (0, 100), (0.1, 100), ylog=True)
    p.yticks([0.1, 0.5, 1, 2, 10, 100], ['0.1', '0.5', '1', '2', '10', '100'])
    p.xticks([0, 25, 50, 75, 100])
    p.hline(1.0, color='#444444', sw=0.6, dash=(3, 2))
    for k, lab, key in rb:
        xs, ys = pct_curve(np.clip(S[k], 0.1, 100))
        p.curve(xs, ys, C[key], sw=1.3, dash=DASH[key])
    p.frame()
    p.xlabel('(query, order) pairs, percentile', dy=17)
    p.ylabel('speedup over no transfer', dx=20)
    legend(f, 8, 118, [(lab, C[key], DASH[key], None) for _, lab, key in rb], fs=6.3, sample=12,
           col_w=[0, 112], ncol=2, row=9)
    f.save(out('fig_host_robust'))


# ============================================================ Figure 7: beta sensitivity
def fig_beta():
    f = Fig(241, 116)
    betas = ['0', '0.25', '0.5', '1', '2', '4']
    for i, (g, title) in enumerate([('dblp', 'DBLP'), ('lj', 'LiveJournal')]):
        p = Plot(f, 30 + i * 108, 14, 94, 70, (-0.4, 5.4), (0, 20))
        p.xticks(range(6), ['off', '.25', '.5', '1', '2', '4'])
        p.yticks([0, 5, 10, 15, 20], ['0', '5', '10', '15', '20'] if i == 0 else [''] * 5)
        sw = N['sweeps'][g]
        xs = list(range(6))
        p.curve(xs, [sw[b]['noise'] for b in betas], '#8a8a8a', sw=1.0, dash=(2, 1.5))
        p.curve(xs, [sw[b]['regr'] for b in betas], C['rptg'], sw=1.3)
        for x in xs:
            f.marker(p.X(x), p.Y(sw[betas[x]]['regr']), 'o', 4.2, fill=C['rptg'])
        p.frame()
        p.title(title)
        p.xlabel('budget factor $\\beta$', dy=11)
        if i == 0:
            p.ylabel('% of queries < 0.9×', dx=17)
    legend(f, 30, 110, [('RPT-G vs. no transfer', C['rptg'], None, 'o'), ('noise floor of the same run', '#8a8a8a', (2, 1.5), None)],
           fs=6.5, sample=14, col_w=[0, 100], ncol=2)
    f.save(out('fig_beta'))


# ============================================================ headroom: total time under exact vs estimated orders
def fig_headroom():
    oq = N.get('order_quality', {})
    graphs = [g for g in ['dblp', 'lj'] if f'{g}_exact' in oq and f'{g}_est' in oq]   # YouTube: numbers in the text
    names = {'dblp': 'DBLP', 'lj': 'LiveJournal', 'youtube': 'YouTube'}
    methods = [('M0', 'no transfer', 'base'), ('M4', 'Yannakakis bitmap', 'yann'), ('M6', 'RPT-G', 'rptg')]
    W = 506 if len(graphs) > 2 else 241
    gapx = 34
    pw = (W - 30 - gapx * (len(graphs) - 1) - 4) / len(graphs)
    f = Fig(W, 128)
    for gi, g in enumerate(graphs):
        top = max(oq[f'{g}_{o}']['total_s'][m] for o in ['exact', 'est'] for m, _, _ in methods)
        ymax = [v for v in (500, 1000, 2000, 3000, 4000, 6000) if v >= top * 1.12][0]
        p = Plot(f, 30 + gi * (pw + gapx), 12, pw, 80, (0, 2), (0, ymax))
        ticks = [0, ymax / 2, ymax]
        p.yticks(ticks, [f'{t / 1000:g}' if ymax >= 2000 else f'{t:g}' for t in ticks])
        bw = min(16.0, pw / 8)
        for oi, o in enumerate(['exact', 'est']):
            cx = p.X(0.5 + oi)
            for mi, (m, _, key) in enumerate(methods):
                v = oq[f'{g}_{o}']['total_s'][m]
                x = cx + (mi - 1) * (bw + 1.5) - bw / 2
                f.rect(x, p.Y(v), bw, p.Y(0) - p.Y(v), fill=C[key], stroke='none')
                f.text(x + bw / 2, p.Y(v) - 1.5, f'{v / 1000:.2f}' if ymax >= 2000 else f'{v:.0f}', fs=5.6,
                       va='bottom', color=C['ink'], rot=0)
            f.text(cx, p.y + p.h + 4, 'exact sizes' if o == 'exact' else '10% estimate', fs=6.3, va='top')
        p.frame()
        p.title(names[g] + (' (1000 s)' if ymax >= 2000 else ' (s)'), fs=7)
        if gi == 0:
            p.ylabel('total time', dx=20)
    f.text(W / 2, 108, 'join order built from', fs=6.3, color=C['muted'])
    legend(f, W / 2 - 110, 121, [(lab, C[key], 'bar', None) for _, lab, key in methods], fs=6.5, sample=10, col_w=[0, 70, 160], ncol=3)
    f.save(out('fig_headroom'))


# ============================================================ cyclic patterns: regressions per method
def fig_cycles():
    cy = N.get('cyclic', {})
    runs = [(k, lab) for k, lab in [('cyc_dblp', 'DBLP, exact-size order'), ('cyc_dblp_est', 'DBLP, 10%-estimate order'),
                                     ('cyc_lj', 'LiveJournal, exact'), ('cyc_lj_est', 'LiveJournal, 10% estimate')] if k in cy]
    methods = [('M3', 'static semi-mask', 'static'), ('M4', 'Yannakakis (spanning tree)', 'yann'),
               ('M5', 'arc consistency', 'exact'), ('M6', 'RPT-G', 'rptg')]
    bh, gap, ggap, top = 5.2, 1.0, 7.0, 26
    H = top + len(runs) * (len(methods) * (bh + gap) + ggap) + 22
    f = Fig(241, H)
    x0, pw = 92, 138
    p = Plot(f, x0, top, pw, H - top - 22, (0, 100), (0, 1))
    for v in (0, 25, 50, 75, 100):
        X = p.X(v)
        f.line([(X, top - 2), (X, H - 22)], color=C['grid'], sw=0.4)
        f.text(X, H - 19, f'{v}%', fs=6.5, va='top')
    f.text(x0 + pw / 2, H - 10, 'share of cyclic queries slower than 0.9x', fs=7, va='top')
    y = top + 3
    for k, lab in runs:
        gy0 = y
        noise = cy[k]['noise']
        for m, _, key in methods:
            v = cy[k][m]['regr']
            f.rect(x0, y, max(p.X(v) - x0, 0.6), bh, fill=C[key], stroke='none')
            lx = p.X(v) + 2
            if p.X(noise) - 1 <= lx + 12 and p.X(noise) >= p.X(v) - 1:   # keep the label clear of the noise marker
                lx = max(p.X(v), p.X(noise)) + 4
            txt = f'{v:.0f}%' + (f'   geo. mean {cy[k][m]["geomean"]:.2f}x' if m == 'M6' else '')
            f.text(lx, y + bh / 2, txt, fs=6, ha='left', color=C['ink'])
            y += bh + gap
        f.text(x0 - 4, (gy0 + y - gap) / 2, lab, fs=6.4, ha='right', color=C['ink'])
        X = p.X(noise)
        f.line([(X, gy0 - 1.5), (X, y - gap + 1.5)], color=C['ink'], sw=0.9)
        y += ggap
    f.line([(x0, top - 2), (x0, H - 22)], color=C['ink'], sw=0.6)
    legend(f, 4, 7, [(lab, C[key], 'bar', None) for _, lab, key in methods], fs=6.3, row=9, sample=10, col_w=[0, 80, 180], ncol=3)
    f.save(out('fig_cycles'))


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for fn in [fig_motivation, fig_example, fig_overview, fig_proto_speedups, fig_robustness, fig_hosts, fig_beta,
               fig_headroom, fig_cycles, fig_host_robust]:
        fn()
        print('wrote', fn.__name__[4:])

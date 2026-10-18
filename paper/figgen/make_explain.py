"""The explanatory figures of the paper: where the time goes, what a transfer costs on a graph, the transfer
plan of RPT, RPT+, and RPT-G on the running example, the benefit model, a pull with its abort rule, the two
ski rentals, the counting pass on the example, and the host-plan benefit. Numbers come from example.json
(example_data.py: the DBLP running example, measured LiveJournal survival, recorded runs).

Usage: python example_data.py && python make_explain.py
"""
import json
import os

from dio import Fig, Plot, legend
from make_figures import C, out

HERE = os.path.dirname(os.path.abspath(__file__))
EX = json.load(open(os.path.join(HERE, 'example.json')))
INK, MUT, GRID = C['ink'], C['muted'], C['grid']
BLUE, GREY, ORANGE, GREEN = C['rptg'], '#8a8a8a', '#1b3a6b', '#5b7fae'   # a navy and a slate in place of orange and green
PRED, XFER, JOIN = '#c9d7e8', '#1f6fd0', '#8a8a8a'          # phases of a query


def k(v):
    """1234 -> 1.2K, 1234567 -> 1.2M"""
    if v >= 1e6:
        return f'{v / 1e6:.1f}M'
    if v >= 1e3:
        return f'{v / 1e3:.1f}K' if v < 1e4 else f'{v / 1e3:.0f}K'
    return f'{v:.0f}'


# ============================================================ where the time goes (three LiveJournal queries)
def fig_breakdown():
    rows = EX['breakdown_rows']
    qs = [('4841', 'A: the reduction|removes nothing'), ('1340', 'B: the reduction pays,|the transfers do not'),
          ('1441', 'C: a bad|join order')]
    qs = [(q, t) for q, t in qs if q in rows]
    f = Fig(241, 130)
    pw, gap, x0, top, ph = 58, 11, 30, 28, 64
    meths = [('M0', 'none'), ('M4', 'Yann'), ('M6', 'RPT-G')]
    for i, (q, title) in enumerate(qs):
        r = rows[q]
        tot = max(r[m]['total_ms'] for m, _ in meths)
        px = x0 + i * (pw + gap)
        p = Plot(f, px, top, pw, ph, (0, 3), (0, tot * 1.08))
        f.line([(px, top + ph), (px + pw, top + ph)], color=INK, sw=0.6)
        f.line([(px, top), (px, top + ph)], color=INK, sw=0.6)
        step = 10 ** max(0, len(str(int(tot))) - 1)
        if tot / step < 3:
            step /= 2
        v = 0
        while v <= tot * 1.08:
            Y = p.Y(v)
            f.line([(px - 1.5, Y), (px, Y)], color=INK, sw=0.5)
            f.text(px - 3, Y, k(v) if v else '0', fs=5.6, ha='right')
            v += step
        for j, (m, name) in enumerate(meths):
            bx = px + 4 + j * 18
            y = top + ph
            for key, col in [('init_ms', PRED), ('transfer_ms', XFER), ('join_ms', JOIN)]:
                h = r[m][key] / (tot * 1.08) * ph
                if h > 0.3:
                    f.rect(bx, y - h, 12, h, fill=col, stroke='none')
                y -= h
            f.text(bx + 6, y - 2, f'{r[m]["total_ms"]:.0f}', fs=5.8, va='bottom', color=INK)
            f.text(bx + 6, top + ph + 3, name, fs=5.6, va='top', color=MUT)
        f.text(px + pw / 2, top - 4, title.split(':')[0], fs=6.6, va='bottom', bold=True)
        for li, part in enumerate(title.split(': ')[1].split('|')):
            f.text(px + pw / 2, top + ph + 12 + li * 7, part, fs=5.4, va='top', color=MUT)
    f.text(x0 - 22, top + ph / 2, 'time (ms)', fs=6.5, rot=90)
    legend(f, 4, 7, [('predicates', PRED, 'bar', None), ('transfers', XFER, 'bar', None), ('join', JOIN, 'bar', None)],
           fs=6.3, row=9, sample=9, col_w=[0, 56, 108], ncol=3)
    f.save(out('fig_breakdown'))


# ============================================================ what a transfer costs: relational vs graph
def fig_cost():
    e = EX
    f = Fig(241, 132)
    # (a) relational
    f.text(4, 6, '(a) relational: one filter per plan edge, in the pass direction', fs=6.6, ha='left', bold=True)
    f.rect(8, 16, 40, 22, fill='#f2f2f2', stroke=INK, sw=0.7, r=2, label='table $S$\n$|S|$ rows', fs=6.2)
    f.rect(78, 16, 40, 22, fill='#f2f2f2', stroke=INK, sw=0.7, r=2, label='table $T$\n$|T|$ rows', fs=6.2)
    f.line([(48, 27), (78, 27)], color=INK, sw=0.8, arrow='end', head=4)
    f.text(63, 22, 'Bloom filter', fs=5.8, va='bottom')
    f.text(126, 22, 'cost: scan $S$ to build, probe each row of $T$;', fs=5.8, ha='left', color=INK)
    f.text(126, 31, 'the join scans $S$ and $T$ anyway', fs=5.8, ha='left', color=INK)
    # (b) graph
    f.text(4, 52, '(b) graph: either direction over the adjacency index', fs=6.6, ha='left', bold=True)
    y0 = 78
    ratio = e['D3'] / e['D1']
    f.text(92, y0 - 6, f'push: walk the lists of $B_3$, {k(e["D3"])} entries', fs=5.8, va='bottom', color=ORANGE)
    f.rect(8, y0, 46, 24, fill='#d9e7f8', stroke=INK, sw=0.7, r=2,
           label=f'$B_3$: {e["B3"]:,} hubs\n$\\Sigma$deg = {k(e["D3"])}', fs=6)
    f.rect(130, y0, 46, 24, fill='#ffffff', stroke=INK, sw=0.7, r=2,
           label=f'$B_1$: {e["B1"]:,} vertices\n$\\Sigma$deg = {k(e["D1"])}', fs=6)
    f.line([(54, y0 + 6), (130, y0 + 6)], color=ORANGE, sw=1.0, arrow='end', head=4)
    f.line([(130, y0 + 18), (54, y0 + 18)], color=BLUE, sw=1.0, arrow='end', head=4)
    f.text(92, y0 + 30, f'pull: walk the lists of $B_1$, at most {k(e["D1"])} entries', fs=5.8, va='top', color=BLUE)
    f.text(182, y0 + 7, 'same result,', fs=6, ha='left', color=INK)
    f.text(182, y0 + 16, f'{ratio:.1f}$\\times$ apart', fs=6, ha='left', color=INK)
    f.text(4, 122, 'the direction is a choice per transfer, and the cheaper one is known exactly', fs=5.8, ha='left', color=INK)
    f.save(out('fig_cost'))


# ============================================================ transfer plans on the running example
def _pattern(f, ox, oy, edges, pos, fills, extra_edge=None):
    for a, b in edges:
        f.line([(ox + pos[a][0], oy + pos[a][1]), (ox + pos[b][0], oy + pos[b][1])], color=INK, sw=0.8)
    if extra_edge:
        a, b = extra_edge
        f.line([(ox + pos[a][0], oy + pos[a][1]), (ox + pos[b][0], oy + pos[b][1])], color=INK, sw=0.8, dash=(2, 1.5))
    for v, (x, y) in pos.items():
        f.ellipse(ox + x, oy + y, 7.5, 7.5, fill=fills[v], stroke=INK, sw=0.7, label=f'$v_{v}$', fs=6.8)


def _arrow(f, ox, oy, pos, a, b, color, side=1, num=None, dash=None):
    (xa, ya), (xb, yb) = pos[a], pos[b]
    dx, dy = xb - xa, yb - ya
    L = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / L, dy / L
    nx, ny = -uy * side * 3.4, ux * side * 3.4            # offset to one side of the edge
    p0 = (ox + xa + ux * 9 + nx, oy + ya + uy * 9 + ny)
    p1 = (ox + xb - ux * 9 + nx, oy + yb - uy * 9 + ny)
    f.line([p0, p1], color=color, sw=0.9, arrow='end', head=3.5, dash=dash)
    if num is not None:
        mx, my = (p0[0] + p1[0]) / 2 + nx * 2.3, (p0[1] + p1[1]) / 2 + ny * 2.3
        f.ellipse(mx, my, 3.6, 3.6, fill='#ffffff', stroke=color, sw=0.6, label=str(num), fs=4.8, color=color)


def fig_plans():
    e = EX
    f = Fig(506, 150)
    pos = {0: (26, 26), 1: (52, 54), 2: (26, 82), 3: (82, 82)}
    fills = {0: '#d9e7f8', 1: '#ffffff', 2: '#ffffff', 3: '#d9e7f8'}
    edges = [(0, 1), (1, 2), (1, 3)]
    panels = [(0, '(a) RPT', 'symmetric: every edge, both passes'),
              (128, '(b) RPT+', 'asymmetric: fewer, larger filters'),
              (256, '(c) RPT-G', 'pruned, cheaper direction per transfer'),
              (384, '(d) RPT-G on a cycle', 'spanning tree and closing edge')]
    for ox, title, sub in panels:
        f.text(ox + 2, 6, title, fs=6.6, ha='left', bold=True)
        f.text(ox + 2, 14, sub, fs=5.6, ha='left', color=MUT)
        _pattern(f, ox, 18, edges, pos, fills, extra_edge=(0, 3) if ox == 384 else None)
    ty = 112
    # (a) RPT: six Bloom filters
    ox = 0
    for a, b, i in [(0, 1, 1), (2, 1, 2), (3, 1, 3)]:
        _arrow(f, ox, 18, pos, a, b, GREY, side=1, num=i)
    for a, b, i in [(1, 0, 4), (1, 2, 5), (1, 3, 6)]:
        _arrow(f, ox, 18, pos, a, b, GREY, side=1, num=i)
    for i, s in enumerate(['6 filters, each a scan of the source', 'and a probe of the target;', '$v_2$ carries nothing; the direction', 'is the direction of the pass']):
        f.text(ox + 2, ty + i * 8, s, fs=5.5, ha='left', color=INK)
    # (b) RPT+
    ox = 128
    for a, b, i in [(0, 1, 1), (3, 1, 2)]:
        _arrow(f, ox, 18, pos, a, b, GREY, side=1, num=i)
    for a, b, i in [(1, 0, 3), (1, 2, 4), (1, 3, 5)]:
        _arrow(f, ox, 18, pos, a, b, GREY, side=1, num=i)
    for i, s in enumerate(['no forward filter from the unfiltered $v_2$;', 'backward filters stay (one per join key);', 'a filter that keeps more than 35% of its', 'source is abandoned while it is built']):
        f.text(ox + 2, ty + i * 8, s, fs=5.5, ha='left', color=INK)
    # (c) RPT-G
    ox = 256
    _arrow(f, ox, 18, pos, 0, 1, BLUE, side=1, num=1)
    _arrow(f, ox, 18, pos, 3, 1, BLUE, side=1, num=2, dash=(2, 1.2))
    _arrow(f, ox, 18, pos, 1, 0, BLUE, side=1, num=3, dash=(2, 1.2))
    lines = [(f'1  push $v_0 \\to v_1$: {k(e["D0"])} entries', BLUE),
             (f'2  pull $v_3 \\to v_1$: $\\leq$ {k(e["D1"])}, not push {k(e["D3"])}', BLUE),
             ('3  pull $v_1 \\to v_0$: the join starts at $v_0$', BLUE),
             ('dropped: $v_2 \\to v_1$ (no sources),', MUT), ('$v_1 \\to v_2$, $v_1 \\to v_3$ (no consumer)', MUT)]
    for i, (s, col) in enumerate(lines):
        f.text(ox + 2, ty + i * 8, s, fs=5.4, ha='left', color=col)
    # (d) cycle
    ox = 384
    _arrow(f, ox, 18, pos, 0, 1, BLUE, side=1, num=1)
    _arrow(f, ox, 18, pos, 3, 1, BLUE, side=1, num=2)
    _arrow(f, ox, 18, pos, 0, 3, GREEN, side=1, num=3)
    _arrow(f, ox, 18, pos, 3, 0, GREEN, side=1, num=4)
    _arrow(f, ox, 18, pos, 1, 0, BLUE, side=1, num=5)
    for i, s in enumerate(['forward pass on the tree (1, 2), then', 'both ways along the closing edge', '$v_0$–$v_3$ (3, 4), then the backward pass (5);', 'the join checks $v_0$–$v_3$ by intersection']):
        f.text(ox + 2, ty + i * 8, s, fs=5.5, ha='left', color=INK)
    for ox in (124, 252, 380):
        f.line([(ox, 4), (ox, 146)], color=GRID, sw=0.6)
    f.save(out('fig_plans'))


# ============================================================ benefit: degree-weighted survival and cap
def fig_benefit():
    e = EX['lj_survival']
    meas = EX.get('lj_push_out', {})
    f = Fig(241, 130)
    # (a) survival by degree on LiveJournal
    f.text(4, 6, '(a) who survives a push', fs=6.6, ha='left', bold=True)
    hist = [h for h in e['hist'] if h['bin'] <= 14]
    px, py, pw, ph = 30, 16, 108, 54
    p = Plot(f, px, py, pw, ph, (-0.5, len(hist) - 0.5), (0, 1))
    bwid = pw / len(hist)
    for i, h in enumerate(hist):
        X = p.X(i)
        f.rect(X - bwid * 0.42, p.Y(h['count_share']), bwid * 0.4, p.Y(0) - p.Y(h['count_share']), fill='#c9c9c9', stroke='none')
        f.rect(X + 0.02 * bwid, p.Y(h['degsum_share']), bwid * 0.4, p.Y(0) - p.Y(h['degsum_share']), fill=BLUE, stroke='none')
    p.curve(list(range(len(hist))), [h['survival'] for h in hist], ORANGE, sw=1.1)
    p.frame()
    p.yticks([0, 0.5, 1], ['0', '.5', '1'], fs=5.6)
    p.xticks([0, 3, 6, 9, 12], ['1', '8', '64', '512', '4K'], fs=5.6, grid=False)
    p.xlabel('degree $d$', fs=6, dy=10)
    legend(f, 6, 90, [('vertices', '#c9c9c9', 'bar', None), ('degree sum', BLUE, 'bar', None),
                       ('survival', ORANGE, None, None)], fs=5.5, row=8, sample=8, col_w=[0, 44, 98], ncol=3)
    f.text(6, 100, 'a 10% uniform set pushes into $V$: $\\rho$ = 0.1', fs=5.6, ha='left', color=INK)
    if meas:
        f.text(6, 109, f'measured: {100 * meas["vertices"]:.0f}% of the vertices survive,', fs=5.6, ha='left', color=INK)
        f.text(6, 117, f'{100 * meas["degsum_same"]:.0f}% of the degree sum', fs=5.6, ha='left', color=INK)
    # (b) cap: levels after the entering step
    ox = 152
    f.text(ox, 6, '(b) what is saved', fs=6.6, ha='left', bold=True)
    steps = ['$v_0$', '$v_1$', '$v_2$', '$v_3$']
    y = 22
    for i, v in enumerate(steps):
        Y = y + i * 20
        f.ellipse(ox + 10, Y, 6.5, 6.5, fill='#d9e7f8' if i in (0, 3) else '#ffffff', stroke=INK, sw=0.7, label=v, fs=6.2)
        if i < 3:
            f.line([(ox + 10, Y + 7), (ox + 10, Y + 13)], color=INK, sw=0.7, arrow='end', head=3)
    f.text(ox + 20, 22, f'scan lists of $B_0$: {k(EX["D0"])}', fs=5.5, ha='left', color=INK)
    f.text(ox + 20, 42, 'probe $B_1$', fs=5.5, ha='left', color=INK)
    f.rect(ox + 18, 54, 70, 36, fill='#eef4fc', stroke=BLUE, sw=0.6, r=2, dash=(2, 1.5))
    f.text(ox + 20, 62, 'scan lists of each $v_1$', fs=5.5, ha='left', color=BLUE)
    f.text(ox + 20, 70, 'for $v_2$, then $v_3$:', fs=5.5, ha='left', color=BLUE)
    f.text(ox + 20, 78, 'cap($v_1$) = these scans;', fs=5.5, ha='left', color=BLUE)
    f.text(ox + 20, 86, 'benefit = (1$-$s)$\\cdot$cap', fs=5.5, ha='left', color=BLUE)
    f.text(ox, 100, 'the entering scan is paid', fs=5.5, ha='left', color=MUT)
    f.text(ox, 108, 'whatever $B_1$ holds; a transfer', fs=5.5, ha='left', color=MUT)
    f.text(ox, 116, 'into $v_1$ only shortens', fs=5.5, ha='left', color=MUT)
    f.text(ox, 124, 'the levels after it', fs=5.5, ha='left', color=MUT)
    f.save(out('fig_benefit'))


# ============================================================ a pull with the abort rule
def fig_pull():
    e = EX['pull_into_10pct']
    f = Fig(241, 104)
    f.text(4, 6, f'two pulls into {e["target"]:,} DBLP vertices, in random word order', fs=6.5, ha='left', bold=True)
    px, py, pw, ph = 30, 16, 196, 60
    p = Plot(f, px, py, pw, ph, (1, e['target']), (0, 1), xlog=True)
    p.frame()
    p.yticks([0, 0.35, 0.7, 1], ['0', '.35', '.7', '1'], fs=5.6)
    p.xticks([1, 10, 100, 1000, 10000], ['1', '10', '100', '1K', '10K'], fs=5.6, grid=False)
    p.xlabel('members visited', fs=6, dy=10)
    p.ylabel('running survival', fs=6, dx=22)
    p.hline(0.35, color=MUT)
    f.text(px + 2, p.Y(0.35) + 3, '$\\tau_{sel}$ = 0.35', fs=5.4, ha='left', va='top', color=MUT)
    p.vline(2000, color=MUT)
    f.text(p.X(2000) + 2, py + 2, '$\\gamma$ = 2,000', fs=5.4, ha='left', va='top', color=MUT)
    a, b = e['from_B0'], e['from_30pct']
    p.curve(a['k'], a['rate'], BLUE, sw=1.2)
    kb = [x for x in b['k'] if x <= 2000] + [2000]
    rb = [r for x, r in zip(b['k'], b['rate']) if x <= 2000] + [b['rate'][min(range(len(b['k'])), key=lambda i: abs(b['k'][i] - 2000))]]
    p.curve(kb, rb, ORANGE, sw=1.2)
    f.marker(p.X(2000), p.Y(rb[-1]), 'o', 4.5, fill=ORANGE, stroke='#ffffff')
    f.text(p.X(2000) - 5, p.Y(0.61), f'abort after 2,000 members: {100 * rb[-1]:.0f}% survive,', fs=5.4, ha='right', va='top', color=ORANGE)
    f.text(p.X(2000) - 5, p.Y(0.51), f'the other {k(e["D_target"])} list entries are never read', fs=5.4, ha='right', va='top', color=ORANGE)
    f.text(p.X(e['target']) - 2, p.Y(a['final']) - 3, f'completes: {100 * a["final"]:.1f}% survive', fs=5.4, ha='right', va='bottom', color=BLUE)
    legend(f, 30, 97, [(f'from $B_0$ ({k(EX["D0"])} entries)', BLUE, None, None),
                       (f'from a 30% set ({k(e["D_30pct"])} entries)', ORANGE, None, None)],
           fs=5.6, row=8, sample=10, col_w=[0, 100], ncol=2)
    f.save(out('fig_pull'))


# ============================================================ the two ski rentals
def fig_rental():
    e = EX['count']
    f = Fig(241, 118)
    # (a) filtered adjacency lists
    f.text(4, 6, '(a) filtered adjacency lists', fs=6.6, ha='left', bold=True)
    px, py, pw, ph = 24, 16, 86, 50
    p = Plot(f, px, py, pw, ph, (0, 10), (0, 10))
    p.frame()
    p.curve([0, 10], [0, 10], GREY, sw=1.0, dash=(2, 1.5))
    p.curve([0, 4, 4, 10], [0, 4, 6, 6.6], BLUE, sw=1.2)
    p.hline(2, color=MUT)
    f.text(px + 2, p.Y(2) - 2, 'build cost $b$', fs=5.2, ha='left', va='bottom', color=MUT)
    f.text(p.X(4.4), p.Y(4.4), 'at $b$ scanned: build', fs=5.2, ha='left', va='top', color=BLUE)
    f.text(p.X(10) - 1, p.Y(6.6) + 2, 'then survivors only', fs=5.2, ha='right', va='top', color=BLUE)
    f.text(p.X(6.4), p.Y(7.6), 'unfiltered', fs=5.2, ha='right', va='bottom', color=GREY)
    p.xlabel('join progress', fs=5.8, dy=5)
    p.ylabel('entries scanned', fs=5.8, dx=10)
    f.text(4, py + ph + 16, 'a step that has scanned $b$ entries builds the', fs=5.4, ha='left', color=INK)
    f.text(4, py + ph + 24, 'filtered lists: at most twice the better choice', fs=5.4, ha='left', color=INK)
    f.text(4, py + ph + 32, 'whatever the estimate said', fs=5.4, ha='left', color=INK)
    # (b) counting
    ox = 124
    f.text(ox, 6, '(b) counting against enumeration', fs=6.6, ha='left', bold=True)
    px, py, pw, ph = ox + 22, 16, 88, 50
    p = Plot(f, px, py, pw, ph, (0, 10), (0, 10))
    p.frame()
    p.curve([0, 10], [0, 10], GREY, sw=1.0, dash=(2, 1.5))
    p.hline(3, color=ORANGE, dash=None, sw=1.0)
    p.curve([0, 3, 3, 3.3], [0, 3, 6, 6], BLUE, sw=1.2)
    f.text(p.X(10) - 1, p.Y(3) - 2, 'count: $C$, flat', fs=5.2, ha='right', va='bottom', color=ORANGE)
    f.text(p.X(3.6), p.Y(6) - 2, 'switch at $C$: $\\leq$ 2$C$', fs=5.2, ha='left', va='bottom', color=BLUE)
    f.text(p.X(10) - 1, p.Y(9.4) + 1, 'enumerate', fs=5.2, ha='right', va='top', color=GREY)
    p.xlabel('output', fs=5.8, dy=5)
    p.ylabel('work', fs=5.8, dx=10)
    f.text(ox, py + ph + 16, f'example: $C$ = {k(e["C"])} entries against {k(e["E_scanned"])}', fs=5.4, ha='left', color=INK)
    f.text(ox, py + ph + 24, f'scanned for {k(e["output"])} matches; an estimate above', fs=5.4, ha='left', color=INK)
    f.text(ox, py + ph + 32, '$\\phi C$ counts at once, else the join switches at $C$', fs=5.4, ha='left', color=INK)
    f.save(out('fig_rental'))


# ============================================================ counting on the running example
def fig_counting():
    e = EX['count']
    ex = EX
    f = Fig(241, 124)
    f.text(4, 6, 'counting the example without enumeration', fs=6.6, ha='left', bold=True)
    pos = {1: (58, 40), 0: (22, 78), 2: (58, 78), 3: (94, 78)}
    fills = {0: '#d9e7f8', 1: '#ffffff', 2: '#ffffff', 3: '#d9e7f8'}
    for c in (0, 2, 3):
        f.line([pos[c], pos[1]], color=INK, sw=0.7, arrow='end', head=3)
    for v, (x, y) in pos.items():
        f.ellipse(x, y, 7, 7, fill=fills[v], stroke=INK, sw=0.7, label=f'$v_{v}$', fs=6.5)
    f.text(22, 90, '$c_0$ = 1', fs=5.4, color=INK)
    f.text(22, 97, f'on {ex["B0"]}', fs=5.1, color=MUT)
    f.text(58, 90, 'deg($v$)', fs=5.4, color=INK)
    f.text(58, 97, 'unvisited', fs=5.1, color=MUT)
    f.text(94, 90, '$c_3$ = 1', fs=5.4, color=INK)
    f.text(94, 97, f'on {ex["B3"]:,}', fs=5.1, color=MUT)
    f.text(4, 20, '$c_1(v) = |N(v)\\cap B_0| \\cdot \\mathrm{deg}(v) \\cdot |N(v)\\cap B_3|$', fs=5.7, ha='left', color=INK)
    f.text(4, 120, f'root: $\\Sigma_{{v \\in B_1}}\\, c_1(v)$ = {e["total"]:,} matches', fs=5.7, ha='left', color=INK)
    # the three largest contributors
    ox = 122
    f.text(ox, 20, f'three of the {e["members_B1"]:,} members of $B_1$:', fs=5.6, ha='left', color=INK)
    f.text(ox, 31, '$v$', fs=5.5, ha='left', color=MUT)
    for j, h in enumerate(['in $B_0$', 'deg', 'in $B_3$', '$c_1(v)$']):
        f.text(ox + 38 + j * 26, 31, h, fs=5.5, ha='right', color=MUT)
    f.line([(ox, 35), (ox + 112, 35)], color=GRID, sw=0.6)
    for i, r in enumerate(e['examples']):
        Y = 42 + i * 9
        f.text(ox, Y, f'{r["v"]:,}', fs=5.5, ha='left')
        for j, key in enumerate(['in_B0', 'deg', 'in_B3', 'c']):
            f.text(ox + 38 + j * 26, Y, f'{r[key]:,}', fs=5.5, ha='right')
    f.text(ox, 78, f'cost $C$ = {k(e["C"])} entries: the lists of $B_0$', fs=5.5, ha='left', color=INK)
    f.text(ox, 86, f'(pushed) and of $B_1$ (pulled from $B_3$);', fs=5.5, ha='left', color=INK)
    f.text(ox, 97, f'enumeration scans {k(e["E_scanned"])} entries', fs=5.5, ha='left', color=INK)
    f.text(ox, 105, f'to produce {k(e["output"])} matches', fs=5.5, ha='left', color=INK)
    f.save(out('fig_counting'))


# ============================================================ host plan: rows a transfer removes
def fig_hostplan():
    h = EX['host_rows']
    ex = EX
    f = Fig(241, 114)
    f.text(4, 6, 'a host join tree of the example: rows per node, before $\\to$ after $v_3 \\to v_1$', fs=6.3, ha='left', bold=True)
    nodes = {'root': (120, 22), 'j01': (60, 48), 'j13': (150, 48), 'E12': (203, 48),
             'E01': (34, 76), 'V0': (86, 76), 'E13': (124, 76), 'V3': (176, 76)}
    labels = {'root': f'$\\bowtie_{{v_1}}$  {k(h["E01_V0_E13_V3"])} $\\to$ {k(h["after_transfer"])}',
              'j01': f'$E_{{01}} \\bowtie V_0$  {k(h["E01_V0"])} $\\to$ {k(h["E01_V0_after_transfer"])}',
              'j13': f'$E_{{13}} \\bowtie V_3$  {k(h["E13_V3_alone"])}', 'E12': f'$E_{{12}}$  {k(h["E12_alone"])}',
              'E01': f'$E_{{01}}$  {k(ex["m"])}', 'V0': f'$V_0$  {ex["B0"]}', 'E13': f'$E_{{13}}$  {k(ex["m"])}', 'V3': f'$V_3$  {ex["B3"]:,}'}
    hi = {'j01'}
    for a, b in [('root', 'j01'), ('root', 'j13'), ('root', 'E12'), ('j01', 'E01'), ('j01', 'V0'), ('j13', 'E13'), ('j13', 'V3')]:
        f.line([nodes[a], nodes[b]], color=INK, sw=0.6)
    for key, (x, y) in nodes.items():
        w = 58 if key in ('root', 'j01') else 44
        f.rect(x - w / 2, y - 7, w, 14, fill='#eef4fc' if key in hi else '#f7f7f7', stroke=BLUE if key in hi else '#b5b5b5',
               sw=0.7, r=2, label=labels[key], fs=5.4)
    removed = h['E01_V0'] - h['E01_V0_after_transfer']
    f.text(4, 94, f'benefit = rows removed below the root from nodes with $v_1$: {removed} of {k(h["E01_V0"])};', fs=5.4, ha='left', color=INK)
    f.text(4, 102, f'cost = a pull over $B_1$, up to {k(ex["D1"])} entries: not admitted. The root is output,', fs=5.4, ha='left', color=INK)
    f.text(4, 110, f'and $E_{{13}} \\bowtie V_3$ joins $v_1$ through the transfer\'s own edge and keeps its rows', fs=5.4, ha='left', color=MUT)
    f.save(out('fig_hostplan'))


if __name__ == '__main__':
    for fn in (fig_breakdown, fig_cost, fig_plans, fig_benefit, fig_pull, fig_rental, fig_counting, fig_hostplan):
        fn()
        print('wrote', fn.__name__)

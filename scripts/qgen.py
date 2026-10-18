#!/usr/bin/env python
"""Q-GEN: random tree-pattern workload generator with controlled predicate selectivity.

Shapes: path (k=2..5; --shape path: k up to --kmax), star (k=3..5), random tree (k=4..6); with --cyclic: triangle, square, diamond,
tailed triangle, pentagon, house, triangle with two tails. Every query has >= 1 predicate.
Predicate types: pu<s (uniform property, selectivity exactly s), pd<s (top-s hubs),
label=L (ground-truth community, structurally correlated).
Writes the query file and a side CSV with per-query metadata for analysis.
"""
import argparse, math, os, random
import numpy as np


CYCLIC = {  # name: (k, undirected edge list)
    'triangle': (3, [(0, 1), (1, 2), (2, 0)]),
    'square': (4, [(0, 1), (1, 2), (2, 3), (3, 0)]),
    'diamond': (4, [(0, 1), (1, 2), (2, 0), (1, 3), (3, 2)]),
    'tailed_triangle': (4, [(0, 1), (1, 2), (2, 0), (2, 3)]),
    'pentagon': (5, [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)]),
    'house': (5, [(0, 1), (1, 2), (2, 3), (3, 0), (2, 4), (4, 3)]),
    'triangle_two_tails': (5, [(0, 1), (1, 2), (2, 0), (0, 3), (2, 4)]),
}


def gen_cyclic(rng):
    shape = rng.choice(sorted(CYCLIC))
    k, edges = CYCLIC[shape]
    perm = list(range(k)); rng.shuffle(perm)           # random vertex numbering
    edges = [(perm[a], perm[b]) for a, b in edges]
    edges = [(b, a) if rng.random() < 0.5 else (a, b) for a, b in edges]
    return shape, k, edges


def gen_shape(rng, kmin, kmax, only=None):
    shape = only or rng.choices(['path', 'star', 'tree'], weights=[0.4, 0.3, 0.3])[0]
    if shape == 'path':
        k = rng.randint(max(kmin, 2), kmax if only else min(kmax, 5))   # --shape path: chains of any length
        edges = [(i, i + 1) for i in range(k - 1)]
    elif shape == 'star':
        k = rng.randint(max(kmin, 3), min(kmax, 5))
        edges = [(0, i) for i in range(1, k)]
    else:
        k = rng.randint(max(kmin, 4), kmax)
        edges = [(rng.randrange(i), i) for i in range(1, k)]
    # random orientation of every pattern edge
    edges = [(b, a) if rng.random() < 0.5 else (a, b) for a, b in edges]
    return shape, k, edges


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--graph', required=True, help='binary graph dir (for n and label counts)')
    ap.add_argument('--n', type=int, default=5000)
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--out', required=True)
    ap.add_argument('--kmin', type=int, default=2)
    ap.add_argument('--kmax', type=int, default=6)
    ap.add_argument('--p-pred', type=float, default=0.5, help='probability that a vertex carries a predicate')
    ap.add_argument('--sel-min', type=float, default=1e-5)
    ap.add_argument('--sel-max', type=float, default=1.0)
    ap.add_argument('--w-pu', type=float, default=0.7)
    ap.add_argument('--w-pd', type=float, default=0.15)
    ap.add_argument('--w-label', type=float, default=0.15)
    ap.add_argument('--cyclic', action='store_true', help='cyclic shapes only (triangle, square, diamond, ...)')
    ap.add_argument('--shape', default=None, choices=['path', 'star', 'tree'], help='one shape only (path: k up to --kmax)')
    a = ap.parse_args()

    n = int(open(os.path.join(a.graph, 'meta.txt')).read().split()[0])
    label = np.fromfile(os.path.join(a.graph, 'label.bin'), dtype=np.int32)
    lab_sizes = np.bincount(label[label >= 0]) if (label >= 0).any() else np.array([])
    labels = np.nonzero(lab_sizes)[0]
    rng = random.Random(a.seed)
    weights = [a.w_pu, a.w_pd, a.w_label if len(labels) else 0.0]

    meta = open(a.out + '.meta.csv', 'w')
    meta.write('qid,shape,k,npred,min_sel,max_sel,has_pd,has_label\n')
    with open(a.out, 'w') as f:
        for qid in range(1, a.n + 1):
            shape, k, edges = gen_cyclic(rng) if a.cyclic else gen_shape(rng, a.kmin, a.kmax, a.shape)
            pred_vars = [x for x in range(k) if rng.random() < a.p_pred]
            if not pred_vars:
                pred_vars = [rng.randrange(k)]
            preds, sels, has_pd, has_label = [], [], 0, 0
            for x in pred_vars:
                t = rng.choices(['pu', 'pd', 'label'], weights=weights)[0]
                if t == 'pu':
                    s = math.exp(rng.uniform(math.log(a.sel_min), math.log(a.sel_max)))
                    preds.append(f'{x}:pu<{s:.6g}'); sels.append(s)
                elif t == 'pd':
                    s = math.exp(rng.uniform(math.log(a.sel_min), math.log(min(a.sel_max, 0.1))))
                    preds.append(f'{x}:pd<{s:.6g}'); sels.append(s); has_pd = 1
                else:
                    L = int(rng.choice(labels))
                    preds.append(f'{x}:label={L}'); sels.append(lab_sizes[L] / n); has_label = 1
            f.write(f'id={qid} k={k} edges={",".join(f"{u}>{v}" for u, v in edges)} preds={";".join(preds)}\n')
            meta.write(f'{qid},{shape},{k},{len(preds)},{min(sels):.3g},{max(sels):.3g},{has_pd},{has_label}\n')
    meta.close()
    print('wrote', a.out, 'and', a.out + '.meta.csv')


if __name__ == '__main__':
    main()

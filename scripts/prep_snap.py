#!/usr/bin/env python
"""Convert a SNAP edge list into the RPT-G binary graph format.

Output directory layout (all little-endian):
  meta.txt      n m directed(0/1)
  out_off.bin   uint64[n+1]   CSR offsets (forward adjacency, sorted by src then dst)
  out_nbr.bin   uint32[m]
  in_off.bin    uint64[n+1]   CSC offsets (reverse adjacency); for undirected graphs identical to CSR
  in_nbr.bin    uint32[m]
  pu.bin        float32[n]    uniform(0,1) property           -> "pu < s" has selectivity s
  pd.bin        float32[n]    degree-rank property             -> "pd < s" selects the top-s hubs
  label.bin     int32[n]      ground-truth community label (-1 = none), from the .cmty file if given

Vertex ids are remapped to a dense [0, n) range; edges are deduplicated and self-loops kept as-is.
"""
import argparse, gzip, os, sys, time
import numpy as np
import pandas as pd


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def read_edges(path):
    log('reading', path)
    df = pd.read_csv(path, sep=r'\s+', comment='#', header=None, names=['s', 'd'],
                     dtype={'s': np.int64, 'd': np.int64}, engine='c')
    return df['s'].to_numpy(), df['d'].to_numpy()


def build_csr(src, dst, n):
    order = np.lexsort((dst, src))
    src, dst = src[order], dst[order]
    keep = np.ones(len(src), dtype=bool)
    keep[1:] = (src[1:] != src[:-1]) | (dst[1:] != dst[:-1])
    src, dst = src[keep], dst[keep]
    off = np.zeros(n + 1, dtype=np.uint64)
    off[1:] = np.cumsum(np.bincount(src, minlength=n))
    return off, dst.astype(np.uint32), src, dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('edges')
    ap.add_argument('out')
    ap.add_argument('--undirected', action='store_true')
    ap.add_argument('--cmty', default=None, help='SNAP .all.cmty.txt(.gz) file for labels')
    ap.add_argument('--max-labels', type=int, default=5000)
    ap.add_argument('--seed', type=int, default=42)
    a = ap.parse_args()

    s, d = read_edges(a.edges)
    ids = np.unique(np.concatenate([s, d]))
    n = len(ids)
    log(f'raw edges={len(s):,} distinct vertices={n:,} (max raw id {ids.max():,})')
    s = np.searchsorted(ids, s).astype(np.int64)
    d = np.searchsorted(ids, d).astype(np.int64)
    if a.undirected:
        s, d = np.concatenate([s, d]), np.concatenate([d, s])

    out_off, out_nbr, s, d = build_csr(s, d, n)
    m = len(out_nbr)
    log(f'dense edges m={m:,} (directed={not a.undirected})')
    if a.undirected:
        in_off, in_nbr = out_off, out_nbr
    else:
        in_off, in_nbr, _, _ = build_csr(d, s, n)

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, 'meta.txt'), 'w') as f:
        f.write(f'{n} {m} {0 if a.undirected else 1}\n')
    out_off.tofile(os.path.join(a.out, 'out_off.bin'))
    out_nbr.tofile(os.path.join(a.out, 'out_nbr.bin'))
    in_off.tofile(os.path.join(a.out, 'in_off.bin'))
    in_nbr.tofile(os.path.join(a.out, 'in_nbr.bin'))

    rng = np.random.default_rng(a.seed)
    pu = rng.random(n, dtype=np.float32)
    deg = (np.diff(out_off) + np.diff(in_off)).astype(np.int64)
    # random tie-break so equal-degree vertices are not ordered by id
    order = np.lexsort((rng.random(n), -deg))
    pdeg = np.empty(n, dtype=np.float32)
    pdeg[order] = (np.arange(n) / n).astype(np.float32)
    pu.tofile(os.path.join(a.out, 'pu.bin'))
    pdeg.tofile(os.path.join(a.out, 'pd.bin'))

    label = np.full(n, -1, dtype=np.int32)
    if a.cmty:
        log('reading communities', a.cmty)
        opener = gzip.open if a.cmty.endswith('.gz') else open
        comms = []
        with opener(a.cmty, 'rt') as f:
            for line in f:
                parts = line.split()
                if parts:
                    comms.append(np.array(parts, dtype=np.int64))
        comms.sort(key=len, reverse=True)
        comms = comms[:a.max_labels]
        # assign each vertex the largest community it belongs to
        for li, c in enumerate(comms):
            v = np.searchsorted(ids, c)
            v = v[(v < n) & (ids[np.minimum(v, n - 1)] == c)]
            un = label[v] < 0
            label[v[un]] = li
        log(f'labels: {len(comms)} communities, {np.sum(label >= 0):,} labelled vertices, '
            f'largest={len(comms[0]):,} smallest kept={len(comms[-1]):,}')
    label.tofile(os.path.join(a.out, 'label.bin'))

    log(f'degree: max={deg.max():,} mean={deg.mean():.2f} p99={np.percentile(deg, 99):.0f}')
    log('done ->', a.out)


if __name__ == '__main__':
    main()

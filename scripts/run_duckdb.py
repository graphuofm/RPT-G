#!/usr/bin/env python
"""M1 host baseline: run RPT-G query files as SQL self-joins in DuckDB.

Loads the binary graph directory into an in-memory DuckDB database (tables V(id,pu,pd,label) and
E(src,dst)), translates every query line into SELECT count(*) over E self-joins, and records the
wall time per query. Timeouts are enforced with conn.interrupt().
"""
import argparse, os, sys, threading, time
import numpy as np
import duckdb


def load_graph(con, d):
    n, m, directed = open(os.path.join(d, 'meta.txt')).read().split()
    n, m = int(n), int(m)
    out_off = np.fromfile(os.path.join(d, 'out_off.bin'), dtype=np.uint64)
    out_nbr = np.fromfile(os.path.join(d, 'out_nbr.bin'), dtype=np.uint32)
    src = np.repeat(np.arange(n, dtype=np.int32), np.diff(out_off).astype(np.int64))
    dst = out_nbr.astype(np.int32)
    pu = np.fromfile(os.path.join(d, 'pu.bin'), dtype=np.float32)
    pd = np.fromfile(os.path.join(d, 'pd.bin'), dtype=np.float32)
    label = np.fromfile(os.path.join(d, 'label.bin'), dtype=np.int32)
    import pandas
    vdf = pandas.DataFrame({'id': np.arange(n, dtype=np.int32), 'pu': pu, 'pd': pd, 'label': label})
    edf = pandas.DataFrame({'src': src, 'dst': dst})
    con.execute('CREATE TABLE V AS SELECT * FROM vdf ORDER BY id')
    con.execute('CREATE TABLE E AS SELECT * FROM edf ORDER BY src, dst')
    return n, m


def parse(line):
    kv = dict(tok.split('=', 1) for tok in line.split())
    k = int(kv['k'])
    edges = [tuple(map(int, e.split('>'))) for e in kv['edges'].split(',')]
    preds = {}
    for pr in kv.get('preds', '').split(';'):
        if not pr:
            continue
        x, body = pr.split(':', 1)
        preds.setdefault(int(x), []).append(body)
    return int(kv['id']), k, edges, preds


def to_sql(k, edges, preds):
    """Each pattern vertex x is a column reference; vertex x is anchored to the first edge table
    that mentions it. Predicates are applied through a join with V (as a real host would do)."""
    tabs, conds, anchor = [], [], {}
    for i, (a, b) in enumerate(edges):
        t = f'e{i}'
        tabs.append(f'E {t}')
        for x, col in ((a, 'src'), (b, 'dst')):
            ref = f'{t}.{col}'
            if x in anchor:
                conds.append(f'{ref} = {anchor[x]}')
            else:
                anchor[x] = ref
    for x, ps in preds.items():
        t = f'v{x}'
        tabs.append(f'V {t}')
        conds.append(f'{t}.id = {anchor[x]}')
        for body in ps:
            if body.startswith('pu<'):
                conds.append(f'{t}.pu < {float(body[3:])!r}')
            elif body.startswith('pd<'):
                conds.append(f'{t}.pd < {float(body[3:])!r}')
            elif body.startswith('label='):
                conds.append(f'{t}.label = {int(body[6:])}')
    where = ' AND '.join(conds) if conds else 'TRUE'
    return f'SELECT count(*) FROM {", ".join(tabs)} WHERE {where}'


def to_sql_ordered(k, edges, preds, order):
    """The same query with its join order spelled out as explicit JOINs (left-deep, in the given order), for
    hosts that keep a syntactic order (PostgreSQL with join_collapse_limit=1, DuckDB with the join-order
    optimizer disabled). order = 'start;u>w;...' (results/*_robust.orders.csv): start vertex, then the pattern
    edges in join order, each written as in the query; one endpoint of each is already bound. Edges that close a cycle are joined as soon as both endpoints are bound; the V copy of
    a predicate vertex is joined right after the vertex is bound (as a graph engine filters on binding)."""
    parts = order.split(';')
    start = int(parts[0])
    steps = [tuple(map(int, p.split('>'))) for p in parts[1:] if p]
    col = lambda i, x: f'e{i}.src' if edges[i][0] == x else f'e{i}.dst'
    anchor, used, sql, bound = {}, set(), [], set()

    def pred_conds(x, t):
        out = []
        for body in preds.get(x, []):
            if body.startswith('pu<'):
                out.append(f'{t}.pu < {float(body[3:])!r}')
            elif body.startswith('pd<'):
                out.append(f'{t}.pd < {float(body[3:])!r}')
            elif body.startswith('label='):
                out.append(f'{t}.label = {int(body[6:])}')
        return out

    def bind_vertex(x):
        bound.add(x)
        if x in preds and x != start:
            t = f'v{x}'
            sql.append(f'JOIN V {t} ON ' + ' AND '.join([f'{t}.id = {anchor[x]}'] + pred_conds(x, t)))
        for i, (u, w) in enumerate(edges):      # edges closing a cycle
            if i not in used and u in bound and w in bound:
                used.add(i)
                sql.append(f'JOIN E e{i} ON e{i}.src = {anchor[u]} AND e{i}.dst = {anchor[w]}')

    if start in preds:
        sql.append(f'V v{start}')
        anchor[start] = f'v{start}.id'
        where_start = pred_conds(start, f'v{start}')
        bound.add(start)
    else:
        where_start = []
    for u0, w0 in steps:
        i = next(j for j, (u, w) in enumerate(edges) if j not in used and (u, w) == (u0, w0))
        used.add(i)
        if not sql:
            a, b = (start, w0 if u0 == start else u0)
        else:
            a, b = (u0, w0) if u0 in bound else (w0, u0)
        if not sql:                                  # the first edge copy starts the FROM clause
            sql.append(f'E e{i}')
            anchor[a] = col(i, a)
            bound.add(a)
        else:
            sql.append(f'JOIN E e{i} ON {col(i, a)} = {anchor[a]}')
        anchor[b] = col(i, b)
        bind_vertex(b)
    where = ' WHERE ' + ' AND '.join(where_start) if where_start else ''
    return f'SELECT count(*) FROM {" ".join(sql)}{where}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--graph', required=True)
    ap.add_argument('--queries', required=True)
    ap.add_argument('--out', default='-')
    ap.add_argument('--threads', type=int, default=8)
    ap.add_argument('--timeout', type=float, default=10.0)
    ap.add_argument('--reps', type=int, default=3)
    ap.add_argument('--warm', type=int, default=1)
    ap.add_argument('--print-sql', action='store_true')
    a = ap.parse_args()

    con = duckdb.connect()
    con.execute(f'SET threads={a.threads}')
    t0 = time.time()
    n, m = load_graph(con, a.graph)
    print(f'loaded n={n:,} m={m:,} in {time.time()-t0:.1f}s', file=sys.stderr)

    out = sys.stdout if a.out == '-' else open(a.out, 'w')
    out.write('qid,method,order,rep,status,total_ms,count\n')
    lines = [l.strip() for l in open(a.queries) if l.strip() and not l.startswith('#')]
    for li, line in enumerate(lines):
        qid, k, edges, preds = parse(line)
        sql = to_sql(k, edges, preds)
        if a.print_sql:
            print(qid, sql, file=sys.stderr)
        for r in range(-a.warm, a.reps):
            timer = threading.Timer(a.timeout, con.interrupt)
            timer.start()
            t1 = time.perf_counter()
            try:
                cnt = con.execute(sql).fetchone()[0]
                status = 'ok'
            except duckdb.InterruptException:
                cnt, status = -1, 'timeout'
            except Exception as e:  # noqa
                cnt, status = -1, 'error'
                print(qid, 'error', e, file=sys.stderr)
            ms = (time.perf_counter() - t1) * 1000
            timer.cancel()
            if r < 0 and status == 'ok':
                continue
            out.write(f'{qid},M1,0,{max(r,0)},{status},{ms:.4f},{cnt}\n')
            if status != 'ok':
                break
        if (li + 1) % 50 == 0:
            print(f'\r{li+1}/{len(lines)}', end='', file=sys.stderr)
            out.flush()
    print(f'\r{len(lines)}/{len(lines)} done', file=sys.stderr)
    if out is not sys.stdout:
        out.close()


if __name__ == '__main__':
    main()

#!/usr/bin/env python
"""Run an RPT-G query file in Kuzu as Cypher MATCH ... RETURN count(*).

Pattern edge a>b -> (va)-[:E]->(vb). Kuzu matches with walk semantics (repeated edges/vertices
allowed), i.e. homomorphisms, the same as the prototype and the SQL self-joins.
"""
import argparse, os, random, sys, time
import kuzu
sys.path.insert(0, os.path.dirname(__file__))
from run_duckdb import parse  # noqa: E402


def connected_orders(k, edges):
    """Every connected left-deep order of a tree pattern: (start vertex, pattern edges in join order,
    each reaching one new vertex from the vertices joined so far)."""
    result = []
    def extend(start, seen, order):
        if len(order) == len(edges):
            result.append((start, list(order)))
            return
        for i, (a, b) in enumerate(edges):
            if i not in order and (a in seen) != (b in seen):
                extend(start, seen | {a, b}, order + [i])
    for start in range(k):
        extend(start, {start}, [])
    return result


def random_orders(k, edges, n, rng):
    """n distinct connected left-deep orders drawn without replacement (all of them if there are fewer)."""
    orders = connected_orders(k, edges)
    return orders if len(orders) <= n else rng.sample(orders, n)


def join_hint(edges, start, order):
    """Kuzu HINT join tree for a left-deep order: ((start JOIN e_i) JOIN v_new) ..."""
    expr, seen = f'v{start}', {start}
    for i in order:
        a, b = edges[i]
        new = [v for v in (a, b) if v not in seen]
        expr = f'({expr} JOIN e{i})'
        for v in new:
            expr = f'({expr} JOIN v{v})'
        seen.update((a, b))
    return expr


def to_cypher(k, edges, preds, order=None):
    """order = (start vertex, [edge indices]) forces that join order through a HINT clause."""
    parts = [f'(v{a}:V)-[e{i}:E]->(v{b}:V)' if order else f'(v{a}:V)-[:E]->(v{b}:V)'
             for i, (a, b) in enumerate(edges)]
    conds = []
    for x, ps in preds.items():
        for body in ps:
            if body.startswith('pu<'):
                conds.append(f'v{x}.pu < {float(body[3:])!r}')
            elif body.startswith('pd<'):
                conds.append(f'v{x}.pd < {float(body[3:])!r}')
            elif body.startswith('label='):
                conds.append(f'v{x}.label = {int(body[6:])}')
    where = (' WHERE ' + ' AND '.join(conds)) if conds else ''
    hint = f' HINT {join_hint(edges, *order)}' if order else ''
    return f'MATCH {", ".join(parts)}{where}{hint} RETURN count(*)'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True)
    ap.add_argument('--queries', required=True)
    ap.add_argument('--out', default='-')
    ap.add_argument('--method', default='K1')
    ap.add_argument('--threads', type=int, default=8)
    ap.add_argument('--timeout', type=float, default=10.0)
    ap.add_argument('--reps', type=int, default=3)
    ap.add_argument('--warm', type=int, default=1)
    ap.add_argument('--semi-mask', type=int, default=1)
    ap.add_argument('--configs', default=None, help='interleave several settings per rep: method:enable_semi_mask[:rptg_mode], e.g. "KNO:0:0,KSM:1:0,KSX:1:0:1.0:1,KR2:0:2:1.0" = method:semi_mask:rptg_mode[:beta[:exact_semi_mask]]; any further key=value field is an extra "CALL key=value" (e.g. KR2E:0:2:1.0:rptg_nbr_mask=false)')
    ap.add_argument('--buffer-gb', type=float, default=8.0, help='buffer pool size per process (Kuzu defaults to 80% of RAM)')
    ap.add_argument('--print-cypher', action='store_true')
    ap.add_argument('--random-orders', type=int, default=0, help='run every query under N distinct random connected left-deep join orders (HINT; all of them if fewer); order column = order index')
    ap.add_argument('--order-seed', type=int, default=0)
    ap.add_argument('--worker-start', type=int, default=None, help=argparse.SUPPRESS)
    a = ap.parse_args()

    if a.worker_start is None:
        return supervise(a)

    db = kuzu.Database(a.db, read_only=True, buffer_pool_size=int(a.buffer_gb * (1 << 30)))
    con = kuzu.Connection(db, num_threads=a.threads)
    con.set_query_timeout(int(a.timeout * 1000))
    def parse_cfg(c):
        extra = [x for x in c.split(':') if '=' in x]
        f = [x for x in c.split(':') if '=' not in x]
        return (f[0], int(f[1]), int(f[2]) if len(f) > 2 else None, float(f[3]) if len(f) > 3 else None, int(f[4]) if len(f) > 4 else None, extra)
    configs = [(a.method, a.semi_mask, None, None, None, [])] if not a.configs else [parse_cfg(c) for c in a.configs.split(',')]
    out = open(a.out, 'a')
    orders_log = open(a.out + '.orders', 'a') if a.random_orders else None   # qid,order,start;a>b;...
    lines = [l.strip() for l in open(a.queries) if l.strip() and not l.startswith('#')]
    for li, line in enumerate(lines):
        if li < a.worker_start:
            continue
        poisoned = False
        if ' cypher=' in line:                    # a ready Cypher query: "id=N cypher=MATCH ..."
            qid = int(line.split()[0].split('=', 1)[1])
            variants = [(0, line.split(' cypher=', 1)[1])]
            k = edges = preds = None
        else:
            qid, k, edges, preds = parse(line)
            variants = [(0, to_cypher(k, edges, preds))]
        if a.random_orders:
            variants = []
            for oi, (start, order) in enumerate(random_orders(k, edges, a.random_orders, random.Random(f'{a.order_seed}:{qid}'))):
                variants.append((oi, to_cypher(k, edges, preds, (start, order))))
                orders_log.write(f'{qid},{oi},{start};' + ';'.join(f'{edges[i][0]}>{edges[i][1]}' for i in order) + '\n')
            orders_log.flush()
        for oi, cy in variants:
            if a.print_cypher:
                print(qid, oi, cy, file=sys.stderr)
            dead = set()
            for r in range(-a.warm, a.reps):          # rep-major interleaving of the settings
                for method, sm, rg, beta, exact, extra in configs:
                    if method in dead:
                        continue
                    con.execute(f'CALL enable_semi_mask={"true" if sm else "false"}')
                    if exact is not None:
                        con.execute(f'CALL exact_semi_mask={"true" if exact else "false"}')
                    if rg is not None:
                        con.execute(f'CALL rptg_mode={rg}')
                        con.execute(f'CALL rptg_beta={beta if beta is not None else 1.0}')
                    for kv in extra:
                        con.execute(f'CALL {kv}')
                    t1 = time.perf_counter()
                    try:
                        cnt = con.execute(cy).get_next()[0]; status = 'ok'
                    except RuntimeError as e:
                        cnt = -1; status = 'timeout' if 'nterrupt' in str(e) or 'imeout' in str(e) else 'error'
                        if status == 'error':
                            print(qid, 'error', str(e)[:200], file=sys.stderr)
                            poisoned = poisoned or 'uffer' in str(e)
                    ms = (time.perf_counter() - t1) * 1000
                    if r < 0 and status == 'ok':
                        continue
                    out.write(f'{qid},{method},{oi},{max(r,0)},{status},{ms:.4f},{cnt}\n')
                    if status != 'ok':
                        dead.add(method)
        out.flush()
        open(a.out + '.progress', 'w').write(str(li))
        if (li + 1) % 50 == 0:
            print(f'\r{li+1}/{len(lines)}', end='', file=sys.stderr)
        if poisoned:          # Kuzu 0.11.3 is unstable after a buffer-manager exception: restart clean
            out.close(); sys.exit(3)
    out.close()


def supervise(a):
    """Run workers until the query file is exhausted; a worker that crashes (or exits after a
    buffer-manager error) is replaced by a fresh process starting at the next query."""
    import subprocess
    if a.out == '-':
        raise SystemExit('--out FILE is required')
    lines = [l for l in open(a.queries) if l.strip() and not l.startswith('#')]
    open(a.out, 'w').write('qid,method,order,rep,status,total_ms,count\n')
    if os.path.exists(a.out + '.progress'):
        os.remove(a.out + '.progress')
    start, restarts = 0, 0
    while start < len(lines):
        rc = subprocess.run([sys.executable, os.path.abspath(__file__)] + sys.argv[1:] + ['--worker-start', str(start)]).returncode
        done = int(open(a.out + '.progress').read()) if os.path.exists(a.out + '.progress') else start - 1
        if rc == 0:
            break
        restarts += 1
        if rc != 3:           # hard crash while running query done+1: record it and skip it
            crashed = max(done + 1, start)
            qid = lines[crashed].split()[0].split('=', 1)[1]
            open(a.out, 'a').write(f'{qid},CRASH,0,0,crash,-1,-1\n')
            print(f'\nworker crashed (rc={rc}) on query id={qid}; restarting after it', file=sys.stderr)
            start = crashed + 1
        else:
            start = done + 1
    print(f'\r{len(lines)}/{len(lines)} done ({restarts} worker restarts)', file=sys.stderr)


if __name__ == '__main__':
    main()

#!/usr/bin/env python
"""Run an RPT-G query file on a Neo4j server (cross-system reference).

Homomorphism semantics: one MATCH clause per pattern edge (Neo4j's relationship-uniqueness rule is
per clause), so counts agree with the prototype, DuckDB self-joins, and Kuzu. Timeout via the
server's db.transaction.timeout plus a client-side timeout on the transaction.
"""
import argparse, os, sys, time
from neo4j import GraphDatabase
from neo4j.exceptions import ClientError, TransientError, ServiceUnavailable
sys.path.insert(0, os.path.dirname(__file__))
from run_duckdb import parse  # noqa: E402


def to_cypher(k, edges, preds, mode='multi'):
    seen = set(); clauses = []
    def lab(x):
        if x in seen: return f'(v{x})'
        seen.add(x); return f'(v{x}:V)'
    if mode == 'multi':
        for a, b in edges:
            clauses.append(f'MATCH {lab(a)}-[:E]->{lab(b)}')
        match = ' '.join(clauses)
    else:
        parts = [f'({"v"+str(a)}:V)-[:E]->(v{b}:V)' for a, b in edges]
        match = 'MATCH ' + ', '.join(parts)
    conds = []
    for x, ps in preds.items():
        for body in ps:
            if body.startswith('pu<'): conds.append(f'v{x}.pu < {float(body[3:])!r}')
            elif body.startswith('pd<'): conds.append(f'v{x}.pd < {float(body[3:])!r}')
            elif body.startswith('label='): conds.append(f'v{x}.label = {int(body[6:])}')
    where = (' WHERE ' + ' AND '.join(conds)) if conds else ''
    return f'{match}{where} RETURN count(*) AS c'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--uri', default='bolt://127.0.0.1:7697')
    ap.add_argument('--database', default='dblp')
    ap.add_argument('--queries', required=True)
    ap.add_argument('--out', default='-')
    ap.add_argument('--method', default='N4J')
    ap.add_argument('--timeout', type=float, default=10.0)
    ap.add_argument('--reps', type=int, default=3)
    ap.add_argument('--warm', type=int, default=1)
    ap.add_argument('--print-cypher', action='store_true')
    ap.add_argument('--resume', action='store_true', help='append to --out, skipping queries already recorded')
    a = ap.parse_args()
    drv = GraphDatabase.driver(a.uri)
    done = set()
    if a.resume and a.out != '-' and os.path.exists(a.out):
        done = {int(l.split(',')[0]) for l in open(a.out) if l[:1].isdigit()}
        out = open(a.out, 'a')
    else:
        out = sys.stdout if a.out == '-' else open(a.out, 'w')
        out.write('qid,method,order,rep,status,total_ms,count,server_ms\n')
    lines = [l.strip() for l in open(a.queries) if l.strip() and not l.startswith('#')]
    for li, line in enumerate(lines):
        qid, k, edges, preds = parse(line); cy = to_cypher(k, edges, preds)
        if qid in done:
            continue
        if a.print_cypher: print(qid, cy, file=sys.stderr)
        for r in range(-a.warm, a.reps):
            t1 = time.perf_counter()
            try:
                from neo4j import unit_of_work
                @unit_of_work(timeout=a.timeout)
                def work(tx):
                    r = tx.run(cy); v = r.single()[0]; sm = r.consume()
                    return v, sm.result_available_after + sm.result_consumed_after
                for attempt in range(6):   # the server may stall under GC after huge results: reconnect
                    try:
                        with drv.session(database=a.database) as s:
                            res, server_ms = s.execute_read(work)
                        break
                    except (ServiceUnavailable, OSError) as e:
                        print(qid, 'connection lost, retry', attempt, str(e)[:80], file=sys.stderr, flush=True)
                        time.sleep(15 * (attempt + 1)); drv.close(); drv = GraphDatabase.driver(a.uri)
                else:
                    raise RuntimeError('server unreachable')
                cnt, status = res, 'ok'
            except (ClientError, TransientError) as e:
                cnt = -1; server_ms = -1; status = 'timeout' if 'timeout' in str(e).lower() or 'terminated' in str(e).lower() else 'error'
                if status == 'error': print(qid, 'error', str(e)[:160], file=sys.stderr)
            ms = (time.perf_counter() - t1) * 1000
            if r < 0 and status == 'ok': continue
            out.write(f'{qid},{a.method},0,{max(r,0)},{status},{ms:.4f},{cnt},{server_ms}\n')
            if status != 'ok': break
        out.flush()
        if (li + 1) % 50 == 0: print(f'\r{li+1}/{len(lines)}', end='', file=sys.stderr)
    print(f'\r{len(lines)}/{len(lines)} done', file=sys.stderr)
    drv.close()
    if out is not sys.stdout: out.close()


if __name__ == '__main__':
    main()

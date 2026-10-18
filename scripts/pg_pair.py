#!/usr/bin/env python
"""Run one (query, forced order) pair of the robustness workload in PostgreSQL 19, alternating pg_rptg
off/on, and print per-run times and pg_rptg's debug messages (diagnosis helper).
usage: pg_pair.py QID ORDER [--runs 5]   (ORDER -1: the planner's own order)"""
import argparse, os, sys, time
import psycopg
sys.path.insert(0, os.path.dirname(__file__))
from run_duckdb import parse, to_sql, to_sql_ordered  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('qid', type=int)
ap.add_argument('order', type=int)
ap.add_argument('--runs', type=int, default=5)
ap.add_argument('--queries', default='queries/dblp_robust100b.txt')
ap.add_argument('--orders', default='results/kuzu_dblp_robust.orders.csv')
ap.add_argument('--db', default='dblp')
ap.add_argument('--port', type=int, default=5439)
ap.add_argument('--explain', action='store_true')
a = ap.parse_args()
line = next(l.strip() for l in open(a.queries) if l.startswith(f'id={a.qid} '))
qid, k, edges, preds = parse(line)
if a.order >= 0:
    ostr = next(l.strip().split(',', 2)[2] for l in open(a.orders) if l.startswith(f'{a.qid},{a.order},'))
    sql, gucs = to_sql_ordered(k, edges, preds, ostr), ['join_collapse_limit=1']
else:
    sql, gucs = to_sql(k, edges, preds), []
for mode in ['off', 'on', 'off', 'on']:
    msgs = []
    conn = psycopg.connect(host=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data/pg19/cluster'), port=a.port, dbname=a.db, autocommit=True)
    conn.add_notice_handler(lambda d: msgs.append(d.message_primary))
    cur = conn.cursor()
    for g in gucs + ['client_min_messages=log', f'rptg.enabled={mode}', f"rptg.debug={'on' if mode == 'on' else 'off'}"]:
        n, v = g.split('=')
        cur.execute(f'SET {n} = {v}')
    ts = []
    for r in range(a.runs + 1):
        t0 = time.perf_counter()
        cur.execute(sql)
        cnt = cur.fetchone()[0]
        ts.append((time.perf_counter() - t0) * 1000)
    ts = ts[1:]
    print(f'rptg {mode:3s}: ' + ' '.join(f'{x:.1f}' for x in ts) + f'   median {sorted(ts)[len(ts) // 2]:.1f} ms  count {cnt}')
    if mode == 'on' and msgs:
        for m in msgs[-3:]:
            print('   ', m[:500])
    if a.explain and mode == 'on':
        cur.execute('EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF) ' + sql)
        print('\n'.join(r[0] for r in cur.fetchall()))
    conn.close()
